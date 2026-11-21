#!/usr/bin/env python3
"""
ЧайОК — версия 2 (Pi 4, Bonsai 1.7B через llama.cpp)
Потоковая генерация, озвучка по предложениям, анекдоты и радио
"""

import datetime
import json
import math
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from array import array

import pygame
import requests
import vosk

try:
    import tkinter as tk
    from tkinter import scrolledtext
    HAS_TK = True
except ImportError:
    HAS_TK = False

try:
    import smbus2
    HAS_SMBUS = True
except ImportError:
    HAS_SMBUS = False

import alarm
import addition
import audio_guard
import notifier
import radio as radio_mod
import timer as timer_mod
import volume
import watchdog

# ========================================
# НАСТРОЙКИ
# ========================================

WAKE_WORDS = ["чайок", "чаек", "чаёк", "чай ок"]
COMMAND_SILENCE = 2.5
HISTORY_LIMIT = 4        # сколько последних реплик держать в контексте
FOLLOWUP_SECONDS = 5     # окно продолжения без слова-активатора

BASE_DIR = "/home/pi"
PROJECT_DIR = os.path.join(BASE_DIR, "ChayOK")
SOUNDS_DIR = os.path.join(PROJECT_DIR, "sounds")

VOSK_MODEL_PATH = os.path.join(PROJECT_DIR, "vosk-model")
PIPER_PATH = os.path.join(BASE_DIR, "piper/piper")
PIPER_MODEL = os.path.join(BASE_DIR, "piper/ru_RU-ruslan-medium.onnx")

# --- LLM: сначала локальный Bonsai (llama.cpp), потом сервер на ПК ---
LLM_PROVIDERS = [
    {
        "kind": "completion",
        "url": "http://127.0.0.1:8080/completion",
        "name": "Bonsai (Pi, llama.cpp)",
        "max_tokens": 160,
    },
    {
        "kind": "ollama",
        "url": "http://192.168.1.108:11434/api/chat",
        "model": "qwen2.5:7b-instruct",
        "name": "Сервер (ПК)",
        "max_tokens": 220,
    },
]
LLM_TIMEOUT = (5, 180)
LLM_SYSTEM_PROMPT = (
    "Ты — ЧайОК, голосовой помощник в маленьком устройстве. "
    "Отвечай по-русски, кратко: одно-два предложения, без списков и разметки. "
    "Никогда не пиши даты в формате ГГГГ-ММ-ДД — называй дату словами."
)

CITY = "Москва"

AUDIO_RATE = 16000        # Vosk обучен на 16 кГц
AUDIO_CHANNELS = 1
AUDIO_CHUNK = 4000        # ~125 мс при 16 кГц / 16 бит

MIC_DEVICE = os.environ.get("CHAYOK_MIC", "")   # пусто = определить автоматически
SPK_DEVICE = os.environ.get("CHAYOK_SPK", "")   # пусто = определить автоматически

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480

alarm_pending = None
is_generating = False
audio_lock = threading.Lock()
dialogue_history = []      # последние реплики для контекста
followup_until = 0.0       # до этого времени слушаем без слова-активатора
pending_followup = False   # открыть окно, как только закончим говорить

# PipeWire в пользовательской сессии — без этого pw-play не находит сокет
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = "/run/user/%d" % os.getuid()

# ========================================
# ЦВЕТА
# ========================================

COLORS = {
    "bg": (10, 12, 20),
    "primary": (0, 180, 255),
    "secondary": (0, 220, 180),
    "accent": (255, 200, 50),
    "salad": (120, 255, 120),
    "text": (200, 210, 230),
    "text_dim": (100, 120, 150),
    "card_bg": (20, 30, 45),
    "border": (0, 150, 200),
    "error": (255, 100, 100),
    "button": (0, 120, 200),
    "button_hover": (0, 150, 240),
}

# ========================================
# ЭКРАН
# ========================================

os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
# звук выводят pw-play/aplay, микшер pygame не нужен — иначе он засоряет лог underrun'ами
os.environ["SDL_AUDIODRIVER"] = "dummy"
pygame.init()
pygame.mixer.quit()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
pygame.display.set_caption("ChayOK")

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype",
]


def load_font(size, bold=False):
    names = (
        ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf"]
        if bold
        else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf"]
    )
    for directory in FONT_DIRS:
        for name in names:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                try:
                    return pygame.font.Font(path, size)
                except Exception:
                    pass
    return pygame.font.Font(None, size)


font_title = load_font(52, bold=True)
font_status = load_font(32)
font_clock = load_font(40, bold=True)
font_text = load_font(24)
font_small = load_font(18)
font_tiny = load_font(14)
font_button = load_font(16)

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]

_alarm_cache = {"ts": 0.0, "data": None}


def cached_alarm():
    """Настройки будильника с кэшем на 2 с — чтобы не читать файл каждый кадр."""
    now = time.time()
    if _alarm_cache["data"] is None or now - _alarm_cache["ts"] > 2:
        _alarm_cache["data"] = alarm.load_alarm()
        _alarm_cache["ts"] = now
    return _alarm_cache["data"]

# ========================================
# ВСПОМОГАТЕЛЬНЫЕ
# ========================================


