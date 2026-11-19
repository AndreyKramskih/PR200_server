import asyncio, glob, json, os, struct, time
from contextlib import asynccontextmanager
import aiosqlite
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
import uvicorn

# --- НАСТРОЙКИ ---
BASE_DIR = "/opt/pr200_server"
MAPS_DIR = f"{BASE_DIR}/maps"
LEGACY_MAP_PATH = f"{BASE_DIR}/map.json"
DB_PATH = f"{BASE_DIR}/telemetry.db"

TCP_PORT = 9000
API_PORT = 8000
DEFAULT_SLAVE_ID, MAX_CHUNK = 16, 12
MASTER_API_KEY = os.getenv("PR200_MASTER_KEY", "dev-local-key")

RETENTION_DAYS = 90

cabinets, write_q = {}, {}
db_status = {"ok": True, "last_error": None}
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_cab_map_path(cab_id: str) -> str:
    os.makedirs(MAPS_DIR, exist_ok=True)
    specific = os.path.join(MAPS_DIR, f"{cab_id}.json")
    if os.path.exists(specific):
        return specific
    if cab_id == "shkaf_01" and os.path.exists(LEGACY_MAP_PATH):
        return LEGACY_MAP_PATH
    return specific


def load_cab_map(cab_id: str) -> dict:
    path = get_cab_map_path(cab_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"start_reg": 512, "total_regs": 12, "tags": {}}


def get_all_keys_map() -> dict[str, str]:
    keys = {}
    os.makedirs(MAPS_DIR, exist_ok=True)
    files = glob.glob(os.path.join(MAPS_DIR, "*.json"))
    if os.path.exists(LEGACY_MAP_PATH):
        files.append(LEGACY_MAP_PATH)
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            k = data.get("api_key")
            cab = "shkaf_01" if fp == LEGACY_MAP_PATH else os.path.splitext(os.path.basename(fp))[0]
            if k:
                keys[k] = cab
        except Exception:
            pass
    return keys


