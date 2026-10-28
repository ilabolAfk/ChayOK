#!/usr/bin/env python3
"""
ЧайОК — голосовой помощник
Edge TTS (онлайн) + Piper (офлайн fallback)
"""

import os
import sys
import json
import time
import threading
import subprocess
import tempfile
import re
import datetime
import asyncio
import tkinter as tk
from tkinter import scrolledtext

import vosk
import pygame
import requests
import edge_tts

try:
    import smbus2
    HAS_SMBUS = True
except ImportError:
    HAS_SMBUS = False

import alarm

# ========================================
# НАСТРОЙКИ
# ========================================

WAKE_WORDS = ["чайок", "чаек", "чаёк", "чай ок"]
COMMAND_SILENCE = 2.5

BASE_DIR = "/home/pi"
VOSK_MODEL_PATH = os.path.join(BASE_DIR, "ChayOK/vosk-model")
PIPER_PATH = os.path.join(BASE_DIR, "piper/piper")
PIPER_MODEL = os.path.join(BASE_DIR, "piper/ru_RU-ruslan-medium.onnx")

# --- Edge TTS (онлайн) ---
EDGE_VOICE = "ru-RU-DmitryNeural"  # Мужской голос Microsoft (качественный)

# --- LLM ---
SERVER_OLLAMA_URL = "http://192.168.1.108:11434/api/chat"
SERVER_OLLAMA_MODEL = "qwen2.5:7b-instruct"
LOCAL_OLLAMA_URL = "http://localhost:11434/api/chat"
LOCAL_OLLAMA_MODEL = "qwen2.5:0.5b-instruct"

WEATHER_API_KEY = "ТВОЙ_КЛЮЧ_СЮДА"
CITY = "Moscow"

AUDIO_RATE = 44100
AUDIO_CHANNELS = 1
AUDIO_CHUNK = 1024

MIC_CARD = 3
MIC_DEVICE = 0
SPK_CARD = 4
SPK_DEVICE = 0

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480

alarm_pending = None
is_generating = False
audio_lock = threading.Lock()

# ========================================
# ЦВЕТА
# ========================================

COLORS = {
    "bg": (10, 12, 20), "primary": (0, 180, 255), "secondary": (0, 220, 180),
    "accent": (255, 200, 50), "salad": (120, 255, 120), "text": (200, 210, 230),
    "text_dim": (100, 120, 150), "card_bg": (20, 30, 45), "border": (0, 150, 200),
    "error": (255, 100, 100), "button": (0, 120, 200), "button_hover": (0, 150, 240),
}

# ========================================
# ЭКРАН
# ========================================

os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
pygame.display.set_caption("ChayOK")

try:
    font_title = pygame.font.Font("/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf", 52)
    font_status = pygame.font.Font("/usr/share/fonts/truetype/ubuntu/Ubuntu-Medium.ttf", 38)
    font_text = pygame.font.Font("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf", 24)
    font_small = pygame.font.Font("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf", 18)
    font_tiny = pygame.font.Font("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf", 14)
    font_button = pygame.font.Font("/usr/share/fonts/truetype/ubuntu/Ubuntu-Medium.ttf", 18)
except:
    font_title = pygame.font.Font(None, 52)
    font_status = pygame.font.Font(None, 38)
    font_text = pygame.font.Font(None, 24)
    font_small = pygame.font.Font(None, 18)
    font_tiny = pygame.font.Font(None, 14)
    font_button = pygame.font.Font(None, 18)

# ========================================
# ВСПОМОГАТЕЛЬНЫЕ
# ========================================

def draw_rounded_rect(surface, color, rect, radius=6, border_width=0, border_color=None):
    x, y, w, h = rect
    if w <= 0 or h <= 0: return
    pygame.draw.rect(surface, color, (x + radius, y, w - radius * 2, h))
    pygame.draw.rect(surface, color, (x, y + radius, w, h - radius * 2))
    for cx, cy in [(x + radius, y + radius), (x + w - radius, y + radius), (x + radius, y + h - radius), (x + w - radius, y + h - radius)]:
        pygame.draw.circle(surface, color, (cx, cy), radius)
    if border_width > 0 and border_color:
        pygame.draw.rect(surface, border_color, (x, y, w, h), border_width, border_radius=radius)

