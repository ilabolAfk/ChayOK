"""Уведомления на почту из ЧайОК.

Отправка идёт в фоновом потоке через очередь, чтобы никогда не тормозить
основной цикл. Одинаковые события троттлятся (не чаще min_interval_sec).

Конфиг: /home/pi/ChayOK/notify.json
    {
      "enabled": true,
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 465,
      "user": "you@gmail.com",
      "password": "app-password",
      "to": "you@gmail.com",
      "min_interval_sec": 300
    }

Пароль — только «пароль приложения» Google, обычный пароль не подойдёт.
Файл должен быть доступен только владельцу: chmod 600 notify.json
"""

import json
import os
import queue
import smtplib
import threading
import time
from email.message import EmailMessage

BASE_DIR = "/home/pi/ChayOK"
CONFIG_FILE = os.path.join(BASE_DIR, "notify.json")

_queue = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False
_last_sent = {}
DEFAULT_INTERVAL = 300


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {}
    cfg.setdefault("smtp_host", "smtp.gmail.com")
    cfg.setdefault("smtp_port", 465)
    cfg.setdefault("min_interval_sec", DEFAULT_INTERVAL)
    cfg.setdefault("enabled", False)
    return cfg


def _send_blocking(subject, body, cfg):
    msg = EmailMessage()
    msg["From"] = cfg.get("user", "")
    msg["To"] = cfg.get("to", "") or cfg.get("user", "")
    msg["Subject"] = subject
    msg.set_content(body)

    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 465))
    user = cfg.get("user", "")
    password = cfg.get("password", "")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=25) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)


def _worker():
    while True:
        subject, body = _queue.get()
        try:
            cfg = load_config()
            if not cfg.get("enabled") or not cfg.get("password"):
                print("[notify] отправка выключена или нет пароля")
                continue
            _send_blocking(subject, body, cfg)
            print(f"[notify] отправлено: {subject}")
        except Exception as e:
            print(f"[notify] ошибка отправки: {e}")
        finally:
            _queue.task_done()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True


def notify(subject, body="", key=None, force=False):
    """Ставит письмо в очередь. key — для троттлинга одинаковых событий."""
    _ensure_worker()
    if key and not force:
        cfg = load_config()
        interval = int(cfg.get("min_interval_sec", DEFAULT_INTERVAL))
        last = _last_sent.get(key, 0)
        if time.time() - last < interval:
            return False
        _last_sent[key] = time.time()
    _queue.put((subject, body or subject))
    return True


def is_configured():
    cfg = load_config()
    return bool(cfg.get("enabled") and cfg.get("password"))


def flush(timeout=5.0):
    """Дождаться отправки очереди (для штатного завершения)."""
    _ensure_worker()
    waiter = threading.Thread(target=_queue.join, daemon=True)
    waiter.start()
    waiter.join(timeout)


if __name__ == "__main__":
    print("конфиг:", CONFIG_FILE)
    print("настроено:", is_configured())
    notify("ЧайОК: проверка связи", "Это тестовое письмо от голосового помощника.", force=True)
    _queue.join()
