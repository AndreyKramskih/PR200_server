#!/usr/bin/env bash
set -e

echo "=== Установка PR200 Multi-Cabinet Telemetry Server ==="

# 1. Смена пароля root (по желанию)
read -rp "Хотите сменить пароль root прямо сейчас? (y/n) [y]: " CHANGE_PASS
CHANGE_PASS=${CHANGE_PASS:-y}
if [[ "$CHANGE_PASS" =~ ^[Yy]$ ]]; then
    passwd
fi

# 2. Ввод или автогенерация мастер-ключа
read -rp "Введите мастер-ключ администратора (Enter = сгенерировать автоматически): " MASTER_KEY
if [ -z "$MASTER_KEY" ]; then
    MASTER_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    echo "Сгенерирован мастер-ключ: $MASTER_KEY"
fi

# 3. Настройка Telegram-уведомлений (по желанию)
read -rp "Введите токен Telegram-бота для алертов (Enter = пропустить): " TG_TOKEN
TG_CHAT_ID=""
if [ -n "$TG_TOKEN" ]; then
    read -rp "Введите ваш числовой Telegram Chat ID: " TG_CHAT_ID
fi

# 4. Автоопределение IP-адреса сервера
SERVER_IP=$(curl -4 -s ifconfig.me || hostname -I | awk '{print $1}')
DOMAIN_DASHES="${SERVER_IP//./-}.sslip.io"
echo "Определен IP сервера: $SERVER_IP (домен HTTPS: $DOMAIN_DASHES)"

# 5. Установка системных пакетов, sqlite3 и защиты (ufw + fail2ban)
apt update && apt install -y python3-venv python3-pip caddy ufw fail2ban curl sqlite3
systemctl enable --now fail2ban

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 9000/tcp
ufw --force enable

# 6. Создание папок и виртуального окружения Python
mkdir -p /opt/pr200_server/maps /opt/pr200_server/backups
python3 -m venv /opt/pr200_server/venv
/opt/pr200_server/venv/bin/pip install --upgrade pip
/opt/pr200_server/venv/bin/pip install fastapi uvicorn aiosqlite

# 7. Копирование файлов проекта (если они лежат рядом с install.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/main.py" ] && [ "$SCRIPT_DIR" != "/opt/pr200_server" ]; then
    cp "$SCRIPT_DIR/main.py" /opt/pr200_server/
fi
if ls "$SCRIPT_DIR"/shkaf_*.json 1> /dev/null 2>&1 && [ "$SCRIPT_DIR" != "/opt/pr200_server" ]; then
    cp "$SCRIPT_DIR"/shkaf_*.json /opt/pr200_server/maps/
fi
if [ -f "$SCRIPT_DIR/telemetry.db" ] && [ "$SCRIPT_DIR" != "/opt/pr200_server" ]; then
    cp "$SCRIPT_DIR/telemetry.db" /opt/pr200_server/
fi

# 8. Создание конфигурации и скрипта Telegram-уведомлений
cat << EOF > /opt/pr200_server/.env
PR200_TG_TOKEN=$TG_TOKEN
PR200_TG_CHAT_ID=$TG_CHAT_ID
EOF
chmod 600 /opt/pr200_server/.env

cat << 'EOF' > /opt/pr200_server/notify_tg.py
import json
import os
import re
import sys
import urllib.request

def load_env_file(path="/opt/pr200_server/.env"):
    env_vars = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip().replace("\r", "")
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")
    return env_vars