def draw_glow_line(surface, color, start, end, width=2):
    pygame.draw.line(surface, color, start, end, width)
    pygame.draw.line(surface, (color[0]//2, color[1]//2, color[2]//2), start, end, width + 4)

def load_custom_commands():
    try:
        with open(os.path.join(BASE_DIR, "ChayOK/custom_commands.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("commands", [])
    except: return []

def save_custom_commands(commands):
    with open(os.path.join(BASE_DIR, "ChayOK/custom_commands.json"), "w", encoding="utf-8") as f:
        json.dump({"commands": commands}, f, ensure_ascii=False, indent=2)

# ========================================
# ЗАРЯД БАТАРЕИ
# ========================================

def get_battery_level():
    if not HAS_SMBUS: return None
    try:
        bus = smbus2.SMBus(1)
        raw = bus.read_word_data(0x42, 0x02)
        voltage_raw = ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)
        voltage_mv = (voltage_raw >> 3) * 4
        if voltage_mv > 8400: return 100
        elif voltage_mv < 6000: return 0
        else: return max(0, min(100, int((voltage_mv - 6000) / (8400 - 6000) * 100)))
    except Exception: return None

# ========================================
# РЕДАКТОРЫ
# ========================================

def open_script_editor():
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
    tk.Label(root, text="Введи команды (по одной на строку):", font=("Arial", 12)).pack(pady=5)
    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Courier", 12))
    text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    commands = load_custom_commands()
    text_area.insert("1.0", "\n".join(commands) if commands else "включи свет\nвыключи свет")
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=5)
    tk.Button(btn_frame, text="Сохранить", command=save_script, bg="lightgreen", font=("Arial", 10)).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Закрыть", command=root.destroy, bg="lightcoral", font=("Arial", 10)).pack(side=tk.LEFT, padx=5)
    status_label = tk.Label(root, text="", font=("Arial", 10))
    status_label.pack()
    root.mainloop()

def open_alarm_editor():
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
    tk.Label(root, text="Настройка будильника", font=("Arial", 14, "bold")).pack(pady=10)
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
    tk.Label(level_frame, text="Уровень жёсткости:", font=("Arial", 12)).pack()
    level_var = tk.StringVar(value=current.get("level", "средний"))
    for lvl in ["мягкий", "средний", "жёсткий"]:
        tk.Radiobutton(level_frame, text=lvl.capitalize(), variable=level_var, value=lvl, font=("Arial", 11)).pack(anchor="w", padx=20)
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=15)
    tk.Button(btn_frame, text="Сохранить", command=save_alarm_settings, bg="lightgreen", font=("Arial", 11), width=12).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Отключить", command=disable_alarm, bg="lightyellow", font=("Arial", 11), width=12).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Закрыть", command=root.destroy, bg="lightcoral", font=("Arial", 11), width=12).pack(side=tk.LEFT, padx=5)
    status_label = tk.Label(root, text="", font=("Arial", 10))
    status_label.pack()
    root.mainloop()

# ========================================
# ПОГОДА
# ========================================

def get_weather_now(city=CITY):
    if not WEATHER_API_KEY or WEATHER_API_KEY == "ТВОЙ_КЛЮЧ_СЮДА": return {"Ошибка": "API ключ не установлен"}
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            d = r.json()
            return {
                "Температура": f"{round(d['main']['temp'])} градусов",
                "Ощущается": f"{round(d['main']['feels_like'])} градусов",
                "Погода": d['weather'][0]['description'],
                "Влажность": f"{d['main']['humidity']}%",
                "Ветер": f"{d['wind']['speed']} м/с"
            }
        return {"Ошибка": f"Код {r.status_code}"}
    except Exception as e: return {"Ошибка": str(e)}

