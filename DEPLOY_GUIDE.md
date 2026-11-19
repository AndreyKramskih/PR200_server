# Инструкция по развертыванию мульти-шкафного сервера ПР200 на VPS

## 0. Что сохранить на компьютере перед переносом или удалением старого VPS
Убедитесь, что у вас на компьютере (в папке проекта, например `C:\Users\PR200_server`) сохранены актуальные файлы:
* `install.sh` — автоматический скрипт развертывания сервера.
* `main.py` — код мульти-шкафного сервера (`PR200 Multi-Cabinet Server`).
* `convert_map.py` — конвертер выгрузок из Owen Logic в JSON-карты шкафов.
* Карты шкафов (`shkaf_01.json`, `shkaf_02.json` и т.д.).
* *(Опционально)* Скачать актуальную копию истории и все карты со старого сервера на ПК перед удалением бокса:
  ```bash
  ssh root@<СТАРЫЙ_IP> "sqlite3 /opt/pr200_server/telemetry.db \".backup '/tmp/telemetry.db'\""
  scp root@<СТАРЫЙ_IP>:/tmp/telemetry.db .
  scp -r root@<СТАРЫЙ_IP>:/opt/pr200_server/maps .
  ```

---

## 1. Создание нового VPS
1. Закажите бокс/VPS с образом **Ubuntu 24.04 LTS** и выделенным IPv4.
2. Запишите выданные **`<НОВЫЙ_IP>`** и **пароль от `root`**.

---

## 2. Установка среды, переменной окружения и защиты (ручной способ)
1. Подключитесь к серверу из командной строки Windows (`cmd`):
   ```bash
   ssh root@<НОВЫЙ_IP>
   ```
2. Сразу смените временный пароль `root` на свой надежный:
   ```bash
   passwd
   ```
3. Придумайте надежный мастер-ключ администратора (замените им `<ВАШ_НОВЫЙ_МАСТЕР_КЛЮЧ>` в команде ниже) и выполните этот единый блок в окне SSH:
   ```bash
   apt update && apt install -y python3-venv python3-pip caddy ufw fail2ban sqlite3
   systemctl enable --now fail2ban

   mkdir -p /opt/pr200_server/maps /opt/pr200_server/backups
   python3 -m venv /opt/pr200_server/venv
   /opt/pr200_server/venv/bin/pip install fastapi uvicorn aiosqlite

   ufw allow 22/tcp
   ufw allow 80/tcp
   ufw allow 443/tcp
   ufw allow 9000/tcp
   ufw --force enable

   cat << 'EOF' > /etc/systemd/system/pr200.service
   [Unit]
   Description=PR200 Multi-Cabinet Telemetry Server
   After=network.target

   [Service]
   WorkingDirectory=/opt/pr200_server
   Environment="PR200_MASTER_KEY=<ВАШ_НОВЫЙ_МАСТЕР_КЛЮЧ>"
   ExecStart=/opt/pr200_server/venv/bin/python main.py
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   EOF

   chmod 600 /etc/systemd/system/pr200.service
   systemctl daemon-reload
   systemctl enable pr200
   ```

---

## 3. Загрузка файлов, установка прав защиты и запуск
1. Откройте **второе окно `cmd`** на Windows в папке с проектом (`cd C:\Users\PR200_server`) и загрузите `main.py` и JSON-карты шкафов в папку `maps/`:
   ```bash
   scp main.py root@<НОВЫЙ_IP>:/opt/pr200_server/
   scp shkaf_*.json root@<НОВЫЙ_IP>:/opt/pr200_server/maps/
   ```
   *(Если скачивали `telemetry.db`, скопируйте её так же: `scp telemetry.db root@<НОВЫЙ_IP>:/opt/pr200_server/`)*.

2. Вернитесь в **первое окно SSH**, закройте доступ к файлам с ключами для посторонних процессов (`chmod`) и запустите сервер:
   ```bash
   chmod 700 /opt/pr200_server /opt/pr200_server/maps /opt/pr200_server/backups
   chmod 600 /opt/pr200_server/main.py /opt/pr200_server/maps/*.json

   systemctl start pr200
   systemctl status pr200
   ```
   *(Убедитесь, что появилась зеленая надпись `active (running)`, выход по клавише `q`)*.
---

## 4. Включение бесплатного HTTPS (SSL-сертификата)
Замените точки в `<НОВЫЙ_IP>` на дефисы (например, `185.10.20.30` -> `185-10-20-30.sslip.io`) и выполните в окне SSH:

