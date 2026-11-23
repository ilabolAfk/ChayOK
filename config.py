"""Р•РґРёРЅС‹Р№ РєРѕРЅС„РёРі Р§Р°Р№РћРљ: config.json РїРѕРІРµСЂС… Р·РЅР°С‡РµРЅРёР№ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ.

Р’СЃС‘, С‡С‚Рѕ СЂР°РЅСЊС€Рµ Р±С‹Р»Рѕ Р·Р°С€РёС‚Рѕ РІ main.py (РіРѕР»РѕСЃ, РјРѕРґРµР»СЊ LLM, РїРѕРіРѕРґР°, РїРѕСЂРѕРі С‚РёС€РёРЅС‹,
РІРµР±-РїР°РЅРµР»СЊ), С‡РёС‚Р°РµС‚СЃСЏ РѕС‚СЃСЋРґР°. Р¤Р°Р№Р» РїСЂР°РІРёС‚СЃСЏ РёР· РІРµР±-РїР°РЅРµР»Рё.
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
            "РўС‹ вЂ” Р§Р°Р№РћРљ. РћС‚РІРµС‡Р°Р№ РїРѕ-СЂСѓСЃСЃРєРё, РѕРґРЅРѕ-РґРІР° РїСЂРµРґР»РѕР¶РµРЅРёСЏ, Р±РµР· СЃРїРёСЃРєРѕРІ. "
            "Р”Р°С‚С‹ РЅР°Р·С‹РІР°Р№ СЃР»РѕРІР°РјРё."
        ),
        "history_limit": 1,
        "timeout_connect": 5,
        "timeout_read": 180,
        "providers": [
            {
                "kind": "completion",
                "url": "http://127.0.0.1:8080/completion",
                "name": "Bonsai (Pi, llama.cpp)",
                "max_tokens": 45,
            },
            {
                "kind": "ollama",
                "url": "http://192.168.1.108:11434/api/chat",
                "model": "qwen2.5:7b-instruct",
                "name": "РЎРµСЂРІРµСЂ (РџРљ)",
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
        "wake_words": ["С‡Р°Р№РѕРє", "С‡Р°РµРє", "С‡Р°С‘Рє", "С‡Р°Р№ РѕРє"],
        "command_silence": 2.5,
        "followup_seconds": 5,
    },
    "weather": {
        "city": "РњРѕСЃРєРІР°",
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
    """Р§РёС‚Р°РµС‚ config.json; РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёРµ РєР»СЋС‡Рё Р±РµСЂСѓС‚СЃСЏ РёР· DEFAULT."""
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
    """РЎРѕС…СЂР°РЅСЏРµС‚ РєРѕРЅС„РёРі (РїРѕР»РЅР°СЏ Р·Р°РјРµРЅР°), РІРѕР·РІСЂР°С‰Р°РµС‚ РёС‚РѕРіРѕРІС‹Рµ Р·РЅР°С‡РµРЅРёСЏ."""
    if not isinstance(new_values, dict):
        raise ValueError("РєРѕРЅС„РёРі РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РѕР±СЉРµРєС‚РѕРј JSON")
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