def get_weather_forecast(city=CITY, days=7):
    if not WEATHER_API_KEY or WEATHER_API_KEY == "ТВОЙ_КЛЮЧ_СЮДА": return {"Ошибка": "API ключ не установлен"}
    try:
        url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = {}
            seen = set()
            months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
            for item in data['list']:
                date_iso = item['dt_txt'][:10]
                if date_iso in seen: continue
                if item['dt_txt'][11:16] == "12:00" or not result:
                    dt = datetime.datetime.strptime(date_iso, "%Y-%m-%d")
                    date_ru = f"{dt.day} {months[dt.month - 1]}"
                    result[date_ru] = f"{round(item['main']['temp'])} градусов, {item['weather'][0]['description']}"
                    seen.add(date_iso)
                if len(result) >= days: break
            return result
        return {"Ошибка": f"Код {r.status_code}"}
    except Exception as e: return {"Ошибка": str(e)}

# ========================================
# ОЗВУЧКА (Edge TTS + Piper fallback)
# ========================================

async def _edge_tts_generate(text, output_file):
    """Асинхронно генерирует аудио через Edge TTS."""
    communicate = edge_tts.Communicate(text, EDGE_VOICE)
    await communicate.save(output_file)

def speak_piper_fallback(text):
    """Офлайн-озвучка через Piper (Руслан)."""
    if not text or not os.path.exists(PIPER_PATH): return
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_file = f.name
        cmd = f'echo "{text}" | {PIPER_PATH} --model {PIPER_MODEL} --output_file {temp_file}'
        subprocess.run(cmd, shell=True, capture_output=True, timeout=60)
        with audio_lock:
            subprocess.run(f'pw-play {temp_file}', shell=True, timeout=60)
        os.unlink(temp_file)
        print("[TTS] Piper (офлайн)")
    except Exception as e:
        print(f"Ошибка Piper: {e}")

def speak_hybrid(text):
    """Пробует Edge TTS, если не выходит — Piper."""
    if not text: return

    # Пытаемся использовать Edge TTS (онлайн)
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_file = f.name
        
        # Запускаем асинхронную генерацию
        asyncio.run(_edge_tts_generate(text, temp_file))
        
        # Если файл создан и не пустой — играем
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            with audio_lock:
                subprocess.run(f'pw-play {temp_file}', shell=True, timeout=60)
            os.unlink(temp_file)
            print("[TTS] Edge (онлайн)")
            return
    except Exception as e:
        print(f"[TTS] Edge недоступен: {e}")

    # Если Edge упал — откатываемся на Piper
    print("[TTS] Переключаюсь на Piper...")
    speak_piper_fallback(text)

# ========================================
# LLM (Потоковая генерация)
# ========================================

def ask_llm_streaming(command, ui_ref):
    global is_generating
    is_generating = True
    
    messages = [
        {"role": "system", "content": "Ты — ЧайОК, голосовой помощник. Отвечай кратко и по-русски. ВАЖНО: Никогда не пиши даты в формате ГГГГ-ММ-ДД. Если называешь дату, всегда пиши её словами. Не шути про чай."},
        {"role": "user", "content": command}
    ]

    urls_to_try = [
        (SERVER_OLLAMA_URL, SERVER_OLLAMA_MODEL, "Сервер (ПК)"),
        (LOCAL_OLLAMA_URL, LOCAL_OLLAMA_MODEL, "Локально (Pi)")
    ]

    response = None
    for url, model, name in urls_to_try:
        try:
            payload = {"model": model, "messages": messages, "stream": True}
            r = requests.post(url, json=payload, stream=True, timeout=10)
            if r.status_code == 200:
                print(f"[LLM] {name}")
                response = r
                break
        except Exception as e:
            print(f"[LLM] {name} недоступен: {e}")

    if not response:
        ui_ref.response = "Ошибка: нейросеть недоступна."
        is_generating = False
        return

    full_text = ""
    sentence_buffer = ""
    
    ui_ref.response = ""
    ui_ref.status = "Generating..."

    for line in response.iter_lines():
        if not line: continue
        try:
            chunk = json.loads(line.decode('utf-8'))
            if "message" in chunk and "content" in chunk["message"]:
                token = chunk["message"]["content"]
                full_text += token
                sentence_buffer += token
                
                ui_ref.response = full_text

                if any(p in token for p in ['.', '!', '?', '\n']) and len(sentence_buffer.strip()) > 5:
                    clean_sentence = sentence_buffer.strip()
                    threading.Thread(target=speak_hybrid, args=(clean_sentence,), daemon=True).start()
                    sentence_buffer = ""
        except Exception: pass

    if sentence_buffer.strip():
        threading.Thread(target=speak_hybrid, args=(sentence_buffer.strip(),), daemon=True).start()

    ui_ref.status = "Ready"
    is_generating = False

