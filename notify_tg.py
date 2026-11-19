
code = """import json, os, re, sys, urllib.request

def load_env(path="/opt/pr200_server/.env"):
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().replace("\\r", "")
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\\x22\\x27")
    return env

def send_alert(subject: str, body: str):
    cfg = load_env()
    token = re.sub(r"[^0-9A-Za-z:_-]", "", cfg.get("PR200_TG_TOKEN") or os.getenv("PR200_TG_TOKEN", ""))
    chat_id = re.sub(r"[^0-9-]", "", cfg.get("PR200_TG_CHAT_ID") or os.getenv("PR200_TG_CHAT_ID", ""))
    if not token or not chat_id:
        print("[TG] Не заданы PR200_TG_TOKEN или PR200_TG_CHAT_ID")
        return
    url = "https://" + "api.telegram.org/" + "bot" + token + "/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": f"🚨 [PR200 Server] {subject}\\n\\n{body}"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"[TG] Уведомление отправлено: {subject}")
    except Exception as e:
        print(f"[TG ERROR] {e}")

if __name__ == "__main__":
    s = sys.argv[1] if len(sys.argv) > 1 else "Тест"
    b = sys.argv[2] if len(sys.argv) > 2 else "Проверка отправки"
    send_alert(s, b)
"""
open("/opt/pr200_server/notify_tg.py", "w", encoding="utf-8").write(code)
