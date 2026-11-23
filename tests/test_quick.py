# -*- coding: utf-8 -*-
"""Юнит-тесты быстрых ответов. Радио/таймер/громкость подменяются заглушками,
чтобы тест шёл и на Windows."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_state = {"radio": False, "station": "Европа Плюс", "timer": "", "volume": 45}

player = types.SimpleNamespace(
    active=lambda: _state["radio"],
    station_name=lambda: _state["station"],
)
sys.modules.setdefault("radio", types.SimpleNamespace(player=player))
sys.modules.setdefault("timer", types.SimpleNamespace(
    describe=lambda: _state["timer"], is_running=lambda: bool(_state["timer"])))
sys.modules.setdefault("volume", types.SimpleNamespace(
    percent=lambda: _state["volume"]))

import quick  # noqa: E402


class QuickTest(unittest.TestCase):
    def setUp(self):
        _state.update({"radio": False, "timer": "", "volume": 45})

    def test_time(self):
        answer = quick.process_quick_command("который час")
        self.assertTrue(answer.startswith("Сейчас"))
        self.assertTrue(answer.endswith("."))

    def test_date(self):
        self.assertIn("Сегодня", quick.process_quick_command("какое сегодня число"))

    def test_radio_state(self):
        self.assertEqual(quick.process_quick_command("что играет"), "Радио выключено.")
        _state["radio"] = True
        self.assertEqual(quick.process_quick_command("что играет"),
                         "Играет Европа Плюс.")

    def test_timer_and_volume(self):
        self.assertEqual(quick.process_quick_command("таймер"), "Таймер не запущен.")
        _state["timer"] = "Таймер: 4 мин"
        self.assertEqual(quick.process_quick_command("что с таймером"), "Таймер: 4 мин")
        self.assertIn("45", quick.process_quick_command("какая громкость"))

    def test_small_talk(self):
        self.assertEqual(quick.process_quick_command("спасибо"), "Пожалуйста.")
        self.assertIn("хорошо", quick.process_quick_command("как дела"))

    def test_free_questions_go_to_model(self):
        for phrase in ("расскажи про космос", "что такое время",
                       "почему небо синее", "сколько времени нужно на дорогу"):
            self.assertIsNone(quick.process_quick_command(phrase), phrase)


if __name__ == "__main__":
    unittest.main()