def draw_rounded_rect(surface, color, rect, radius=6, border_width=0, border_color=None):
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return
    radius = max(0, min(radius, w // 2, h // 2))
    pygame.draw.rect(surface, color, (x + radius, y, w - radius * 2, h))
    pygame.draw.rect(surface, color, (x, y + radius, w, h - radius * 2))
    for cx, cy in [
        (x + radius, y + radius),
        (x + w - radius, y + radius),
        (x + radius, y + h - radius),
        (x + w - radius, y + h - radius),
    ]:
        pygame.draw.circle(surface, color, (cx, cy), radius)
    if border_width > 0 and border_color:
        pygame.draw.rect(surface, border_color, (x, y, w, h), border_width, border_radius=radius)


def draw_glow_line(surface, color, start, end, width=2):
    pygame.draw.line(surface, (color[0] // 2, color[1] // 2, color[2] // 2), start, end, width + 4)
    pygame.draw.line(surface, color, start, end, width)


# ========================================
# ИКОНКИ ПОГОДЫ (векторно, без картинок)
# ========================================

ICON_SUN = (255, 205, 60)
ICON_CLOUD = (232, 238, 248)
ICON_CLOUD_DARK = (198, 210, 228)
ICON_RAIN = (120, 195, 255)
ICON_SNOW = (225, 245, 255)
ICON_BOLT = (255, 210, 70)


def draw_radio_waves(surface, rect, phase, energy=None):
    """Три бегущие синусоиды — волны вместо столбиков."""
    energy = volume.load() if energy is None else energy
    layers = (
        (COLORS["primary"], 0.55, 1.0),
        (COLORS["secondary"], 0.38, 1.6),
        (COLORS["accent"], 0.26, 2.4),
    )
    for color, amplitude_ratio, speed in layers:
        amplitude = rect.height * amplitude_ratio * (0.75 + 0.25 * energy)
        points = []
        for x in range(rect.left, rect.right + 1, 6):
            t = (x - rect.left) / max(1, rect.width)
            y = rect.centery + math.sin(t * 6.28318 * 1.5 + phase * speed) * amplitude
            points.append((x, y))
        pygame.draw.lines(surface, color, False, points, 2)


HOLIDAY_COLORS = ((255, 92, 92), (255, 200, 80), (120, 255, 160),
                  (110, 190, 255), (225, 140, 255))


def holiday_mode(now=None):
    """Гирлянда с 1 декабря по 5 января. CHAYOK_HOLIDAY=1 включает принудительно."""
    if os.environ.get("CHAYOK_HOLIDAY") == "1":
        return True
    now = now or datetime.datetime.now()
    return now.month == 12 or (now.month == 1 and now.day <= 5)


def draw_garland(surface, seconds):
    spacing = 26
    for edge_y in (5, SCREEN_HEIGHT - 6):
        for index, x in enumerate(range(14, SCREEN_WIDTH - 8, spacing)):
            color = HOLIDAY_COLORS[index % len(HOLIDAY_COLORS)]
            twinkle = 0.5 + 0.5 * math.sin(seconds * 2.4 + index * 0.9)
            intensity = 0.55 + 0.45 * twinkle
            radius = 2 + int(2.5 * intensity)
            pygame.draw.circle(surface, tuple(int(c * intensity) for c in color),
                               (x, edge_y), radius)
            pygame.draw.circle(surface, (255, 255, 255), (x, edge_y), max(1, radius // 2))


def weather_icon_kind(code):
    code = int(code)
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunder"
    return "cloud"


def _icon_sun(surface, center, radius):
    pygame.draw.circle(surface, ICON_SUN, center, radius)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        start = (center[0] + math.cos(rad) * (radius + 4), center[1] + math.sin(rad) * (radius + 4))
        end = (center[0] + math.cos(rad) * (radius + 9), center[1] + math.sin(rad) * (radius + 9))
        pygame.draw.line(surface, ICON_SUN, start, end, 2)


def _icon_cloud(surface, x, y, width, color=ICON_CLOUD):
    pygame.draw.circle(surface, color, (int(x + width * 0.30), int(y + width * 0.34)), int(width * 0.21))
    pygame.draw.circle(surface, color, (int(x + width * 0.54), int(y + width * 0.25)), int(width * 0.26))
    pygame.draw.circle(surface, color, (int(x + width * 0.76), int(y + width * 0.37)), int(width * 0.18))
    pygame.draw.rect(surface, color,
                     (int(x + width * 0.16), int(y + width * 0.35),
                      int(width * 0.68), int(width * 0.26)),
                     border_radius=int(width * 0.12))


def draw_weather_icon(surface, kind, rect):
    x, y, w, h = rect
    if kind == "sun":
        _icon_sun(surface, (x + w // 2, y + h // 2), max(4, int(w * 0.20)))
    elif kind == "partly":
        _icon_sun(surface, (x + int(w * 0.30), y + int(h * 0.28)), max(3, int(w * 0.12)))
        _icon_cloud(surface, x + int(w * 0.18), y + int(h * 0.34), int(w * 0.78))
    elif kind == "fog":
        for index, dy in enumerate((0.30, 0.48, 0.66)):
            width = int(w * (0.80 if index != 1 else 0.62))
            pygame.draw.rect(surface, ICON_CLOUD, (x + 2, y + int(h * dy), width, 5), border_radius=3)
    elif kind == "rain":
        _icon_cloud(surface, x, y, w)
        for index in range(3):
            sx = x + int(w * (0.36 + index * 0.14))
            pygame.draw.line(surface, ICON_RAIN, (sx, y + int(h * 0.70)),
                             (sx - 4, y + int(h * 0.90)), 3)
    elif kind == "snow":
        _icon_cloud(surface, x, y, w)
        for index in range(3):
            cx = x + int(w * (0.34 + index * 0.16))
            cy = y + int(h * 0.82)
            for angle in (0, 60, 120):
                rad = math.radians(angle)
                dx, dy = math.cos(rad) * 5, math.sin(rad) * 5
                pygame.draw.line(surface, ICON_SNOW, (cx - dx, cy - dy), (cx + dx, cy + dy), 2)
    elif kind == "thunder":
        _icon_cloud(surface, x, y, int(w * 0.9), ICON_CLOUD_DARK)
        bolt = [
            (x + int(w * 0.52), y + int(h * 0.52)),
            (x + int(w * 0.38), y + int(h * 0.80)),
            (x + int(w * 0.49), y + int(h * 0.80)),
            (x + int(w * 0.42), y + int(h * 0.99)),
            (x + int(w * 0.64), y + int(h * 0.68)),
            (x + int(w * 0.52), y + int(h * 0.68)),
        ]
        pygame.draw.polygon(surface, ICON_BOLT, bolt)
    else:
        _icon_cloud(surface, x, y, w)


def commands_path():
    return os.path.join(PROJECT_DIR, "custom_commands.json")


def load_custom_commands():
    try:
        with open(commands_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("commands", [])
    except Exception:
        return []


def save_custom_commands(commands):
    with open(commands_path(), "w", encoding="utf-8") as f:
        json.dump({"commands": commands}, f, ensure_ascii=False, indent=2)


def run_custom_command(command_text):
    """Выполняет первую совпавшую пользовательскую команду."""
    for cmd in custom_commands:
        if cmd.lower() in command_text:
            try:
                subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return cmd
            except Exception as e:
                print("Ошибка запуска команды:", e)
                return None
    return None


# ========================================
# ЗАРЯД БАТАРЕИ (шина I2C открывается один раз)
# ========================================

_battery_bus = None
_battery_failed = False


def get_battery_level():
    global _battery_bus, _battery_failed
    if not HAS_SMBUS or _battery_failed:
        return None
    try:
        if _battery_bus is None:
            _battery_bus = smbus2.SMBus(1)
        raw = _battery_bus.read_word_data(0x42, 0x02)
        voltage_raw = ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)
        voltage_mv = (voltage_raw >> 3) * 4
        if voltage_mv > 8400:
            return 100
        if voltage_mv < 6000:
            return 0
        return max(0, min(100, int((voltage_mv - 6000) / (8400 - 6000) * 100)))
    except Exception:
        # при ошибке один раз закрываем шину и больше не дёргаем железо
        _battery_failed = True
        if _battery_bus is not None:
            try:
                _battery_bus.close()
            except Exception:
                pass
            _battery_bus = None
        return None


# ========================================
# РЕДАКТОРЫ
# ========================================


def open_script_editor():
    if not HAS_TK:
        print("tkinter не установлен")
        return

    def save_script():
        commands = [line.strip() for line in text_area.get("1.0", tk.END).strip().split("\n") if line.strip()]
        save_custom_commands(commands)
        status_label.config(text="Сохранено!")
        root.after(1500, lambda: status_label.config(text=""))
        global custom_commands
        custom_commands = load_custom_commands()

    root = tk.Tk()
    root.title("Редактор скриптов ЧайОК")
    root.geometry("600x400")
    tk.Label(root, text="Введи команды (по одной на строку):", font=("DejaVu Sans", 12)).pack(pady=5)
    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("DejaVu Sans Mono", 12))
    text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    commands = load_custom_commands()
    text_area.insert("1.0", "\n".join(commands) if commands else "включи свет\nвыключи свет")
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=5)
    tk.Button(btn_frame, text="Сохранить", command=save_script, bg="lightgreen",
              font=("DejaVu Sans", 10)).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Закрыть", command=root.destroy, bg="lightcoral",
              font=("DejaVu Sans", 10)).pack(side=tk.LEFT, padx=5)
    status_label = tk.Label(root, text="", font=("DejaVu Sans", 10))
    status_label.pack()
    root.mainloop()


def open_alarm_editor():
    if not HAS_TK:
        print("tkinter не установлен")
        return

    def save_alarm_settings():
        try:
            hour, minute = int(hour_var.get()), int(minute_var.get())
            level = level_var.get()
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                status_label.config(text="Некорректное время!")
                return
            alarm.save_alarm(hour, minute, level, enabled=True)
            status_label.config(text=f"Будильник: {hour:02d}:{minute:02d}, {level}")
            root.after(2000, lambda: status_label.config(text=""))
        except ValueError:
            status_label.config(text="Введи числа!")

    def disable_alarm():
        a = alarm.load_alarm()
        alarm.save_alarm(a["hour"], a["minute"], a.get("level", "средний"), enabled=False)
        status_label.config(text="Будильник отключён")

    root = tk.Tk()
    root.title("Будильник ЧайОК")
    root.geometry("400x320")
    current = alarm.load_alarm()
    tk.Label(root, text="Настройка будильника", font=("DejaVu Sans", 14, "bold")).pack(pady=10)
    time_frame = tk.Frame(root)
    time_frame.pack(pady=5)
    tk.Label(time_frame, text="Часы:").pack(side=tk.LEFT, padx=5)
    hour_var = tk.StringVar(value=str(current.get("hour", 7)))
    tk.Entry(time_frame, textvariable=hour_var, width=5).pack(side=tk.LEFT)
    tk.Label(time_frame, text="Минуты:").pack(side=tk.LEFT, padx=5)
    minute_var = tk.StringVar(value=str(current.get("minute", 0)))
    tk.Entry(time_frame, textvariable=minute_var, width=5).pack(side=tk.LEFT)
    level_frame = tk.Frame(root)
    level_frame.pack(pady=15)
    tk.Label(level_frame, text="Уровень жёсткости:", font=("DejaVu Sans", 12)).pack()
    level_var = tk.StringVar(value=current.get("level", "средний"))
    for lvl in ["мягкий", "средний", "жёсткий"]:
        tk.Radiobutton(level_frame, text=lvl.capitalize(), variable=level_var,
                       value=lvl, font=("DejaVu Sans", 11)).pack(anchor="w", padx=20)
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=15)
    tk.Button(btn_frame, text="Сохранить", command=save_alarm_settings, bg="lightgreen",
              font=("DejaVu Sans", 11), width=12).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Отключить", command=disable_alarm, bg="lightyellow",
              font=("DejaVu Sans", 11), width=12).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Закрыть", command=root.destroy, bg="lightcoral",
              font=("DejaVu Sans", 11), width=12).pack(side=tk.LEFT, padx=5)
    status_label = tk.Label(root, text="", font=("DejaVu Sans", 10))
    status_label.pack()
    root.mainloop()


# ========================================
# ПОГОДА
# ========================================


WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
CITY_COORDS = {"latitude": 55.7558, "longitude": 37.6173}

# коды WMO → по-русски
WMO_RU = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "слабая морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
    80: "небольшие ливни", 81: "ливни", 82: "сильные ливни",
    85: "небольшие снежные ливни", 86: "сильные снежные ливни",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}

MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def weather_desc(code):
    return WMO_RU.get(int(code), "без осадков")


def _weather_request(daily=None, days=1):
    """Open-Meteo: ключ не нужен, HTTPS. OpenWeather из РФ висит на TLS."""
    params = dict(CITY_COORDS, timezone="Europe/Moscow", forecast_days=days)
    params["current"] = ("temperature_2m,apparent_temperature,"
                         "relative_humidity_2m,wind_speed_10m,weather_code")
    if daily:
        params["daily"] = daily
    response = requests.get(WEATHER_URL, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def get_weather_now():
    try:
        current = _weather_request()["current"]
        temperature = round(current["temperature_2m"])
        feels = round(current["apparent_temperature"])
        wind = round(current["wind_speed_10m"] / 3.6, 1)  # км/ч → м/с
        return {
            "_code": current["weather_code"],
            "Температура": f"{temperature} {_plural(temperature, 'градус', 'градуса', 'градусов')}",
            "Ощущается": f"{feels} {_plural(feels, 'градус', 'градуса', 'градусов')}",
            "Погода": weather_desc(current["weather_code"]),
            "Влажность": f"{current['relative_humidity_2m']}%",
            "Ветер": f"{wind} м/с",
        }
    except Exception as e:
        return {"Ошибка": str(e)}


def get_weather_forecast(days=7):
    try:
        daily = _weather_request(daily="weather_code,temperature_2m_max", days=days)["daily"]
        result = {}
        for index, iso in enumerate(daily["time"][:days]):
            dt = datetime.datetime.strptime(iso, "%Y-%m-%d")
            date_ru = f"{dt.day} {MONTHS_RU[dt.month - 1]}"
            temperature = round(daily["temperature_2m_max"][index])
            result[date_ru] = (f"днём {temperature} "
                               f"{_plural(temperature, 'градус', 'градуса', 'градусов')}, "
                               f"{weather_desc(daily['weather_code'][index])}")
        return result
    except Exception as e:
        return {"Ошибка": str(e)}


# ========================================
# ЗВУК: определение устройств и воспроизведение
# ========================================

_mic_device = None
_spk_device = None


def _parse_alsa(pflag):
    try:
        out = subprocess.run(["aplay" if pflag == "p" else "arecord", "-l"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    return re.findall(r"card (\d+):\s*([^\[]+)\[([^\]]*)\]", out)


def get_mic_device():
    """Первый USB-захват (USB PnP Sound Device), иначе plughw:0,0."""
    global _mic_device
    if _mic_device:
        return _mic_device
    if MIC_DEVICE:
        _mic_device = MIC_DEVICE
        return _mic_device
    for card, name, _ in _parse_alsa("c"):
        if "usb" in name.lower() or "pnp" in name.lower():
            _mic_device = f"plughw:{card},0"
            return _mic_device
    cards = _parse_alsa("c")
    _mic_device = f"plughw:{cards[0][0]},0" if cards else "plughw:0,0"
    return _mic_device


def get_spk_device():
    """Карта вывода: предпочитаем USB-колонку, а не встроенные наушники."""
    global _spk_device
    if _spk_device:
        return _spk_device
    if SPK_DEVICE:
        _spk_device = SPK_DEVICE
        return _spk_device
    cards = _parse_alsa("p")
    for card, name, _ in cards:
        if "usb" in name.lower() or "uac" in name.lower():
            _spk_device = f"plughw:{card},0"
            return _spk_device
    _spk_device = f"plughw:{cards[0][0]},0" if cards else "plughw:0,0"
    return _spk_device


_play_via_pw = None


def play_wav(path, level=None):
    """Играет wav через PipeWire, при неудаче — через ALSA.

    На всё время звука поднимается audio_guard.audio_playing: микрофон в это
    время не кормит распознавание, поэтому ЧайОК не слышит сам себя.
    """
    global _play_via_pw
    level = volume.load() if level is None else max(0.0, min(1.0, level))
    audio_guard.audio_playing.set()
    try:
        with audio_lock:
            if _play_via_pw is not False:
                try:
                    res = subprocess.run(["pw-play", f"--volume={level:.2f}", path],
                                         capture_output=True, timeout=180)
                    if res.returncode == 0:
                        _play_via_pw = True
                        return
                except Exception:
                    pass
                _play_via_pw = False
            try:
                subprocess.run(["aplay", "-q", "-D", get_spk_device(), path],
                               capture_output=True, timeout=180)
            except Exception as e:
                print("Ошибка воспроизведения:", e)
    finally:
        audio_guard.audio_playing.clear()


# ========================================
# ОЗВУЧКА
# ========================================

_speech_queue = queue.Queue()


def _speech_worker():
    while True:
        text = _speech_queue.get()
        try:
            if text is None:
                return
            speak_piper_sync(text)
        finally:
            _speech_queue.task_done()


def speak_piper(text):
    """Ставит фразу в очередь — фразы не перемешиваются."""
    if not text:
        return
    _speech_queue.put(text)


def speech_text(text):
    """Готовит текст для Piper: символы, на которых он запинается."""

    def percent_to_words(match):
        value = int(match.group(1))
        return f"{value} {_plural(value, 'процент', 'процента', 'процентов')}"

    text = text.replace("м/с", "метров в секунду")
    text = text.replace("км/ч", "километров в час")
    text = re.sub(r"(\d+)\s*%", percent_to_words, text)
    text = text.replace("°C", " градусов").replace("°", " градусов")
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1,\2", text)        # 3.8 → 3,8
    text = re.sub(r"(?<![\w-])-\s*(\d)", r"минус \1", text)   # -4 → минус 4
    text = re.sub(r"(?<![\w-])\+\s*(\d)", r"плюс \1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def speak_piper_sync(text):
    text = speech_text(text)
    if not text or not os.path.exists(PIPER_PATH):
        return
    temp_file = None
    try:
        fd, temp_file = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        # текст уходит в stdin, а не в shell — кавычки и $() безопасны
        res = subprocess.run(
            [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", temp_file],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        if res.returncode != 0:
            print("piper:", res.stderr.decode("utf-8", "replace")[:300])
            return
        # пока говорим — радио тише
        if radio_mod.player.active():
            radio_mod.player.duck()
        play_wav(temp_file)
    except Exception as e:
        print(f"Ошибка озвучки: {e}")
    finally:
        if radio_mod.player.active():
            radio_mod.player.restore()
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception:
                pass


threading.Thread(target=_speech_worker, daemon=True).start()

# ========================================
# LLM (потоковая генерация)
# ========================================


def _iter_tokens(response, kind):
    """Отдаёт текстовые куски из SSE (llama.cpp) или NDJSON (ollama)."""
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "error" in chunk:
            raise RuntimeError(str(chunk["error"])[:200])
        if kind == "completion":
            piece = chunk.get("content") or ""
        elif kind == "openai":
            choices = chunk.get("choices") or []
            piece = ""
            if choices:
                piece = (choices[0].get("delta") or {}).get("content") or ""
        else:
            piece = (chunk.get("message") or {}).get("content") or ""
        if piece:
            yield piece


def _strip_think(pieces):
    """Убирает <think>…</think> и служебные токены из потока."""
    buf = ""
    inside = False
    for piece in pieces:
        buf += piece
        while True:
            if inside:
                idx = buf.find("</think>")
                if idx == -1:
                    buf = buf[-8:]
                    break
                buf = buf[idx + 8:]
                inside = False
                continue
            idx = buf.find("<think>")
            if idx == -1:
                keep = 8
                if len(buf) > keep:
                    safe = buf[:-keep]
                    for token in ("<|im_end|>", "<|im_start|>", "</think>"):
                        safe = safe.replace(token, "")
                    if safe:
                        yield safe
                    buf = buf[-keep:]
                break
            if idx > 0:
                yield buf[:idx]
            buf = buf[idx + 7:]
            inside = True
    if buf and not inside:
        for token in ("<|im_end|>", "<|im_start|>", "<think>", "</think>"):
            buf = buf.replace(token, "")
        if buf:
            yield buf


def _chatml(messages):
    """ChatML-промпт из истории: Bonsai обучена на этом формате.

    Пустой закрытый <think> в конце отключает «рассуждения» и экономит время.
    """
    parts = []
    for message in messages:
        parts.append(f"<|im_start|>{message['role']}\n{message['content']}<|im_end|>\n")
    parts.append("<|im_start|>assistant\n<think>\n</think>\n")
    return "".join(parts)


def _build_payload(provider, messages):
    kind = provider["kind"]
    max_tokens = provider.get("max_tokens", 200)
    if kind == "completion":
        return {
            "prompt": _chatml(messages),
            "n_predict": max_tokens,
            "temperature": 0.3,
            "top_p": 0.9,
            "repeat_penalty": 1.15,
            # "\n\n" в стопах обрывал ответ на первом пустом переводе строки
            "stop": ["<|im_end|>", "<|im_start|>"],
            "stream": True,
        }
    if kind == "ollama":
        return {
            "model": provider["model"],
            "messages": messages,
            "stream": True,
            "options": {"num_predict": max_tokens, "temperature": 0.5},
        }
    return {
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }


def ask_llm_streaming(command, ui_ref):
    global is_generating, pending_followup
    is_generating = True
    ui_ref.status = "Generating..."
    dialogue_history.append({"role": "user", "content": command})
    messages = ([{"role": "system", "content": LLM_SYSTEM_PROMPT}]
                + dialogue_history[-HISTORY_LIMIT * 2:])
    ui_ref.response = ""
    full_text = ""
    sentence_buffer = ""
    try:
        for provider in LLM_PROVIDERS:
            kind = provider["kind"]
            payload = _build_payload(provider, messages)
            try:
                r = requests.post(provider["url"], json=payload, stream=True, timeout=LLM_TIMEOUT)
            except Exception as e:
                print(f"[LLM] {provider['name']} недоступен: {e}")
                continue
            if r.status_code != 200:
                print(f"[LLM] {provider['name']}: HTTP {r.status_code}")
                r.close()
                continue

            print(f"[LLM] {provider['name']}")
            try:
                for piece in _strip_think(_iter_tokens(r, kind)):
                    full_text += piece
                    sentence_buffer += piece
                    ui_ref.response = full_text.strip()
                    # озвучиваем только законченное предложение: ждём точку,
                    # вопрос или восклицание, после которых пробел или конец
                    while True:
                        match = re.search(r"[^.!?…]*[.!?…](?=\s|$)", sentence_buffer)
                        if not match or len(match.group(0).strip()) < 5:
                            break
                        speak_piper(match.group(0).strip())
                        sentence_buffer = sentence_buffer[match.end():].lstrip()
            finally:
                r.close()

            if full_text.strip():
                break
            print(f"[LLM] {provider['name']}: пустой ответ")

        if sentence_buffer.strip():
            speak_piper(sentence_buffer.strip())
        answer = full_text.strip()
        if answer:
            dialogue_history.append({"role": "assistant", "content": answer})
            del dialogue_history[:-HISTORY_LIMIT * 2]
        else:
            ui_ref.response = "Ошибка: нейросеть недоступна."
            speak_piper("Извините, нейросеть недоступна.")
            dialogue_history.pop()
    except Exception as e:
        print("[LLM] ошибка:", e)
        ui_ref.response = full_text.strip() or "Ошибка: нейросеть недоступна."
        if dialogue_history and dialogue_history[-1]["role"] == "user":
            dialogue_history.pop()
    finally:
        ui_ref.status = "Ready"
        is_generating = False
        pending_followup = True


# ========================================
# КОМАНДЫ
# ========================================

custom_commands = load_custom_commands()

RADIO_STOPWORDS = {"радио", "fm", "фм"}


def _norm_ru(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^а-яa-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_station_index(command, stations):
    """Станция по фразе-алиасу, затем по основе слова.

    Приоритет: точная фраза («ретро хит») важнее отдельного слова («ретро»),
    при равенстве выигрывает станция, стоящая выше в списке.
    Основа слова нужна для падежей: «дискотеку» → «дискотека».
    """
    normalized_cmd = _norm_ru(command)
    cmd = f" {normalized_cmd} "
    words = normalized_cmd.split()
    best = None

    for index, station in enumerate(stations):
        keys = [station["name"]] + list(station.get("aliases", []))
        for key in keys:
            normalized = _norm_ru(key)
            if not normalized:
                continue
            candidate = None
            if " " in normalized and f" {normalized} " in cmd:
                candidate = (2, len(normalized), -index)
            else:
                for word in normalized.split():
                    if word in RADIO_STOPWORDS:
                        continue
                    if word.isdigit():
                        if word in words:
                            candidate = (1, len(word), -index)
                            break
                        continue
                    if len(word) < 3:
                        continue
                    stem = word[:5]
                    if any(w.startswith(stem) for w in words):
                        candidate = (1, len(word), -index)
                        break
            if candidate and (best is None or candidate > best):
                best = candidate

    return -best[2] if best else None


def _set_volume(value):
    value = max(0.0, min(1.0, value))
    volume.save(value)
    if radio_mod.player.active():
        radio_mod.player.set_volume(value)
    return volume.describe()


def handle_volume_command(command):
    if any(phrase in command for phrase in ("выключи звук", "без звука", "тишина")):
        return _set_volume(0.0)
    if "на всю" in command or "максимальн" in command:
        return _set_volume(1.0)
    if "тише" in command or "потише" in command:
        return _set_volume(volume.load() - 0.1)
    if "громче" in command or "погромче" in command:
        return _set_volume(volume.load() + 0.1)
    if "громкость" in command or "звук" in command:
        numbers = re.findall(r"\d+", command)
        if numbers:
            return _set_volume(int(numbers[0]) / 100.0)
        return volume.describe()
    return None


def handle_radio_command(command):
    player = radio_mod.player

    if any(word in command for word in ("выключи", "отключи", "стоп", "хватит")):
        if player.active():
            return player.stop()
        return None

    if "радио" not in command and "станц" not in command:
        return None

    if "следующ" in command or "переключ" in command:
        name = player.next_station()
        return f"Станция: {name}" if name else "Не удалось переключить"

    index = find_station_index(command, player.stations)
    if index is not None:
        name = player.start(index)
        return f"Включаю {name}" if name else "Не удалось включить радио"

    if player.active():
        return f"Уже играет {player.station_name()}"
    name = player.start()
    return f"Включаю {name}" if name else "Не удалось включить радио"


def _plural(value, one, few, many):
    n = abs(int(value)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def handle_timer_command(command):
    if "таймер" not in command and "напомни" not in command and "напоминание" not in command:
        return None

    if any(word in command for word in ("выключи", "отмени", "стоп", "хватит", "убери")):
        return timer_mod.stop()

    if "сколько" in command or "осталось" in command:
        return timer_mod.describe() or "Таймер не запущен"

    numbers = re.findall(r"\d+", command)
    if not numbers:
        return "Скажи, на сколько: например, таймер на 5 минут"

    value = int(numbers[0])
    if "час" in command:
        unit, word = 3600, _plural(value, "час", "часа", "часов")
    elif "секунд" in command:
        unit, word = 1, _plural(value, "секунду", "секунды", "секунд")
    else:
        unit, word = 60, _plural(value, "минуту", "минуты", "минут")

    seconds = value * unit
    if seconds <= 0 or seconds > 24 * 3600:
        return "Такой таймер не поставлю"

    timer_mod.start(seconds, command)
    return f"Таймер на {value} {word}"


def process_command(command):
    command = command.lower().strip()

    if any(phrase in command for phrase in
           ("забудь всё", "забудь все", "очисти контекст", "новый разговор", "начнём заново")):
        dialogue_history.clear()
        return "Контекст очищен", None

    if timer_mod.is_ringing() and command in ("стоп", "хватит", "замолчи", "выключи"):
        return timer_mod.stop(), None

    timer_response = handle_timer_command(command)
    if timer_response:
        return timer_response, None

    if radio_mod.player.active() and command in ("стоп", "хватит", "замолчи", "выключи"):
        return radio_mod.player.stop(), None

    volume_response = handle_volume_command(command)
    if volume_response:
        return volume_response, None

    radio_response = handle_radio_command(command)
    if radio_response:
        return radio_response, None

    if "погода" in command and "прогноз" not in command:
        w = get_weather_now()
        if "Ошибка" in w:
            return f"Ошибка: {w['Ошибка']}", w
        text = (f"Сейчас в Москве {w['Температура']}, {w['Погода']}. "
                f"Ощущается как {w['Ощущается']}. Влажность {w['Влажность']}, ветер {w['Ветер']}.")
        return text, w

    if "прогноз" in command:
        days = 7 if "недел" in command or "7" in command else 3
        w = get_weather_forecast(days=days)
        if "Ошибка" in w:
            return f"Ошибка: {w['Ошибка']}", w
        text = f"Прогноз на {days} дней:\n"
        for date, info in w.items():
            text += f"{date}: {info}\n"
        return text, w

    alarm_response = alarm.process_alarm_command(command)
    if alarm_response:
        return alarm_response, None

    addition_response = addition.process_addition_command(command)
    if addition_response:
        return addition_response, None

    if "редактор" in command or "скрипт" in command:
        threading.Thread(target=open_script_editor, daemon=True).start()
        return "Открываю редактор.", None

    executed = run_custom_command(command)
    if executed:
        return f"Выполнено: {executed}", None

    return None, None


# ========================================
# ГОЛОС
# ========================================


class VoiceEngine:
    def __init__(self, model_path):
        if not os.path.exists(model_path):
            print(f"Модель Vosk не найдена: {model_path}", file=sys.stderr)
            sys.exit(1)
        vosk.SetLogLevel(-1)
        self.model = vosk.Model(model_path)
        self.recognizer = vosk.KaldiRecognizer(self.model, AUDIO_RATE)
        self.running = True
        self.wake_detected = False
        self.command_text = ""
        self.state = "waiting"
        self.last_text_time = 0
        self.process = None
        self._muted = False
        self.level = 0.0          # уровень микрофона 0..1 для индикатора
        self._start_arecord()
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _start_arecord(self):
        device = get_mic_device()
        cmd = ["arecord", "-D", device, "-f", "S16_LE", "-r", str(AUDIO_RATE),
               "-c", str(AUDIO_CHANNELS), "-t", "raw", "-q"]
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=10 ** 6)
        print(f"Микрофон: {device}")

    def _is_wake_word(self, text):
        return any(w in text for w in WAKE_WORDS)

    @staticmethod
    def _rms(data):
        """Громкость кадра 0..1 — для индикатора прослушивания."""
        try:
            samples = array("h", data)
        except Exception:
            return 0.0
        if not samples:
            return 0.0
        chunk = samples[::2]  # каждый второй сэмпл — хватает для индикатора
        total = sum(sample * sample for sample in chunk)
        return min(1.0, (total / max(1, len(chunk))) ** 0.5 / 6000.0)

    def _start_listening(self):
        global followup_until
        self.state = "listening"
        self.wake_detected = True
        self.command_text = ""
        self.last_text_time = time.time()
        followup_until = 0.0
        # пока ждём команду, радио приглушается
        if radio_mod.player.active():
            radio_mod.player.duck()

    def _in_followup(self, text):
        """Окно после ответа: слушаем уточнение без слова-активатора."""
        return bool(text) and time.time() < followup_until

    def _listen_loop(self):
        while self.running:
            if not self.process or not self.process.stdout:
                time.sleep(0.1)
                continue
            data = self.process.stdout.read(AUDIO_CHUNK)
            if not data:
                time.sleep(0.05)
                continue

            self.level = self.level * 0.6 + self._rms(data) * 0.4

            # поток читаем всегда (иначе ALSA захлёбывается), но пока говорим
            # сами — кадры в распознавание не отдаём
            muted = audio_guard.audio_playing.is_set() or is_generating
            if muted:
                if not self._muted:
                    self._muted = True
                    self.recognizer.Reset()
                    self.command_text = ""
                    self.state = "waiting"
                    self.wake_detected = False
                continue
            if self._muted:
                self._muted = False
                self.recognizer.Reset()

            if self.recognizer.AcceptWaveform(data):
                res = json.loads(self.recognizer.Result())
                text = res.get("text", "").lower()
                if self.state == "waiting":
                    if self._is_wake_word(text) or self._in_followup(text):
                        self._start_listening()
                elif self.state == "listening":
                    if text:
                        self.command_text += " " + text
                        self.last_text_time = time.time()
            else:
                part = json.loads(self.recognizer.PartialResult())
                pt = part.get("partial", "").lower()
                if pt:
                    if self.state == "waiting" and self._is_wake_word(pt):
                        self._start_listening()
                    elif self.state == "listening":
                        self.last_text_time = time.time()

            if self.state == "listening" and time.time() - self.last_text_time > COMMAND_SILENCE:
                self.state = "processing"
            time.sleep(0.01)

    def get_command(self):
        if self.state == "processing":
            cmd = self.command_text.strip().lower()
            self.command_text = ""
            self.state = "waiting"
            for word in WAKE_WORDS:
                cmd = cmd.replace(word, "").strip()
            if radio_mod.player.active():
                radio_mod.player.restore()
            if not cmd:
                return "привет"
            return cmd
        return None

    def is_wake_detected(self):
        if self.wake_detected:
            self.wake_detected = False
            return True
        return False

    def close(self):
        self.running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass


# ========================================
# ИНТЕРФЕЙС
# ========================================

_logo_cache = None


def get_logo():
    global _logo_cache
    if _logo_cache is None:
        try:
            _logo_cache = pygame.transform.scale(
                pygame.image.load(os.path.join(PROJECT_DIR, "logo.png")), (50, 50)
            )
        except Exception:
            _logo_cache = False
    return _logo_cache


def wrap_text(text, font, max_width):
    words = text.replace("\n", " ").split(" ")
    lines = []
    current = ""
    for word in words:
        test = current + word + " "
        if font.size(test)[0] < max_width:
            current = test
        else:
            if current:
                lines.append(current.strip())
            current = word + " "
    if current:
        lines.append(current.strip())
    return lines


class ChayOKUI:
    def __init__(self):
        self.status = "Ready"
        self.response = "Я ЧайОК, голосовой помощник."
        self.reveal = 0.0          # сколько символов ответа уже показано
        self._last_tick = pygame.time.get_ticks()
        self.subtext = "Скажи 'ЧайОК' или нажми кнопку"
        self.weather_data = None
        self.show_buttons = True
        self.alarm_active = False
        self.timer_active = False
        self.alarm_stop_rect = None
        self.setup_buttons()
        self.voice = None

    def setup_buttons(self):
        btn_w, btn_h, spacing = 105, 45, 6
        y = 360
        button_defs = [
            ("Привет", "привет"),
            ("Погода", "погода"),
            ("Прогноз", "прогноз на неделю"),
            ("Радио", "__radio__"),
            ("Будильник", "__alarm_editor__"),
            ("Редактор", "редактор"),
            ("Выключить", "__shutdown__"),
        ]
        total_w = len(button_defs) * (btn_w + spacing) - spacing
        start_x = (SCREEN_WIDTH - total_w) // 2
        self.buttons = []
        for i, (label, command) in enumerate(button_defs):
            self.buttons.append({
                "rect": pygame.Rect(start_x + i * (btn_w + spacing), y, btn_w, btn_h),
                "label": label,
                "command": command,
                "hover": False,
            })

    def show_alarm(self, level, label):
        self.alarm_active = True
        self.status = f"БУДИЛЬНИК: {label}"
        self.response = "Нажми СТОП"
        self.subtext = "Повтор каждые 5 минут"
        self.show_buttons = False
        self.update_display_alarm()

    def _draw_state_indicator(self, rect, now_ms):
        """Три состояния: говорим, думаем, слушаем."""
        seconds = now_ms / 1000.0
        center = (rect.centerx, rect.centery)

        if audio_guard.audio_playing.is_set():
            pulse = 12 + 3 * math.sin(seconds * 7)
            pygame.draw.circle(screen, COLORS["primary"], center, int(pulse), 2)
            pygame.draw.circle(screen, COLORS["secondary"], center, int(pulse) + 5, 1)
            return

        if is_generating:
            for index in range(3):
                angle = seconds * 4 + index * (2 * math.pi / 3)
                x = center[0] + math.cos(angle) * 15
                y = center[1] + math.sin(angle) * 15
                glow = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(seconds * 6 + index * 2))
                color = tuple(int(channel * glow) for channel in COLORS["accent"])
                pygame.draw.circle(screen, color, (int(x), int(y)), 4)
            return

        if self.voice is not None and getattr(self.voice, "state", "") == "listening":
            level = getattr(self.voice, "level", 0.0)
            radius = 11 + 4 * math.sin(seconds * 5) + 14 * level
            pygame.draw.circle(screen, COLORS["secondary"], center, int(radius), 2)
            pygame.draw.circle(screen, COLORS["primary"], center, int(radius) + 5, 1)

    def _draw_stop_screen(self, status_text):
        screen.fill(COLORS["bg"])
        screen.blit(font_title.render("[ ChayOK ]", True, COLORS["primary"]), (30, 20))
        screen.blit(font_status.render(status_text, True, COLORS["error"]), (30, 110))
        sub = font_small.render("Скажи «стоп» или нажми кнопку", True, COLORS["text_dim"])
        screen.blit(sub, (30, 160))
        btn_rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 30, 300, 80)
        draw_rounded_rect(screen, (200, 30, 30), btn_rect, radius=12)
        btn_text = font_title.render("СТОП", True, (255, 255, 255))
        screen.blit(btn_text, btn_text.get_rect(center=btn_rect.center))
        self.alarm_stop_rect = btn_rect
        if holiday_mode():
            draw_garland(screen, pygame.time.get_ticks() / 1000.0)
        pygame.display.flip()

    def update_display_alarm(self):
        self._draw_stop_screen(self.status)

    def show_timer(self):
        if not self.timer_active:
            self.timer_active = True
            self.show_buttons = False
        self._draw_stop_screen("ТАЙМЕР: время вышло")

    def handle_click(self, pos):
        global is_generating
        if self.timer_active and self.alarm_stop_rect and self.alarm_stop_rect.collidepoint(pos):
            timer_mod.stop()
            self.timer_active = False
            self.show_buttons = True
            self.status = "Ready"
            self.response = "Таймер выключен"
            self.update_display()
            return True
        if self.alarm_active and self.alarm_stop_rect and self.alarm_stop_rect.collidepoint(pos):
            alarm.stop_alarm()
            self.alarm_active = False
            self.show_buttons = True
            self.status = "Ready"
            self.response = "Будильник выключен"
            self.update_display()
            return True
        if not self.alarm_active and not is_generating:
            for btn in self.buttons:
                if btn["rect"].collidepoint(pos):
                    if btn["command"] == "__alarm_editor__":
                        threading.Thread(target=open_alarm_editor, daemon=True).start()
                        self.response = "Открываю редактор будильника."
                    elif btn["command"] == "__radio__":
                        if radio_mod.player.active():
                            self.response = radio_mod.player.stop()
                        else:
                            name = radio_mod.player.start()
                            self.response = f"Радио: {name}" if name else "Не удалось включить радио"
                        self.update_display()
                    elif btn["command"] == "__shutdown__":
                        self.response = "Выключаю..."
                        self.update_display()
                        speak_piper_sync("Выключаю")
                        time.sleep(1)
                        subprocess.run(["sudo", "shutdown", "-h", "now"])
                        pygame.quit()
                        sys.exit(0)
                    else:
                        self.execute_command(btn["command"])
                    return True
        return False

    def execute_command(self, command):
        global is_generating
        if is_generating:
            return
        self.status = "Thinking..."
        self.reveal = 0.0
        self.update_display()

        response, weather = process_command(command)

        if response is not None:
            self.response = response
            self.status = "Response:"
            self.weather_data = weather
            self.update_display()
            speak_piper(response)
        else:
            self.weather_data = None
            threading.Thread(target=ask_llm_streaming, args=(command, self), daemon=True).start()

    def update_status(self, status, subtext=""):
        self.status = status
        self.subtext = subtext
        self.update_display()

    def update_display(self):
        screen.fill(COLORS["bg"])

        # посимвольный вывод ответа
        now_ms = pygame.time.get_ticks()
        delta = min(0.25, max(0.0, (now_ms - self._last_tick) / 1000.0))
        self._last_tick = now_ms
        full_text = self.response or ""
        if self.reveal < len(full_text):
            self.reveal = min(len(full_text), self.reveal + delta * 60)
        elif self.reveal > len(full_text):
            self.reveal = len(full_text)
        visible_text = full_text[:int(self.reveal)]

        logo = get_logo()
        if logo:
            screen.blit(logo, (SCREEN_WIDTH - 70, SCREEN_HEIGHT - 70))

        now = datetime.datetime.now()
        clock = font_clock.render(now.strftime("%H:%M"), True, COLORS["primary"])
        screen.blit(clock, (SCREEN_WIDTH - 30 - clock.get_width(), 6))
        date_text = f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}"
        rendered_date = font_tiny.render(date_text, True, COLORS["text_dim"])
        screen.blit(rendered_date, (SCREEN_WIDTH - 30 - rendered_date.get_width(), 54))

        draw_glow_line(screen, COLORS["primary"], (30, 80), (SCREEN_WIDTH - 30, 80), 2)
        draw_glow_line(screen, COLORS["secondary"], (30, 85), (SCREEN_WIDTH - 30, 85), 1)
        screen.blit(font_title.render("[ ChayOK ]", True, COLORS["primary"]), (30, 12))
        if "Ready" in self.status:
            status_col = COLORS["salad"]
        elif "Thinking" in self.status or "Generating" in self.status:
            status_col = COLORS["accent"]
        elif "Listening" in self.status:
            status_col = COLORS["secondary"]
        else:
            status_col = COLORS["text"]
        screen.blit(font_status.render(self.status, True, status_col), (30, 88))
        self._draw_state_indicator(pygame.Rect(SCREEN_WIDTH - 110, 84, 80, 46), now_ms)

        alarm_data = cached_alarm()
        if alarm_data.get("enabled"):
            alarm_txt = f"Будильник {alarm_data['hour']:02d}:{alarm_data['minute']:02d}"
        else:
            alarm_txt = "Будильник выкл"
        info_parts = [alarm_txt, f"Звук {volume.percent()}%"]
        if radio_mod.player.active():
            info_parts.insert(0, f"Радио: {radio_mod.player.station_name()}")
        timer_text = timer_mod.describe()
        if timer_text:
            info_parts.insert(0, timer_text)
        screen.blit(font_tiny.render(" · ".join(info_parts), True, COLORS["text_dim"]), (30, 128))

        card_w = SCREEN_WIDTH - 60
        if self.weather_data and "Ошибка" not in self.weather_data:
            card_w = SCREEN_WIDTH - 320

        if full_text:
            card = pygame.Rect(30, 150, card_w, 198)
            draw_rounded_rect(screen, COLORS["card_bg"], card, radius=8)
            # только контур: draw_rounded_rect всегда заливает цветом
            pygame.draw.rect(screen, COLORS["border"], card, 1, border_radius=8)
            lines = wrap_text(visible_text, font_text, card_w - 40)
            y = 168
            max_lines = (card.height - 36) // 30
            if radio_mod.player.active():
                max_lines -= 1  # внизу карточки живут волны радио
            shown = lines[-max_lines:] if lines else []
            if len(lines) > max_lines:
                shown[0] = "… " + shown[0]
            for line in shown:
                screen.blit(font_text.render(line, True, COLORS["text"]), (50, y))
                y += 30

            if radio_mod.player.active():
                wave_rect = pygame.Rect(card.left + 14, card.bottom - 34, card.width - 28, 28)
                draw_radio_waves(screen, wave_rect, now_ms / 1000.0)

        if self.weather_data and "Ошибка" not in self.weather_data:
            wx, wy = SCREEN_WIDTH - 280, 150
            panel = pygame.Rect(wx, wy, 250, 190)
            draw_rounded_rect(screen, COLORS["card_bg"], panel, radius=8)
            pygame.draw.rect(screen, COLORS["secondary"], panel, 1, border_radius=8)

            icon_kind = weather_icon_kind(self.weather_data.get("_code", 3))
            draw_weather_icon(screen, icon_kind, pygame.Rect(wx + 10, wy + 10, 64, 64))

            header = font_tiny.render(str(self.weather_data.get("Погода", "")).capitalize(),
                                      True, COLORS["text"])
            screen.blit(header, (wx + 84, wy + 36))

            y_offset = wy + 80
            rows = [(k, v) for k, v in self.weather_data.items()
                    if not k.startswith("_") and k != "Погода"]
            for key, value in rows[:4]:
                screen.blit(font_tiny.render(f"{key}: {value}", True, COLORS["text"]),
                            (wx + 12, y_offset))
                y_offset += 26

        draw_glow_line(screen, COLORS["primary"], (30, 416), (SCREEN_WIDTH - 30, 416), 1)
        if self.subtext:
            screen.blit(font_small.render(self.subtext, True, COLORS["text_dim"]), (30, 432))
        bat_level = get_battery_level()
        if bat_level is not None:
            bat_color = (COLORS["salad"] if bat_level > 60
                         else COLORS["accent"] if bat_level > 30 else COLORS["error"])
            bat_text = font_small.render(f"Battery: {bat_level}%", True, bat_color)
        else:
            bat_text = font_small.render("Battery: --%", True, COLORS["text_dim"])
        # справа, чтобы не наезжать на подпись и логотип
        screen.blit(bat_text, (SCREEN_WIDTH - 240, 432))
        if self.show_buttons:
            mouse_pos = pygame.mouse.get_pos()
            for btn in self.buttons:
                color = COLORS["button_hover"] if btn["rect"].collidepoint(mouse_pos) else COLORS["button"]
                draw_rounded_rect(screen, color, btn["rect"], radius=8)
                btn_text = font_button.render(btn["label"], True, (255, 255, 255))
                screen.blit(btn_text, btn_text.get_rect(center=btn["rect"].center))

        if holiday_mode():
            draw_garland(screen, now_ms / 1000.0)
        pygame.display.flip()


# ========================================
# ГЛАВНАЯ
# ========================================

ui = None


def install_crash_hook():
    """Необработанное исключение — письмо, а не тихая смерть."""
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        notifier.notify("ЧайОК: ошибка", text[-2500:], key="crash")
        notifier.flush(4)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def alarm_ui_callback(level, label):
    global alarm_pending
    alarm_pending = (level, label)


def install_signal_handlers():
    """SIGTERM от systemd — штатная остановка, а не тихая смерть."""
    def handler(signum, frame):
        notifier.notify(
            "ЧайОК остановлен",
            f"Получен сигнал {signum}, приложение завершается.\n"
            f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}",
            key="stop",
        )
        notifier.flush(4)
        try:
            radio_mod.player.stop()
        except Exception:
            pass
        pygame.quit()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handler)


def main():
    global ui, custom_commands, alarm_pending, followup_until, pending_followup
    install_crash_hook()
    install_signal_handlers()
    os.makedirs(PROJECT_DIR, exist_ok=True)
    os.makedirs(os.path.join(PROJECT_DIR, "sounds"), exist_ok=True)
    custom_commands = load_custom_commands()
    if not os.path.exists(commands_path()):
        save_custom_commands(["включи свет", "выключи свет"])

    notifier.notify(
        "ЧайОК запущен",
        f"Устройство: {os.uname().nodename}\n"
        f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"Модель LLM: {LLM_PROVIDERS[0]['name']}",
        key="start",
    )
    watchdog.start()

    ui = ChayOKUI()
    ui.update_display()
    threading.Thread(target=alarm.alarm_checker, args=(alarm_ui_callback,), daemon=True).start()

    voice = VoiceEngine(VOSK_MODEL_PATH)
    ui.voice = voice
    print("Микрофон готов")
    ui.update_status("Ready", "Скажи 'ЧайОК' или нажми кнопку")

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    ui.handle_click(event.pos)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False

            if alarm_pending is not None:
                level, label = alarm_pending
                alarm_pending = None
                ui.show_alarm(level, label)

            if timer_mod.is_ringing():
                ui.show_timer()
            elif ui.timer_active:
                ui.timer_active = False
                ui.show_buttons = True
                ui.status = "Ready"
                ui.response = "Таймер выключен"

            # окно продолжения открываем только после того, как договорили
            if pending_followup and not audio_guard.audio_playing.is_set():
                followup_until = time.time() + FOLLOWUP_SECONDS
                pending_followup = False
                ui.subtext = "Слушаю продолжение..."
            elif followup_until and time.time() > followup_until:
                followup_until = 0.0
                pending_followup = False
                ui.subtext = "Скажи 'ЧайОК' или нажми кнопку"

            if not ui.alarm_active:
                command = voice.get_command()
                if command:
                    ui.execute_command(command)
                elif not ui.timer_active and voice.is_wake_detected():
                    ui.update_status("Listening...", "Говорите...")

            if not ui.alarm_active and not ui.timer_active:
                ui.update_display()
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        voice.close()
        try:
            radio_mod.player.stop()
        except Exception:
            pass
        notifier.notify(
            "ЧайОК остановлен",
            f"Приложение завершило работу.\nВремя: {time.strftime('%d.%m.%Y %H:%M:%S')}",
            key="stop",
        )
        notifier.flush(4)
        pygame.quit()
        sys.exit(0)


if __name__ == "__main__":
    print("ChayOK — голосовой помощник")
    main()
