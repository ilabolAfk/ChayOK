"""Единый конфиг ЧайОК: config.json поверх значений по умолчанию.

Всё, что раньше было зашито в main.py (голос, модель LLM, погода, порог тишины,
веб-панель), читается отсюда. Файл правится из веб-панели.
"""

import copy
import json
import os
import threading

BASE_DIR = "/home/pi/ChayOK"
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT = {
    "voice": {
        "model": "/home/pi/piper/ru_RU-ruslan-medium.onnx",
        "piper": "/home/pi/piper/piper",
        "length_scale": 1.05,
        "sentence_silence": 0.35,
        "volume": 0.9,
    },
    "llm": {
        "system_prompt": (
            "Ты — ЧайОК, голосовой помощник в маленьком устройстве. "
            "Отвечай по-русски, кратко: одно-два предложения, без списков и разметки. "
            "Никогда не пиши даты в формате ГГГГ-ММ-ДД — называй дату словами."
        ),
        "history_limit": 4,
        "timeout_connect": 5,
        "timeout_read": 180,
        "providers": [
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
        ],
    },
    "audio": {
        "rate": 16000,
        "channels": 1,
        "chunk": 4000,
        "mic_device": "",
        "spk_device": "",
    },
    "voice_input": {
        "wake_words": ["чайок", "чаек", "чаёк", "чай ок"],
        "command_silence": 2.5,
        "followup_seconds": 5,
    },
    "weather": {
        "city": "Москва",
        "latitude": 55.7558,
        "longitude": 37.6173,
        "timezone": "Europe/Moscow",
    },
    "radio": {
        "duck_factor": 0.2,
    },
    "screen": {
        "width": 800,
        "height": 480,
    },
    "web": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8000,
        "password": "",
    },
}

_cache = None
_lock = threading.Lock()


def _merge(base, overrides):
    result = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load():
    """Читает config.json; отсутствующие ключи берутся из DEFAULT."""
    global _cache
    data = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("config.json:", e)
    with _lock:
        _cache = _merge(DEFAULT, data)
    return _cache


def reload():
    return load()


def get(*keys, default=None):
    if _cache is None:
        load()
    node = _cache
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return copy.deepcopy(node)


def save(new_values):
    """Сохраняет конфиг (полная замена), возвращает итоговые значения."""
    if not isinstance(new_values, dict):
        raise ValueError("конфиг должен быть объектом JSON")
    merged = _merge(DEFAULT, new_values)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    return reload()


def as_dict():
    if _cache is None:
        load()
    return copy.deepcopy(_cache)
