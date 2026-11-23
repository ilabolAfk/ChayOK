# -*- coding: utf-8 -*-
"""Юнит-тесты калькулятора: запускать python -m unittest discover tests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calc  # noqa: E402


class CalcTest(unittest.TestCase):
    def check(self, phrase, expected):
        self.assertEqual(calc.process_calc_command(phrase), expected, phrase)

    def test_precedence(self):
        self.check("2+2*2", "2 + 2 × 2 = 6")
        self.check("2*2+2", "2 × 2 + 2 = 6")
        self.check("10-3*2", "10 - 3 × 2 = 4")

    def test_spoken(self):
        self.check("два плюс два умножить на два", "2 + 2 × 2 = 6")
        self.check("сколько будет сто двадцать плюс тридцать", "120 + 30 = 150")
        self.check("две тысячи пятьсот минус 500", "2500 - 500 = 2000")

    def test_brackets_and_sign(self):
        self.check("(2+2)*2", "(2 + 2) × 2 = 8")
        self.check("-3 плюс 5", "-3 + 5 = 2")

    def test_division(self):
        self.check("10 разделить на 4", "10 ÷ 4 = 2,5")
        self.assertEqual(calc.process_calc_command("5 разделить на ноль"),
                         "На ноль делить нельзя.")

    def test_power(self):
        self.check("2 в степени 10", "2 ^ 10 = 1024")

    def test_not_math(self):
        for phrase in ("включи радио на 20", "22.11.2026", "расскажи анекдот",
                       "2 2", "сколько времени"):
            self.assertIsNone(calc.process_calc_command(phrase), phrase)


if __name__ == "__main__":
    unittest.main()
