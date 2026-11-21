"""Таймер ЧайОК: отсчёт, затем звонок melody1, пока не остановят.

Команды: «таймер на 5 минут», «напомни через 20 минут», «стоп».
Пока звонок идёт, микрофон глухой (флаг в audio_guard ставит alarm.play_sound).
"""

import threading
import time

import alarm

_state = {
    "running": False,
    "ringing": False,
    "target": 0.0,
    "label": "",
}
_stop = threading.Event()
_lock = threading.Lock()
_thread = None


def _ring_until_stopped():
    """Играет мелодию по кругу до остановки."""
    while not _stop.is_set():
        if not alarm.play_sound("melody1.mp3", volume=0.95):
            # файла нет — хотя бы не крутимся вхолостую
            _stop.wait(5)
            continue
        while not _stop.is_set():
            proc = alarm._current_process
            if proc is None or proc.poll() is not None:
                break
            _stop.wait(0.2)


def _run(seconds, label):
    global _thread
    deadline = time.time() + seconds
    while not _stop.is_set():
        left = deadline - time.time()
        if left <= 0:
            break
        _stop.wait(min(0.5, left))

    if _stop.is_set():
        return

    with _lock:
        _state["ringing"] = True
        _state["running"] = False
        _state["target"] = 0.0

    print(f"ТАЙМЕР: время вышло ({label})")
    _ring_until_stopped()

    with _lock:
        _state["ringing"] = False


def start(seconds, label=""):
    global _thread
    seconds = max(1, int(seconds))
    stop(silent=True)
    _stop.clear()
    with _lock:
        _state["running"] = True
        _state["ringing"] = False
        _state["target"] = time.time() + seconds
        _state["label"] = label
    _thread = threading.Thread(target=_run, args=(seconds, label), daemon=True)
    _thread.start()
    return seconds


def stop(silent=False):
    """Гасит и отсчёт, и звонок."""
    # состояние читаем и сбрасываем ДО убийства плеера: иначе поток звонка
    # успевает сам снять флаг ringing и мы соврём «не запущен»
    with _lock:
        was = _state["running"] or _state["ringing"]
        _state["running"] = False
        _state["ringing"] = False
        _state["target"] = 0.0
        _state["label"] = ""
    _stop.set()
    try:
        alarm._kill_process()
    except Exception:
        pass
    if silent:
        return None
    return "Таймер выключен" if was else "Таймер не запущен"


def is_running():
    with _lock:
        return _state["running"]


def is_ringing():
    with _lock:
        return _state["ringing"]


def remaining():
    with _lock:
        if not _state["running"]:
            return None
        left = _state["target"] - time.time()
    return max(0, int(round(left)))


def describe():
    """Короткая строка для экрана: «Таймер 04:32»."""
    with _lock:
        ringing = _state["ringing"]
    if ringing:
        return "Таймер: время вышло"
    left = remaining()
    if left is None:
        return ""
    minutes, seconds = divmod(left, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"Таймер {hours}:{minutes:02d}:{seconds:02d}"
    return f"Таймер {minutes:02d}:{seconds:02d}"
