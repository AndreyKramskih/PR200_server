
import os
import smtplib
import sys
from email.message import EmailMessage

SMTP_HOST = os.getenv("PR200_SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("PR200_SMTP_PORT", "465"))
SMTP_USER = os.getenv("PR200_SMTP_USER", "")
SMTP_PASS = os.getenv("PR200_SMTP_PASS", "")
MAIL_TO = os.getenv("PR200_MAIL_TO", SMTP_USER)

def send_alert(subject: str, body: str):
    if not SMTP_USER or not SMTP_PASS:
        print("[MAIL] Почта не настроена")
        return
    msg = EmailMessage()
    msg["Subject"] = f"[PR200 Server] {subject}"
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.set_content(str(body))
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"[MAIL] Письмо отправлено: {subject}")
    except Exception as e:
        print(f"[MAIL ERROR] {e}")

if __name__ == "__main__":
    subj = sys.argv[1] if len(sys.argv) > 1 else "Тест связи"
    text = sys.argv[2] if len(sys.argv) > 2 else "Уведомления с сервера ПР200 работают!"
    send_alert(subj, text)




