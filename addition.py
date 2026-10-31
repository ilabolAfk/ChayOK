#!/usr/bin/env python3
"""
Модуль дополнительных функций: анекдоты и радио
"""

import os
import json
import random
import subprocess
import time

BASE_DIR = "/home/pi/ChayOK"
JOKES_FILE = os.path.join(BASE_DIR, "jokes.txt")
RADIO_FILE = os.path.join(BASE_DIR, "radio.json")

# Глобальная переменная для процесса радио
radio_process = None

# ========================================
# АНЕКДОТЫ
# ========================================

def get_joke():
    """Возвращает случайный анекдот из jokes.txt.
    Анекдот — блок строк, разделённый пустыми строками."""
    try:
        with open(JOKES_FILE, "r", encoding="utf-8") as f:
            blocks = []
            current = []
            for raw in f:
                line = raw.strip()
                if not line:
                    if current:
                        blocks.append("\n".join(current))
                        current = []
                else:
                    current.append(line)
            if current:
                blocks.append("\n".join(current))
        if not blocks:
            return "Файл с анекдотами пуст."
        return random.choice(blocks)
    except FileNotFoundError:
        return "Не могу найти файл с анекдотами."
    except Exception as e:
        return f"Ошибка чтения анекдотов: {e}"

# ========================================
# РАДИО
# ========================================

def play_radio(station_key):
    """Включает радио по названию или частоте."""
    global radio_process
    try:
        with open(RADIO_FILE, "r", encoding="utf-8") as f:
            stations = json.load(f)
        
        key = station_key.lower().strip()
        
        # Поиск по ключу
        if key not in stations:
            # Попробуем найти по частичному совпадению (например, "радио 7" вместо "104.7")
            found = None
            for name in stations.keys():
                if key in name or name in key:
                    found = name
                    break
            if found:
                key = found
            else:
                return f"Станция '{station_key}' не найдена. Попробуй 'Радио 7' или 'Монте-Карло'."
        
        # Останавливаем предыдущее радио
        if radio_process and radio_process.poll() is None:
            radio_process.terminate()
            time.sleep(0.5)
        
        url = stations[key]
        # Запускаем mpg123
        radio_process = subprocess.Popen(
            ["mpg123", "-q", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return f"Включаю {key}."
    except FileNotFoundError:
        return "Не могу найти файл radio.json."
    except Exception as e:
        return f"Ошибка радио: {e}"

def stop_radio():
    """Останавливает радио."""
    global radio_process
    if radio_process and radio_process.poll() is None:
        radio_process.terminate()
        radio_process = None
        return "Радио выключено."
    return "Радио не играет."

def list_stations():
    """Возвращает список доступных станций."""
    try:
        with open(RADIO_FILE, "r", encoding="utf-8") as f:
            stations = json.load(f)
        return list(stations.keys())
    except:
        return []

# ========================================
# ОБРАБОТКА КОМАНД
# ========================================

def process_addition_command(command):
    """
    Обрабатывает команды анекдотов и радио.
    Возвращает текст ответа или None, если команда не распознана.
    """
    command = command.lower().strip()

    # Анекдоты
    if "анекдот" in command or "шутк" in command:
        return get_joke()

    # Радио
    if "включи радио" in command or "радио" in command:
        # Вытаскиваем текст после "радио"
        text_after = command.split("радио", 1)[-1].strip()
        if not text_after:
            stations = list_stations()
            return f"Что включить? Доступные станции: {', '.join(stations)}"
        return play_radio(text_after)

    if "выключи радио" in command or "стоп радио" in command:
        return stop_radio()

    return None