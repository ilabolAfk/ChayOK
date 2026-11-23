#!/usr/bin/env python3
"""
Мгновенные ответы на простые вопросы — без модели.

Модель на Pi выдаёт меньше токена в секунду, поэтому «который час»
дешевле посчитать, чем сгенерировать (и точнее).
"""

import datetime
import re

import radio as radio_mod
import timer as timer_mod
import volume

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница",
            "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _plural(value, one, few, many):
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def _time_answer(_match):
    now = datetime.datetime.now()
    hours = _plural(now.hour, "час", "часа", "часов")
    minutes = _plural(now.minute, "минута", "минуты", "минут")
    if now.minute == 0:
        return f"Сейчас {now.hour} {hours} ровно."
    return f"Сейчас {now.hour} {hours} {now.minute} {minutes}."


def _date_answer(_match):
    now = datetime.datetime.now()
    return f"Сегодня {WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}."


def _radio_answer(_match):
    if radio_mod.player.active():
        return f"Играет {radio_mod.player.station_name()}."
    return "Радио выключено."


def _timer_answer(_match):
    text = timer_mod.describe()
    return text or "Таймер не запущен."


def _volume_answer(_match):
    value = volume.percent()
    return f"Громкость {value} {_plural(value, 'процент', 'процента', 'процентов')}."


def _battery_answer(_match):
    import main  # ленивый импорт: main тянет pygame
    level = main.get_battery_level()
    if level is None:
        return "Заряд не измеряется."
    return f"Заряд {level} {_plural(level, 'процент', 'процента', 'процентов')}."


RULES = (
    (re.compile(r"^(сколько времени|который час|сколько время)\??$"), _time_answer),
    (re.compile(r"^(какое сегодня число|какая сегодня дата|какая дата|какое число|"
                r"сегодняшняя дата)\??$"), _date_answer),
    (re.compile(r"^(что играет|что за станция|какая станция)\??$"), _radio_answer),
    (re.compile(r"^(что с таймером|сколько осталось|таймер)\??$"), _timer_answer),
    (re.compile(r"^(какая громкость|громкость|какой звук)\??$"), _volume_answer),
    (re.compile(r"^(какой заряд|сколько заряда|заряд батареи)\??$"), _battery_answer),
    (re.compile(r"^(как дела|как ты|как настроение)\??$"),
     lambda _m: "Всё хорошо, спасибо. Готов помочь."),
    (re.compile(r"^(спасибо|благодарю|спасибо большое)\??$"),
     lambda _m: "Пожалуйста."),
    (re.compile(r"^(что ты умеешь|что можешь|твои возможности)\??$"),
     lambda _m: ("Могу включить радио, поставить таймер и будильник, сказать погоду, "
                 "посчитать пример и ответить на вопрос.")),
)


def process_quick_command(command):
    """Возвращает готовый ответ или None, если фраза не из быстрых."""
    text = command.strip().lower().rstrip(" .!…")
    for pattern, handler in RULES:
        match = pattern.match(text)
        if match:
            try:
                return handler(match)
            except Exception as exc:
                print(f"[quick] {exc}")
                return None
    return None
