#!/usr/bin/env python3
"""
Модуль будильника для ЧайОК
3 уровня: мягкий, средний, жёсткий
На 3-м повторе жёсткого уровня — громкое пиканье (как в CS)
"""

import os
import json
import time
import threading
import subprocess
from datetime import datetime

BASE_DIR = "/home/pi/ChayOK"
ALARM_FILE = os.path.join(BASE_DIR, "alarm.json")
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")

os.makedirs(SOUNDS_DIR, exist_ok=True)

LEVELS = {
    "мягкий": {
        "level": 1,
        "sound": "melody1.mp3",
        "voice": "Доброе утро! Пора вставать.",
        "label": "Мягкий"
    },
    "средний": {
        "level": 2,
        "sound": "melody2.mp3",
        "voice": "Подъём! Хватит спать!",
        "label": "Средний"
    },
    "жёсткий": {
        "level": 3,
        "sound": "melody3.mp3",
        "voice": "ПРОСНИСЬ! ВСТАВАЙ!",
        "label": "Жёсткий"
    }
}

alarm_stop = False

def load_alarm():
    try:
        with open(ALARM_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"enabled": False, "hour": 7, "minute": 0, "level": "средний"}

def save_alarm(hour, minute, level="средний", enabled=True):
    with open(ALARM_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled, "hour": hour, "minute": minute, "level": level}, f, indent=2)

def speak(text):
    try:
        cmd = f'echo "{text}" | /home/pi/piper/piper --model /home/pi/piper/ru_RU-denis-medium.onnx --output_file /tmp/alarm_voice.wav'
        subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
        subprocess.run('aplay /tmp/alarm_voice.wav 2>/dev/null', shell=True)
    except:
        pass

def play_sound(sound_file, volume=100, wait=False):
    sound_path = os.path.join(SOUNDS_DIR, sound_file)
    if os.path.exists(sound_path):
        cmd = f'mpg321 -g {volume} {sound_path} 2>/dev/null'
        if not wait:
            cmd += ' &'
        subprocess.run(cmd, shell=True)
        return True
    else:
        print(f"Файл не найден: {sound_path}")
        return False

def stop_alarm():
    global alarm_stop
    alarm_stop = True
    subprocess.run("pkill mpg321 2>/dev/null", shell=True)
    alarm = load_alarm()
    save_alarm(alarm["hour"], alarm["minute"], alarm.get("level", "средний"), enabled=False)
    print("Будильник остановлен")

def alarm_loop(level, ui_callback=None):
    global alarm_stop
    alarm_stop = False
    
    config = LEVELS.get(level, LEVELS["средний"])
    print(f"БУДИЛЬНИК: {config['label']}")
    
    if ui_callback:
        ui_callback(level, config["label"])
    
    repeat_count = 0
    
    while not alarm_stop:
        repeat_count += 1
        print(f"Повтор {repeat_count}")
        
        # ЖЁСТКИЙ УРОВЕНЬ: на 3-й повтор — громкое пиканье
        if level == "жёсткий" and repeat_count >= 3:
            for i in range(20):
                if alarm_stop:
                    break
                play_sound("melody4.mp3", volume=100, wait=False)
                time.sleep(1)
            
            if not alarm_stop:
                speak("ВСТАВАЙ НЕМЕДЛЕННО!")
                play_sound("melody3.mp3", volume=100, wait=False)
        else:
            speak(config["voice"])
            play_sound(config["sound"], volume=100 if level == "жёсткий" else 70, wait=False)
        
        if alarm_stop:
            break
        
        # Ждём 5 минут (300 секунд) до следующего повтора
        for i in range(300):
            if alarm_stop:
                break
            time.sleep(1)
    
    print("Будильник остановлен")

def alarm_checker(ui_callback=None):
    alarm = load_alarm()
    if not alarm["enabled"]:
        return
    
    target_hour = alarm["hour"]
    target_minute = alarm["minute"]
    level = alarm.get("level", "средний")
    triggered = False
    
    while True:
        now = datetime.now()
        if not triggered and now.hour == target_hour and now.minute == target_minute:
            triggered = True
            threading.Thread(target=alarm_loop, args=(level, ui_callback), daemon=True).start()
            break
        time.sleep(5)

def process_alarm_command(command):
    command = command.lower().strip()
    
    level_names = {
        "мягкий": "мягкий",
        "средний": "средний",
        "жёсткий": "жёсткий",
        "сирена": "жёсткий",
        "пиканье": "жёсткий",
        "бомба": "жёсткий"
    }
    
    if "будильник" in command:
        import re
        numbers = re.findall(r'\d+', command)
        if numbers:
            hour = int(numbers[0])
            minute = 0
            if len(numbers) > 1:
                minute = int(numbers[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                level = "средний"
                for name, value in level_names.items():
                    if name in command:
                        level = value
                        break
                save_alarm(hour, minute, level, enabled=True)
                return f"Будильник на {hour:02d}:{minute:02d}, уровень: {level}"
            else:
                return "Некорректное время"
        else:
            return "Скажи время, например: будильник на 7 утра жёсткий"
    
    if "выключи будильник" in command or "отключи будильник" in command or "стоп" in command:
        stop_alarm()
        return "Будильник отключён"
    
    if "статус будильника" in command:
        alarm = load_alarm()
        if alarm["enabled"]:
            return f"Будильник на {alarm['hour']:02d}:{alarm['minute']:02d}, уровень: {alarm.get('level', 'средний')}"
        else:
            return "Будильник не установлен"
    
    return None
