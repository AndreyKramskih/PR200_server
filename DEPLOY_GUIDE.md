# Инструкция по развертыванию мульти-шкафного сервера ПР200 на VPS

## 0. Что сохранить на компьютере перед переносом или удалением старого VPS
Убедитесь, что у вас на компьютере (в папке проекта, например `C:\Users\PR200_server`) сохранены актуальные файлы:
* `main.py` — код мульти-шкафного сервера (`PR200 Multi-Cabinet Server`).
* `convert_map.py` — конвертер выгрузок из Owen Logic в JSON-карты шкафов.
* Карты шкафов (`shkaf_01.json`, `shkaf_02.json` и т.д.).
* *(Опционально)* Скачать накопленную историю и все карты со старого сервера на ПК перед удалением бокса:
  ```bash
  scp root@<СТАРЫЙ_IP>:/opt/pr200_server/telemetry.db .
  scp -r root@<СТАРЫЙ_IP>:/opt/pr200_server/maps .
  ```

---

## 1. Создание нового VPS
1. Закажите бокс/VPS с образом **Ubuntu 24.04 LTS** и выделенным IPv4.
2. Запишите выданные **`<НОВЫЙ_IP>`** и **пароль от `root`**.

---

## 2. Установка среды, переменной окружения и защиты (1 блок команд)
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
   chmod 700 /opt/pr200_server /opt/pr200_server/maps
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

## 6. Обслуживание и смена мастер-ключа на работающем сервере
Если потребуется заменить мастер-ключ администратора без правки `main.py` и без остановки клиентских шкафов, подключитесь по SSH и выполните (подставив новый ключ вместо `<НОВЫЙ_МАСТЕР_КЛЮЧ>`):

```bash
sed -i 's/Environment="PR200_MASTER_KEY=.*"/Environment="PR200_MASTER_KEY=<НОВЫЙ_МАСТЕР_КЛЮЧ>"/' /etc/systemd/system/pr200.service
systemctl daemon-reload
systemctl restart pr200
systemctl status pr200
```
*(Клиентские ключи в файлах `shkaf_*.json` при этом не меняются и продолжают работать в штатном режиме).*