# ========================================
# КОМАНДЫ
# ========================================

custom_commands = load_custom_commands()

def process_command(command):
    command = command.lower().strip()

    if "погода" in command and "прогноз" not in command:
        w = get_weather_now()
        if "Ошибка" in w: return f"Ошибка: {w['Ошибка']}", w
        text = f"Сейчас в Москве {w['Температура']}, {w['Погода']}. Ощущается как {w['Ощущается']}. Влажность {w['Влажность']}, ветер {w['Ветер']}."
        return text, w

    if "прогноз" in command:
        days = 7 if "недел" in command or "7" in command else 3
        w = get_weather_forecast(days=days)
        if "Ошибка" in w: return f"Ошибка: {w['Ошибка']}", w
        text = f"Прогноз на {days} дней:\n"
        for date, info in w.items(): text += f"{date}: {info}\n"
        return text, w

    alarm_response = alarm.process_alarm_command(command)
    if alarm_response: return alarm_response, None

    if "редактор" in command or "скрипт" in command:
        threading.Thread(target=open_script_editor, daemon=True).start()
        return "Открываю редактор.", None

    for cmd in custom_commands:
        if cmd.lower() in command: return f"Выполнено: {cmd}", None

    return None, None

# ========================================
# ГОЛОС
# ========================================

class VoiceEngine:
    def __init__(self, model_path):
        if not os.path.exists(model_path): sys.exit(1)
        vosk.SetLogLevel(-1)
        self.model = vosk.Model(model_path)
        self.recognizer = vosk.KaldiRecognizer(self.model, AUDIO_RATE)
        self.running = True
        self.wake_detected = False
        self.command_text = ""
        self.state = "waiting"
        self.last_text_time = 0
        self.process = None
        self._start_arecord()
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _start_arecord(self):
        cmd = ["arecord", "-D", f"plughw:{MIC_CARD},{MIC_DEVICE}", "-f", "S16_LE", "-r", str(AUDIO_RATE), "-c", str(AUDIO_CHANNELS), "-t", "raw", "-q"]
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**6)
        print(f"Микрофон: plughw:{MIC_CARD},{MIC_DEVICE}")

    def _is_wake_word(self, text): return any(w in text for w in WAKE_WORDS)

    def _listen_loop(self):
        while self.running:
            if is_generating:
                time.sleep(0.1)
                continue
            data = self.process.stdout.read(AUDIO_CHUNK)
            if not data:
                time.sleep(0.05)
                continue
            if self.recognizer.AcceptWaveform(data):
                res = json.loads(self.recognizer.Result())
                text = res.get("text", "").lower()
                if self.state == "waiting":
                    if self._is_wake_word(text):
                        self.state = "listening"
                        self.wake_detected = True
                        self.command_text = ""
                        self.last_text_time = time.time()
                elif self.state == "listening":
                    if text:
                        self.command_text += " " + text
                        self.last_text_time = time.time()
            else:
                part = json.loads(self.recognizer.PartialResult())
                pt = part.get("partial", "").lower()
                if pt:
                    if self.state == "waiting" and self._is_wake_word(pt):
                        self.state = "listening"
                        self.wake_detected = True
                        self.command_text = ""
                        self.last_text_time = time.time()
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
                
            if not cmd: return "привет"
            return cmd
        return None

    def is_wake_detected(self):
        if self.wake_detected:
            self.wake_detected = False
            return True
        return False

    def close(self):
        self.running = False
        if self.process: self.process.terminate()

