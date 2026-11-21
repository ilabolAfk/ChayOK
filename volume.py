"""Общий уровень громкости ЧайОК (0.0 … 1.0) с сохранением в volume.json."""

import json
import os

BASE_DIR = "/home/pi/ChayOK"
VOLUME_FILE = os.path.join(BASE_DIR, "volume.json")
DEFAULT = 0.7

_cache = None


def _clamp(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return DEFAULT
    return max(0.0, min(1.0, value))


def load():
    global _cache
    if _cache is None:
        try:
            with open(VOLUME_FILE, "r", encoding="utf-8") as f:
                _cache = _clamp(json.load(f).get("level", DEFAULT))
        except Exception:
            _cache = DEFAULT
    return _cache


def save(value):
    global _cache
    _cache = _clamp(value)
    try:
        with open(VOLUME_FILE, "w", encoding="utf-8") as f:
            json.dump({"level": round(_cache, 2)}, f, indent=2)
    except Exception as e:
        print("volume.json:", e)
    return _cache


def set_level(value):
    return save(value)


def adjust(delta):
    return save(load() + delta)


def percent():
    return int(round(load() * 100))


def describe():
    return f"Громкость {percent()} процентов"