def send_alert(subject: str, body: str):
    cfg = load_env_file()
    token = re.sub(r"[^0-9A-Za-z:_-]", "", cfg.get("PR200_TG_TOKEN") or os.getenv("PR200_TG_TOKEN", ""))
    chat_id = re.sub(r"[^0-9-]", "", cfg.get("PR200_TG_CHAT_ID") or os.getenv("PR200_TG_CHAT_ID", ""))

    if not token or not chat_id:
        return

    url = "https://" + "api.telegram.org/" + "bot" + token + "/sendMessage"

    payload = json.dumps({
        "chat_id": chat_id,
        "text": f"🚨 [PR200 Server] {subject}\n\n{body}"
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"[TG] Уведомление отправлено: {subject}")
    except Exception as e:
        print(f"[TG ERROR] {e}")

if __name__ == "__main__":
    subj = sys.argv[1] if len(sys.argv) > 1 else "Тест связи"
    text = sys.argv[2] if len(sys.argv) > 2 else "Уведомления с сервера ПР200 работают!"
    send_alert(subj, text)
EOF
chmod 600 /opt/pr200_server/notify_tg.py

# 9. Настройка ежесуточного бэкапа с проверкой целостности (хранение 3 последних сжатых копий)
cat << 'EOF' > /opt/pr200_server/backup_db.sh
#!/usr/bin/env bash
DB="/opt/pr200_server/telemetry.db"
BACKUP_DIR="/opt/pr200_server/backups"
TMP_DB="/tmp/telemetry_check.db"
DATE_STR=$(date +%Y-%m-%d_%H-%M)

[ ! -f "$DB" ] && exit 0

rm -f "$TMP_DB"
sqlite3 "$DB" ".backup '$TMP_DB'"

CHECK_RES=$(sqlite3 "$TMP_DB" "PRAGMA integrity_check;" 2>&1)
if [ "$CHECK_RES" = "ok" ]; then
    gzip -c "$TMP_DB" > "$BACKUP_DIR/telemetry_$DATE_STR.db.gz"
    chmod 600 "$BACKUP_DIR/telemetry_$DATE_STR.db.gz"
    ls -1t "$BACKUP_DIR"/telemetry_*.db.gz 2>/dev/null | tail -n +4 | xargs -r rm -f
    echo "[$DATE_STR] Бэкап успешно создан и проверен." >> "$BACKUP_DIR/backup.log"
else
    echo "[$DATE_STR] ТРЕВОГА: Ошибка целостности базы! ($CHECK_RES)" >> "$BACKUP_DIR/backup.log"
    /opt/pr200_server/venv/bin/python /opt/pr200_server/notify_tg.py "Повреждена база данных!" "Проверка integrity_check выявила ошибку: $CHECK_RES"
fi
rm -f "$TMP_DB"
EOF

chmod 700 /opt/pr200_server/backup_db.sh
(crontab -l 2>/dev/null | grep -v "backup_db.sh"; echo "30 3 * * * /opt/pr200_server/backup_db.sh") | crontab -

# 10. Настройка службы автозапуска systemd и сторожа сбоев
cat << EOF > /etc/systemd/system/pr200.service
[Unit]
Description=PR200 Multi-Cabinet Telemetry Server
After=network.target
OnFailure=pr200-alert@%n.service

[Service]
WorkingDirectory=/opt/pr200_server
Environment="PR200_MASTER_KEY=$MASTER_KEY"
ExecStart=/opt/pr200_server/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat << 'EOF' > /etc/systemd/system/pr200-alert@.service
[Unit]
Description=Send Telegram alert on %i failure

[Service]
Type=oneshot
ExecStart=/opt/pr200_server/venv/bin/python /opt/pr200_server/notify_tg.py "Сбой службы %i" "Служба %i аварийно остановилась. Проверьте журнал: journalctl -u %i -n 50"
EOF

chmod 600 /etc/systemd/system/pr200.service /etc/systemd/system/pr200-alert@.service
systemctl daemon-reload
systemctl enable pr200

# 11. Настройка HTTPS (Caddy + sslip.io)
cat << EOF > /etc/caddy/Caddyfile
$DOMAIN_DASHES {
    reverse_proxy localhost:8000
}
EOF

systemctl restart caddy

# 12. Права доступа и запуск
chmod 700 /opt/pr200_server /opt/pr200_server/maps /opt/pr200_server/backups
if [ -f /opt/pr200_server/main.py ]; then
    chmod 600 /opt/pr200_server/main.py
    ls /opt/pr200_server/maps/*.json 1> /dev/null 2>&1 && chmod 600 /opt/pr200_server/maps/*.json
    systemctl restart pr200
    echo "Служба pr200 запущена!"
else
    echo "ВНИМАНИЕ: Файл main.py еще не загружен в /opt/pr200_server/."
    echo "Загрузите main.py и карты шкафов, затем выполните: systemctl start pr200"
fi

if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
    /opt/pr200_server/venv/bin/python /opt/pr200_server/notify_tg.py "Сервер развернут" "Новый сервер $SERVER_IP успешно запущен и готов к работе!"
fi

echo ""
echo "========================================================"
echo "УСТАНОВКА ЗАВЕРШЕНА!"
echo "Адрес API (HTTPS): https://$DOMAIN_DASHES/docs"
echo "TCP-порт для HF2211: $SERVER_IP:9000"
echo "Мастер-ключ (сохраните его!): $MASTER_KEY"
echo "Ночные бэкапы (3 копии): /opt/pr200_server/backups/"
echo "========================================================"
