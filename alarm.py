#!/usr/bin/env python3
"""
Модуль будильника для ЧайОК
3 уровня: мягкий, средний, жёсткий
На 3-м повторе жёсткого уровня — громкое пиканье (как в CS)

Звук по умолчанию — sounds/melody1.mp3.
Проигрывание: ffplay → pw-play → mpg123 (что есть в системе).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime

import audio_guard
import volume as volume_mod

try:
    import radio as radio_mod
except Exception:  # модуль радио может отсутствовать при отдельном запуске
    radio_mod = None

BASE_DIR = "/home/pi/ChayOK"
ALARM_FILE = os.path.join(BASE_DIR, "alarm.json")
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")

PIPER_PATH = "/home/pi/piper/piper"
PIPER_MODEL = "/home/pi/piper/ru_RU-ruslan-medium.onnx"

os.makedirs(SOUNDS_DIR, exist_ok=True)
os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())

DEFAULT_SOUND = "melody1.mp3"
REPEAT_INTERVAL = 300  # 5 минут между повторами

LEVELS = {
    "мягкий": {
        "level": 1,
        "sound": DEFAULT_SOUND,
        "volume": 0.55,
        "voice": "Доброе утро! Пора вставать.",
        "label": "Мягкий",
    },
    "средний": {
        "level": 2,
        "sound": "melody2.mp3",
        "volume": 0.75,
        "voice": "Подъём! Хватит спать!",
        "label": "Средний",
    },
    "жёсткий": {
        "level": 3,
        "sound": "melody3.mp3",
        "volume": 0.95,
        "voice": "ПРОСНИСЬ! ВСТАВАЙ!",
        "label": "Жёсткий",
    },
}

alarm_stop = False
_current_process = None
_process_lock = threading.Lock()


# ========================================
# НАСТРОЙКИ
# ========================================


def load_alarm():
    try:
        with open(ALARM_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("level", "средний")
        data.setdefault("sound", LEVELS[data["level"]]["sound"])
        data.setdefault("enabled", False)
        return data
    except Exception:
        return {"enabled": False, "hour": 7, "minute": 0, "level": "мягкий", "sound": DEFAULT_SOUND}


def save_alarm(hour, minute, level="мягкий", enabled=True, sound=None):
    if level not in LEVELS:
        level = "средний"
    data = {
        "enabled": bool(enabled),
        "hour": int(hour),
        "minute": int(minute),
        "level": level,
        "sound": sound or LEVELS[level]["sound"],
    }
    with open(ALARM_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


# ========================================
# ВОСПРОИЗВЕДЕНИЕ
# ========================================


def _player_commands(path, volume):
    """Порядок важен: pw-play играет на тот же sink, что и озвучка.

    ffplay идёт последним — на этой плате он через SDL цепляется за встроенную
    звуковуху (bcm2835) и висит без звука.
    """
    volume = max(0.0, min(1.0, float(volume)))
    commands = []
    if shutil.which("pw-play"):
        commands.append((["pw-play", f"--volume={volume:.2f}", path], {}))
    if shutil.which("mpg123"):
        commands.append((["mpg123", "-q", "-f", str(int(32768 * volume)), path], {}))
    if shutil.which("cvlc"):
        commands.append((["cvlc", "--play-and-exit", "--quiet", "--intf", "dummy", path], {}))
    if shutil.which("ffplay"):
        commands.append((
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
             "-volume", str(int(volume * 100)), path],
            {"SDL_AUDIODRIVER": "pulse"},
        ))
    return commands


def _spawn(path, volume):
    """Запускает первый рабочий плеер, возвращает процесс или None."""
    for cmd, extra_env in _player_commands(path, volume):
        env = dict(os.environ)
        env.update(extra_env)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env)
        except Exception:
            continue
        time.sleep(0.6)
        if proc.poll() is None or proc.returncode == 0:
            return proc
    print(f"Не удалось воспроизвести: {path}")
    return None


def _guard(proc):
    """Пока звук играет, микрофон глухой (ЧайОК не слышит сам себя)."""
    if proc is None:
        return
    audio_guard.audio_playing.set()

    def _watch():
        try:
            proc.wait()
        except Exception:
            pass
        finally:
            audio_guard.audio_playing.clear()

    threading.Thread(target=_watch, daemon=True).start()


def play_sound(sound_file, volume=0.75, wait=False):
    global _current_process
    sound_path = sound_file
    if not os.path.isabs(sound_path):
        sound_path = os.path.join(SOUNDS_DIR, sound_file)
    if not os.path.exists(sound_path):
        print(f"Файл не найден: {sound_path}")
        return False

    level = max(0.0, min(1.0, float(volume) * volume_mod.load()))
    with _process_lock:
        _kill_process()
        _current_process = _spawn(sound_path, level)
        proc = _current_process
    if proc is None:
        return False
    _guard(proc)
    if wait:
        try:
            proc.wait()
        except Exception:
            pass
    return True


def _kill_process():
    global _current_process
    proc = _current_process
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass
    _current_process = None


def speak(text):
    """Озвучка фразы будильника (Piper, текст через stdin)."""
    global _current_process
    if not text or not os.path.exists(PIPER_PATH):
        return
    temp_file = None
    try:
        fd, temp_file = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        res = subprocess.run(
            [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", temp_file],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
        if res.returncode == 0:
            with _process_lock:
                _kill_process()
                _current_process = _spawn(temp_file, 0.9 * volume_mod.load())
                proc = _current_process
            if proc is not None:
                _guard(proc)
                try:
                    proc.wait(timeout=60)
                except Exception:
                    pass
            if proc is not None:
                try:
                    proc.wait(timeout=60)
                except Exception:
                    pass
    except Exception as e:
        print(f"Ошибка озвучки будильника: {e}")
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception:
                pass


def stop_alarm():
    global alarm_stop
    alarm_stop = True
    with _process_lock:
        _kill_process()
    alarm = load_alarm()
    save_alarm(alarm["hour"], alarm["minute"], alarm.get("level", "средний"),
               enabled=False, sound=alarm.get("sound"))
    print("Будильник остановлен")
    return "Будильник выключен"


# ========================================
# ЗВОНОК
# ========================================


def alarm_loop(level, ui_callback=None, sound=None):
    global alarm_stop
    alarm_stop = False

    config = LEVELS.get(level, LEVELS["средний"])
    sound = sound or config["sound"]
    volume = config["volume"]

    # будильник важнее музыки
    if radio_mod is not None:
        try:
            radio_mod.player.stop()
        except Exception:
            pass

    print(f"БУДИЛЬНИК: {config['label']}, звук {sound}")

    if ui_callback:
        ui_callback(level, config["label"])

    repeat_count = 0
    while not alarm_stop:
        repeat_count += 1
        print(f"Повтор {repeat_count}")

        if level == "жёсткий" and repeat_count >= 3:
            for _ in range(20):
                if alarm_stop:
                    break
                play_sound("melody4.mp3", volume=1.0)
                time.sleep(1)
            if not alarm_stop:
                speak("ВСТАВАЙ НЕМЕДЛЕННО!")
                play_sound("melody3.mp3", volume=1.0)
        else:
            speak(config["voice"])
            if alarm_stop:
                break
            play_sound(sound, volume=volume)

        for _ in range(REPEAT_INTERVAL):
            if alarm_stop:
                break
            time.sleep(1)

    print("Будильник остановлен")


# ========================================
# ПРОВЕРКА ВРЕМЕНИ
# ========================================


def alarm_checker(ui_callback=None):
    """Постоянный сторож: реагирует на включение будильника на ходу."""
    fired_key = None
    while True:
        alarm = load_alarm()
        if alarm.get("enabled"):
            now = datetime.now()
            key = (now.date(), alarm["hour"], alarm["minute"])
            if (now.hour == alarm["hour"] and now.minute == alarm["minute"]
                    and fired_key != key):
                fired_key = key
                threading.Thread(
                    target=alarm_loop,
                    args=(alarm.get("level", "средний"), ui_callback, alarm.get("sound")),
                    daemon=True,
                ).start()
        time.sleep(5)


# ========================================
# ГОЛОСОВЫЕ КОМАНДЫ
# ========================================


def process_alarm_command(command):
    command = command.lower().strip()

    if "будильник" not in command and command not in ("стоп", "хватит"):
        return None

    if any(word in command for word in ("выключи", "отключи", "убери")) or command in ("стоп", "хватит"):
        return stop_alarm()

    if "статус" in command or "когда" in command:
        alarm = load_alarm()
        if alarm["enabled"]:
            return (f"Будильник на {alarm['hour']:02d}:{alarm['minute']:02d}, "
                    f"уровень {alarm.get('level', 'средний')}, звук {alarm.get('sound')}")
        return "Будильник не установлен"

    numbers = re.findall(r"\d+", command)
    if not numbers:
        return "Скажи время, например: будильник на 7 30 мягкий"

    hour = int(numbers[0])
    minute = int(numbers[1]) if len(numbers) > 1 else 0

    # «без пяти семь», «половина седьмого» и т.п. не разбираем — только числа
    if "вечера" in command and hour < 12:
        hour += 12
    if hour < 12 and ("утра" in command) and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return "Некорректное время"

    level = "мягкий"
    for name in LEVELS:
        if name in command:
            level = name
            break

    sound = None
    match = re.search(r"мелоди\w*\s*(\d)", command)
    if match:
        candidate = f"melody{match.group(1)}.mp3"
        if os.path.exists(os.path.join(SOUNDS_DIR, candidate)):
            sound = candidate

    data = save_alarm(hour, minute, level, enabled=True, sound=sound)
    return f"Будильник на {data['hour']:02d}:{data['minute']:02d}, уровень {level}, звук {data['sound']}"
