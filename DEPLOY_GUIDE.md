# Инструкция по развертыванию мульти-шкафного сервера ПР200 на новом VPS

## 0. Что сохранить на компьютере перед переносом или удалением старого VPS
Убедитесь, что у вас на компьютере (в папке `C:\Users\PR200_server`) сохранены актуальные файлы:
* `main.py` — код мульти-шкафного сервера (`PR200 Multi-Cabinet Server`).
* `convert_map.py` — конвертер выгрузок из Owen Logic в JSON-карты шкафов.
* Папка или файлы карт шкафов (`shkaf_01.json`, `shkaf_02.json` и т.д.).
* *(Опционально)* Скачать накопленную историю и все карты со старого сервера на ПК:
  ```bash
  scp root@152.228.98.9:/opt/pr200_server/telemetry.db .
  scp -r root@152.228.98.9:/opt/pr200_server/maps .
  ```

---

## 1. Создание нового VPS
1. Закажите бокс/VPS с образом **Ubuntu 24.04 LTS** и выделенным IPv4.
2. Запишите выданные **`<НОВЫЙ_IP>`** и **пароль от `root`**.

---

## 2. Установка среды и настройка защиты на новом VPS (1 блок команд)
1. Подключитесь к серверу из командной строки Windows (`cmd`):
   ```bash
   ssh root@<НОВЫЙ_IP>
   ```
2. Сразу смените временный пароль `root` на свой надежный:
   ```bash
   passwd
   ```
3. Выполните единый блок установки (ставит Python, библиотеки, Caddy для HTTPS, файрвол `ufw`, защиту от подбора паролей `fail2ban`, создает папки и службу автозапуска):
   ```bash
   apt update && apt install -y python3-venv python3-pip caddy ufw fail2ban
   systemctl enable --now fail2ban

   mkdir -p /opt/pr200_server/maps
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
   ExecStart=/opt/pr200_server/venv/bin/python main.py
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   EOF

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
   chmod 700 /opt/pr200_server /opt/pr200_server/maps
   chmod 600 /opt/pr200_server/main.py /opt/pr200_server/maps/*.json

   systemctl start pr200
   systemctl status pr200
   ```
   *(Убедитесь, что появилась зеленая надпись `active (running)`, выход по клавише `q`)*.

---

## 4. Включение бесплатного HTTPS (SSL-сертификата)
Замените точки в `<НОВЫЙ_IP>` на дефисы (например, `152.228.98.9` -> `152-228-98-9.sslip.io`) и выполните в окне SSH:

```bash
cat << 'EOF' > /etc/caddy/Caddyfile
<НОВЫЙ_IP_ЧЕРЕЗ_ДЕФИС>.sslip.io {
    reverse_proxy localhost:8000
}
EOF

systemctl restart caddy
```
Через 15 секунд проверьте работу API по HTTPS: `https://<НОВЫЙ_IP_ЧЕРЕЗ_ДЕФИС>.sslip.io/docs`.

---

## 5. Подключение шкафов (HF2211) и приложения Flutter
1. **В каждом модуле HF2211** (`COMMUNICATION SETTINGS`):
   * **Protocol:** `Tcp Client`
   * **Server:** `<НОВЫЙ_IP>` (через точки), **Server Port:** `9000`
   * **Register Mode:** `Link`
   * **Register Code:** `ID:shkaf_01` (для следующих шкафов: `ID:shkaf_02`, `ID:shkaf_03`...)
   * Нажмите **`Submit`** и перезагрузите модуль (**`OTHERS -> Restart`**).
2. **Добавление нового шкафа в будущем:**
   * Сгенерируйте карту через `convert_map.py` -> загрузите файл `shkaf_02.json` в `/opt/pr200_server/maps/` (через `scp` или `POST /api/cabinets/shkaf_02/map`) -> выставите `chmod 600 /opt/pr200_server/maps/*.json`. Перезапуск сервера не требуется.
3. **В мобильном приложении на Flutter:**
   * Укажите `baseUrl = 'https://<НОВЫЙ_IP_ЧЕРЕЗ_ДЕФИС>.sslip.io'` и клиентский `apiKey` из нужного файла `shkaf_XX.json`.