async def get_authorized_scope(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(status_code=403, detail="Отсутствует X-API-Key")
    if api_key == MASTER_API_KEY:
        return "*"
    cab_id = get_all_keys_map().get(api_key)
    if not cab_id:
        raise HTTPException(status_code=403, detail="Неверный X-API-Key")
    return cab_id


def check_cab_access(scope: str, cab_id: str):
    if scope != "*" and scope != cab_id:
        raise HTTPException(status_code=403, detail="Нет доступа к этому шкафу")


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
    return struct.pack("<H", crc)


def modbus_req(slave_id: int, func: int, addr: int, val_or_cnt: int, extra: bytes = b"") -> bytes:
    f = struct.pack(">BBHH", slave_id, func, addr, val_or_cnt) + extra
    return f + crc16(f)


def decode(regs_dict: dict[int, int], tags: dict) -> dict:
    out = {}
    for name, info in tags.items():
        r, t = info["reg"], info["type"]
        if r not in regs_dict:
            continue
        if t == "word":
            out[name] = regs_dict[r]
        elif t == "float" and (r + 1) in regs_dict:
            raw = struct.pack(">HH", regs_dict[r + 1], regs_dict[r])
            out[name] = round(struct.unpack(">f", raw)[0], 2)
    return out
async def handle_hf2211_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    cab_id = "shkaf_01"
    try:
        try:
            hello = await asyncio.wait_for(reader.read(64), timeout=1.5)
            text = hello.decode("utf-8", errors="ignore").strip()
            if text.startswith("ID:"):
                cab_id = text.split(":", 1)[1].strip()
        except asyncio.TimeoutError:
            pass

        print(f"[{cab_id}] Подключился с {writer.get_extra_info('peername')}")
        cabinets[cab_id] = {"online": True, "ts": 0, "tags": {}}
        write_q[cab_id] = asyncio.Queue()
        last_save = 0.0

        while True:
            cfg = load_cab_map(cab_id)
            slave_id = cfg.get("slave_id", DEFAULT_SLAVE_ID)

            while not write_q[cab_id].empty():
                addr, dtype, val = await write_q[cab_id].get()
                if dtype == "float":
                    hi, lo = struct.unpack(">HH", struct.pack(">f", float(val)))
                    pkt = modbus_req(slave_id, 0x10, addr, 2, b"\x04" + struct.pack(">HH", lo, hi))
                else:
                    pkt = modbus_req(slave_id, 0x06, addr, int(val) & 0xFFFF)
                writer.write(pkt)
                await writer.drain()
                await asyncio.wait_for(reader.read(64), timeout=2.0)

            start, total = cfg["start_reg"], cfg["total_regs"]
            regs_map = {}

            for offset in range(0, total, MAX_CHUNK):
                chunk_len = min(MAX_CHUNK, total - offset)
                chunk_start = start + offset
                writer.write(modbus_req(slave_id, 0x03, chunk_start, chunk_len))
                await writer.drain()
                resp = await asyncio.wait_for(reader.readexactly(5 + chunk_len * 2), timeout=2.0)
                if crc16(resp[:-2]) == resp[-2:]:
                    vals = struct.unpack(f">{chunk_len}H", resp[3:-2])
                    for i, v in enumerate(vals):
                        regs_map[chunk_start + i] = v

            if regs_map:
                now = time.time()
                tags = decode(regs_map, cfg.get("tags", {}))
                cabinets[cab_id] = {"online": True, "ts": round(now, 1), "tags": tags}
                if now - last_save >= 10.0:
                    last_save = now
                    tags_cfg = cfg.get("tags", {})
                    rows_to_save = [
                        (cab_id, now, k, float(v))
                        for k, v in tags.items()
                        if tags_cfg.get(k, {}).get("log", False)
                    ]
                    if rows_to_save:
                        try:
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.executemany("INSERT INTO log VALUES (?, ?, ?, ?)", rows_to_save)
                                await db.commit()
                            db_status["ok"] = True
                            db_status["last_error"] = None
                        except Exception as db_err:
                            db_status["ok"] = False
                            db_status["last_error"] = str(db_err)
                            print(f"[DB ERROR] Ошибка записи истории: {db_err}")

            await asyncio.sleep(1.0)
    except Exception as e:
        print(f"[{cab_id}] Отключился: {e}")
    finally:
        if cab_id in cabinets:
            cabinets[cab_id]["online"] = False
        write_q.pop(cab_id, None)
        writer.close()


async def cleanup_old_records():
    while True:
        try:
            cutoff_ts = time.time() - (RETENTION_DAYS * 86400)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM log WHERE ts < ?", (cutoff_ts,))
                await db.commit()
                await db.execute("PRAGMA incremental_vacuum")
        except Exception as e:
            print(f"[DB CLEANUP ERROR] {e}")
        await asyncio.sleep(86400)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(MAPS_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA auto_vacuum = INCREMENTAL")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("CREATE TABLE IF NOT EXISTS log (cab TEXT, ts REAL, tag TEXT, val REAL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_log_query ON log (cab, tag, ts)")
        await db.commit()
    tcp_srv = await asyncio.start_server(handle_hf2211_tcp, "0.0.0.0", TCP_PORT)
    t_clean = asyncio.create_task(cleanup_old_records())
    yield
    t_clean.cancel()
    tcp_srv.close()


app = FastAPI(title="PR200 Multi-Cabinet Server", lifespan=lifespan)


class Cmd(BaseModel):
    reg_addr: int
    dtype: str = "word"
    value: float


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "db_ok": db_status["ok"], "db_error": db_status["last_error"]}


@app.get("/api/cabinets")
async def get_all(scope: str = Depends(get_authorized_scope)):
    if scope == "*":
        return cabinets
    return {scope: cabinets[scope]} if scope in cabinets else {}


@app.get("/api/cabinets/{cab_id}/history")
async def get_history(
    cab_id: str,
    tags: str | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    limit: int = 1000,
    scope: str = Depends(get_authorized_scope)
):
    check_cab_access(scope, cab_id)
    now = time.time()
    start_t = from_ts if from_ts is not None else (now - 3600)
    end_t = to_ts if to_ts is not None else now
    query = "SELECT ts, tag, val FROM log WHERE cab = ? AND ts >= ? AND ts <= ?"
    params: list = [cab_id, start_t, end_t]
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        query += f" AND tag IN ({','.join('?' for _ in tag_list)})"
        params.extend(tag_list)
    query += " ORDER BY ts ASC LIMIT ?"
    params.append(limit)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
    except Exception as db_err:
        db_status["ok"] = False
        db_status["last_error"] = str(db_err)
        raise HTTPException(status_code=500, detail=f"Ошибка чтения БД: {db_err}")
    grouped: dict[str, list] = {}
    for ts_val, tag_name, val in rows:
        grouped.setdefault(tag_name, []).append([round(ts_val, 1), val])
    return {"cabinet_id": cab_id, "from_ts": start_t, "to_ts": end_t, "series": grouped}


@app.get("/api/cabinets/{cab_id}/map")
async def get_cab_map(cab_id: str, scope: str = Depends(get_authorized_scope)):
    check_cab_access(scope, cab_id)
    return load_cab_map(cab_id)


@app.post("/api/cabinets/{cab_id}/map")
async def save_cab_map(cab_id: str, new_map: dict, scope: str = Depends(get_authorized_scope)):
    if scope != "*":
        raise HTTPException(status_code=403, detail="Загружать карты может только мастер-ключ")
    os.makedirs(MAPS_DIR, exist_ok=True)
    with open(os.path.join(MAPS_DIR, f"{cab_id}.json"), "w", encoding="utf-8") as f:
        json.dump(new_map, f, ensure_ascii=False, indent=2)
    return {"status": "saved", "cabinet_id": cab_id}


@app.post("/api/cabinets/{cab_id}/write")
async def write_cmd(cab_id: str, cmd: Cmd, scope: str = Depends(get_authorized_scope)):
    check_cab_access(scope, cab_id)
    if cab_id not in write_q:
        raise HTTPException(503, "Offline")
    await write_q[cab_id].put((cmd.reg_addr, cmd.dtype, cmd.value))
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=API_PORT)
