import csv
import json
import os
import re
import secrets
import sys


def read_owen_csv(csv_path: str) -> list[dict]:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            with open(csv_path, "r", encoding=enc) as f:
                sample = f.read(1024)
                f.seek(0)
                delim = ";" if sample.count(";") > sample.count(",") else ","
                reader = csv.DictReader(f, delimiter=delim)
                rows = list(reader)
                if rows and ("VariableName" in rows[0] or "Имя переменной" in rows[0]):
                    return rows
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось прочитать файл экспорта Owen Logic")


def csv_to_map(csv_path: str, cab_id: str, slave_id: int = 16):
    json_path = f"{cab_id}.json"
    raw_rows = read_owen_csv(csv_path)
    rows = []
    for r in raw_rows:
        name = (r.get("VariableName") or r.get("Имя переменной") or "").strip()
        vtype = (r.get("VariableType") or r.get("Тип переменной") or "").strip().lower()
        reg_str = (r.get("Register") or r.get("Адрес регистра") or "").strip()
        comment = (r.get("Comment") or r.get("Комментарий") or "").strip()

        if not name or name == "Имя переменной" or not reg_str.isdigit():
            continue

        rows.append({
            "name": name,
            "vtype": vtype,
            "addr": int(reg_str),
            "comment": comment
        })

    rows.sort(key=lambda x: x["addr"])

    tags = {}
    for i, item in enumerate(rows):
        next_addr = rows[i + 1]["addr"] if i + 1 < len(rows) else None
        is_float = (item["vtype"] == "float") or (
                next_addr is not None and next_addr - item["addr"] >= 2 and item["addr"] >= 540
        )

        is_logged = bool(re.search(r'(?i)(?:^|\s|\[)log(?:\]|\s|$)', item["comment"]))
        clean_comment = re.sub(r'(?i)(?:\s*\[?log\]?\s*)', ' ', item["comment"]).strip()

        tags[item["name"]] = {
            "reg": item["addr"],
            "type": "float" if is_float else "word",
            "log": is_logged,
            "comment": clean_comment
        }

    start_reg = rows[0]["addr"]
    last_item = rows[-1]
    last_size = 2 if tags[last_item["name"]]["type"] == "float" else 1
    total_regs = (last_item["addr"] - start_reg) + last_size

    existing_key = None
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing_key = json.load(f).get("api_key")
        except Exception:
            pass

    api_key = existing_key or secrets.token_urlsafe(24)

    result = {
        "api_key": api_key,
        "slave_id": slave_id,
        "start_reg": start_reg,
        "total_regs": total_regs,
        "tags": tags
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logged_cnt = sum(1 for t in tags.values() if t["log"])
    print(f"\nГотово! Файл сохранен как: {json_path}")
    print(f"Адрес Modbus (Slave ID): {slave_id}")
    print(f"Всего тегов: {len(tags)}, в историю пишется: {logged_cnt}")
    print(f"API-ключ клиента (X-API-Key): {api_key}")
    print(f"Строка для HF2211 (Register Data): ID:{cab_id}")
    print(f"Команда загрузки на сервер: scp {json_path} root@152.228.98.9:/opt/pr200_server/maps/")


if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "registers.csv"

    cab_name = input("Введите имя шкафа латиницей (например, shkaf_02) [Enter = shkaf_01]: ").strip()
    if not cab_name:
        cab_name = "shkaf_01"

    slave_str = input("Введите сетевой адрес ПР200 Slave ID [Enter = 16]: ").strip()
    slave_num = int(slave_str) if slave_str.isdigit() else 16

    csv_to_map(csv_file, cab_name, slave_num)