# ========================================
# ИНТЕРФЕЙС
# ========================================

class ChayOKUI:
    def __init__(self):
        self.status = "Ready"
        self.response = "Я ЧайОК, голосовой помощник."
        self.subtext = "Скажи 'ЧайОК' или нажми кнопку"
        self.weather_data = None
        self.show_buttons = True
        self.alarm_active = False
        self.alarm_stop_rect = None
        self.setup_buttons()
        self.voice = None

    def setup_buttons(self):
        btn_w, btn_h, spacing = 105, 45, 8
        y = SCREEN_HEIGHT - 100
        button_defs = [("Привет", "привет"), ("Погода", "погода"), ("Прогноз", "прогноз на неделю"), ("Будильник", "__alarm_editor__"), ("Редактор", "редактор"), ("Выключить", "__shutdown__")]
        total_w = len(button_defs) * (btn_w + spacing) - spacing
        start_x = (SCREEN_WIDTH - total_w) // 2
        self.buttons = []
        for i, (label, command) in enumerate(button_defs):
            self.buttons.append({"rect": pygame.Rect(start_x + i * (btn_w + spacing), y, btn_w, btn_h), "label": label, "command": command, "hover": False})

    def show_alarm(self, level, label):
        self.alarm_active = True
        self.status = f"БУДИЛЬНИК: {label}"
        self.response = "Нажми СТОП"
        self.subtext = "Повтор каждые 5 минут"
        self.show_buttons = False
        self.update_display_alarm()

    def update_display_alarm(self):
        screen.fill(COLORS["bg"])
        screen.blit(font_title.render("[ ChayOK ]", True, COLORS["primary"]), (30, 20))
        screen.blit(font_status.render(self.status, True, COLORS["error"]), (30, 110))
        btn_rect = pygame.Rect(SCREEN_WIDTH//2 - 150, SCREEN_HEIGHT//2 + 30, 300, 80)
        draw_rounded_rect(screen, (200, 30, 30), btn_rect, radius=12)
        btn_text = font_title.render("СТОП", True, (255, 255, 255))
        screen.blit(btn_text, btn_text.get_rect(center=btn_rect.center))
        self.alarm_stop_rect = btn_rect
        pygame.display.flip()

    def handle_click(self, pos):
        global is_generating
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
                    elif btn["command"] == "__shutdown__":
                        self.response = "Выключаю..."
                        self.update_display()
                        speak_hybrid("Выключаю")
                        time.sleep(2)
                        subprocess.run(["sudo", "shutdown", "-h", "now"])
                        pygame.quit()
                        sys.exit(0)
                    else:
                        self.execute_command(btn["command"])
                    return True
        return False

    def execute_command(self, command):
        global is_generating
        self.status = "Thinking..."
        self.update_display()
        
        response, weather = process_command(command)
        
        if response is not None:
            self.response = response
            self.status = "Response:"
            self.weather_data = weather
            self.update_display()
            threading.Thread(target=speak_hybrid, args=(response,), daemon=True).start()
        else:
            self.weather_data = None
            threading.Thread(target=ask_llm_streaming, args=(command, self), daemon=True).start()

    def update_status(self, status, subtext=""):
        self.status = status
        self.subtext = subtext
        self.update_display()

    def update_display(self):
        screen.fill(COLORS["bg"])
        try:
            logo = pygame.image.load(os.path.join(BASE_DIR, "ChayOK/logo.png"))
            screen.blit(pygame.transform.scale(logo, (50, 50)), (SCREEN_WIDTH - 70, SCREEN_HEIGHT - 70))
        except: pass
        
        draw_glow_line(screen, COLORS["primary"], (30, 85), (SCREEN_WIDTH - 30, 85), 2)
        draw_glow_line(screen, COLORS["secondary"], (30, 90), (SCREEN_WIDTH - 30, 90), 1)
        screen.blit(font_title.render("[ ChayOK ]", True, COLORS["primary"]), (30, 20))
        status_col = COLORS["salad"] if "Ready" in self.status else COLORS["accent"] if "Thinking" in self.status else COLORS["text"]
        screen.blit(font_status.render(self.status, True, status_col), (30, 110))
        
        if self.response:
            card = pygame.Rect(30, 180, SCREEN_WIDTH - 60, 200)
            draw_rounded_rect(screen, COLORS["card_bg"], card, radius=8)
            draw_rounded_rect(screen, COLORS["border"], card, radius=8, border_width=1, border_color=COLORS["border"])
            
            words = self.response.replace('\n', ' ').split(' ')
            lines = []
            current_line = ""
            max_width = SCREEN_WIDTH - 100
            for word in words:
                test_line = current_line + word + " "
                if font_text.size(test_line)[0] < max_width:
                    current_line = test_line
                else:
                    if current_line: lines.append(current_line.strip())
                    current_line = word + " "
            if current_line: lines.append(current_line.strip())
            
            y = 200
            for line in lines[-6:]:
                screen.blit(font_text.render(line, True, COLORS["text"]), (50, y))
                y += 30

        if self.weather_data and "Ошибка" not in self.weather_data:
            wx, wy = SCREEN_WIDTH - 280, 120
            draw_rounded_rect(screen, COLORS["salad"], (wx, wy, 250, 320), radius=8)
            y_offset = wy + 10
            for k, v in list(self.weather_data.items())[:8]:
                screen.blit(font_small.render(f"{k}: {v}", True, (0, 0, 60)), (wx + 10, y_offset))
                y_offset += 25
                
        draw_glow_line(screen, COLORS["primary"], (30, SCREEN_HEIGHT - 50), (SCREEN_WIDTH - 30, SCREEN_HEIGHT - 50), 1)
        if self.subtext: screen.blit(font_small.render(self.subtext, True, COLORS["text_dim"]), (30, SCREEN_HEIGHT - 40))
        bat_level = get_battery_level()
        if bat_level is not None:
            bat_color = COLORS["salad"] if bat_level > 60 else COLORS["accent"] if bat_level > 30 else COLORS["error"]
            screen.blit(font_small.render(f"Battery: {bat_level}%", True, bat_color), (SCREEN_WIDTH // 2 - 40, SCREEN_HEIGHT - 40))
        else:
            screen.blit(font_small.render("Battery: --%", True, COLORS["text_dim"]), (SCREEN_WIDTH // 2 - 40, SCREEN_HEIGHT - 40))
        if self.show_buttons:
            mouse_pos = pygame.mouse.get_pos()
            for btn in self.buttons:
                color = COLORS["button_hover"] if btn["rect"].collidepoint(mouse_pos) else COLORS["button"]
                draw_rounded_rect(screen, color, btn["rect"], radius=8)
                btn_text = font_button.render(btn["label"], True, (255, 255, 255))
                screen.blit(btn_text, btn_text.get_rect(center=btn["rect"].center))
        pygame.display.flip()

# ========================================
# ГЛАВНАЯ
# ========================================

ui = None

def alarm_ui_callback(level, label):
    global alarm_pending
    alarm_pending = (level, label)

def main():
    global ui, custom_commands, alarm_pending
    os.makedirs(os.path.join(BASE_DIR, "ChayOK"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "ChayOK/sounds"), exist_ok=True)
    custom_commands = load_custom_commands()
    if not os.path.exists(os.path.join(BASE_DIR, "ChayOK/custom_commands.json")):
        save_custom_commands(["включи свет", "выключи свет"])
        
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
                if event.type == pygame.QUIT: running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1: ui.handle_click(event.pos)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: running = False
            
            if alarm_pending is not None:
                level, label = alarm_pending
                alarm_pending = None
                ui.show_alarm(level, label)
                
            if not ui.alarm_active:
                if voice.is_wake_detected(): ui.update_status("Listening...", "Говорите...")
                command = voice.get_command()
                if command:
                    ui.execute_command(command)
                    
            ui.update_display()
            time.sleep(0.05)
    except KeyboardInterrupt: pass
    finally:
        voice.close()
        pygame.quit()
        sys.exit(0)

if __name__ == "__main__":
    print("ChayOK — голосовой помощник")
    main()
