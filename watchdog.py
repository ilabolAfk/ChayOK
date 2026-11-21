"""Сторож llama-server: письмо при падении и подъёме, автоподъём.

Работает в отдельном потоке внутри приложения. Проверка раз в 30 секунд:
если сервер перестал отвечать — письмо и попытка перезапуска через
restart_llm.sh; когда поднимется — второе письмо.
"""

import subprocess
import threading
import time

import requests

import notifier

LLM_URL = "http://127.0.0.1:8080/props"
CHECK_INTERVAL = 30
RESTART_SCRIPT = "/home/pi/ChayOK/restart_llm.sh"


def is_alive(timeout=4):
    try:
        return requests.get(LLM_URL, timeout=timeout).status_code == 200
    except Exception:
        return False


def restart():
    try:
        subprocess.Popen(["bash", RESTART_SCRIPT],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print("[watchdog] не смог перезапустить:", e)
        return False


def monitor(restart_enabled=True, ui=None):
    """Бесконечный цикл наблюдения. Первое состояние только запоминается."""
    state = is_alive()
    primed = True
    down_at = 0.0

    while True:
        time.sleep(CHECK_INTERVAL)
        alive = is_alive()
        if alive == state:
            continue
        state = alive

        if not alive:
            down_at = time.time()
            print("[watchdog] сервер LLM не отвечает")
            notifier.notify(
                "ЧайОК: сервер LLM упал",
                f"llama-server не отвечает ({LLM_URL}).\n"
                f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}\n"
                "Пытаюсь поднять автоматически.",
                key="llm_down",
            )
            if restart_enabled and restart():
                print("[watchdog] перезапуск запущен")
        else:
            recovered = down_at and (time.time() - down_at) < 300
            print("[watchdog] сервер LLM отвечает")
            notifier.notify(
                "ЧайОК: сервер LLM восстановлен" if recovered else "ЧайОК: сервер LLM поднялся",
                f"llama-server снова отвечает ({LLM_URL}).\n"
                f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}",
                key="llm_up",
            )
            down_at = 0.0


def start(restart_enabled=True, ui=None):
    threading.Thread(target=monitor, args=(restart_enabled, ui), daemon=True).start()