```bash
cat << 'EOF' > /etc/caddy/Caddyfile
<НОВЫЙ_IP_ЧЕРЕЗ_ДЕФИС>.sslip.io {
    reverse_proxy localhost:8000
}
EOF

systemctl restart caddy
```
Через 15–20 секунд проверьте работу API по HTTPS в браузере: `https://<НОВЫЙ_IP_ЧЕРЕЗ_ДЕФИС>.sslip.io/docs`.

---

## 5. Подключение шкафов (HF2211) и приложения Flutter
1. **В каждом модуле HF2211** (`COMMUNICATION SETTINGS`):
   * **Protocol:** `Tcp Client`
   * **Server:** `<НОВЫЙ_IP>` (через точки), **Server Port:** `9000`
   * **Register Mode:** `Link`
   * **Register Code:** `ID:shkaf_01` (для следующих шкафов: `ID:shkaf_02`, `ID:shkaf_03`...)
   * Нажмите **`Submit`** и перезагрузите модуль (**`OTHERS -> Restart`**).
2. **Добавление нового шкафа в будущем:**
   * Сгенерируйте карту через `convert_map.py` (указав имя шкафа и `Slave ID`).
   * Загрузите файл `shkaf_02.json` в `/opt/pr200_server/maps/` (через `scp` или `POST /api/cabinets/shkaf_02/map`).
   * Выставьте права `chmod 600 /opt/pr200_server/maps/*.json`. Перезапуск сервера не требуется.
3. **В мобильном приложении на Flutter:**
   * Укажите `baseUrl = 'https://<НОВЫЙ_IP_ЧЕРЕЗ_ДЕФИС>.sslip.io'` и клиентский `apiKey` из нужного файла `shkaf_XX.json`.

---

## 6. Обслуживание, смена мастер-ключа и восстановление БД из бэкапа
1. **Смена мастер-ключа на работающем сервере:**
   ```bash
   sed -i 's/Environment="PR200_MASTER_KEY=.*"/Environment="PR200_MASTER_KEY=<НОВЫЙ_МАСТЕР_КЛЮЧ>"/' /etc/systemd/system/pr200.service
   systemctl daemon-reload
   systemctl restart pr200
   systemctl status pr200
   ```
2. **Автоматический бэкап и восстановление при сбое БД:**
   * Каждый день в `03:30` сервер проверяет целостность базы (`PRAGMA integrity_check`) и сохраняет сжатую копию в `/opt/pr200_server/backups/` (хранятся 3 последних исправных снимка). Лог проверок: `/opt/pr200_server/backups/backup.log`.
   * Если потребуется восстановить базу из архива:
     ```bash
     systemctl stop pr200
     rm -f /opt/pr200_server/telemetry.db*
     gunzip -c /opt/pr200_server/backups/<ИМЯ_АРХИВА>.db.gz > /opt/pr200_server/telemetry.db
     chmod 600 /opt/pr200_server/telemetry.db
     systemctl start pr200
     ```

---

## 7. Автоматическая установка и настройка через `install.sh` (быстрый запуск)
1. **С вашего Windows ПК** (откройте `cmd` в папке с проектом `cd C:\Users\PR200_server`) скопируйте на новый VPS сразу все файлы (`install.sh`, `main.py` и карты `shkaf_*.json`):
   ```bash
   scp install.sh main.py shkaf_*.json root@<НОВЫЙ_IP>:/root/
   ```
   *(Если сохраняли бекап базы `telemetry.db`, просто добавьте её в ту же команду `scp`)*.

2. **Подключитесь по SSH и запустите установщик** (команда `tr -d '\r'` автоматически уберет невидимые символы переноса строк Windows, чтобы Linux не ругался на формат файла):
   ```bash
   ssh root@<НОВЫЙ_IP>
   tr -d \('\r' < /\)root/install.sh > /root/run_install.sh && bash /root/run_install.sh
   ```
3. Следуйте подсказкам скрипта в терминале:
   * Смените временный пароль `root` на свой надежный.
   * Введите свой мастер-ключ администратора (или нажмите `Enter`, чтобы скрипт сгенерировал его автоматически).
   * Введите токен Telegram-бота и свой числовой `Chat ID` для получения уведомлений о сбоях службы или повреждении базы (или нажмите `Enter`, чтобы пропустить).
   * Дождитесь завершения — скрипт сам выполнит шаги из разделов 2–4 (настроит `ufw`, `fail2ban`, Python, Telegram-алерты, ежесуточный бэкап с проверкой целостности, права `chmod`, выпустит SSL-сертификат через `caddy` и запустит службу `pr200`).
4. После проверки работы удалите временные файлы установщика из `/root/`:
   ```bash
   rm -f /root/install.sh /root/run_install.sh
   ```
