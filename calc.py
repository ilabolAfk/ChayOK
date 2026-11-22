#!/usr/bin/env python3
"""
Калькулятор для ЧайОК: арифметика считается парсером, а не моделью.
Отвечает только если вся фраза состоит из чисел, скобок и операций.
"""

import math
import re

_UNITS = {
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30,
    "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200,
    "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_THOUSAND = {"тысяча", "тысячи", "тысяч"}

_PHRASES = (
    ("умножить на", "*"), ("разделить на", "/"), ("поделить на", "/"),
    ("делить на", "/"), ("в степени", "**"),
    ("скобка открывается", "("), ("скобка закрывается", ")"),
    ("открывающая скобка", "("), ("закрывающая скобка", ")"),
)
_WORDS = {
    "плюс": "+", "минус": "-", "умножить": "*", "разделить": "/",
    "поделить": "/", "делить": "/",
}
_PREFIX = re.compile(
    r"^(сколько будет|сколько получится|сколько|посчитай|вычисли|сосчитай|калькулятор)\s+")
_ALLOWED = re.compile(r"^[\d\s+\-*/().]+$")
_TOKEN = re.compile(r"\d+(?:\.\d+)?|\*\*|[+\-*/()]")


def _numbers_to_digits(text):
    """'двадцать пять' -> '25', 'две тысячи пятьсот' -> '2500'."""
    out, acc, have = [], 0, False
    for word in text.split():
        if word in _UNITS:
            acc += _UNITS[word]
            have = True
        elif word in _THOUSAND:
            acc = (acc or 1) * 1000
            have = True
        else:
            if have:
                out.append(str(acc))
                acc, have = 0, False
            out.append(word)
    if have:
        out.append(str(acc))
    return " ".join(out)


def _build_expression(command):
    text = _PREFIX.sub("", command.lower().strip()).strip()
    for src, dst in _PHRASES:
        text = text.replace(src, f" {dst} ")
    text = _numbers_to_digits(text)
    for word, symbol in _WORDS.items():
        text = re.sub(rf"\b{word}\b", f" {symbol} ", text)
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class _Parser:
    """Рекурсивный спуск: + - , * / , ** , унарный минус, скобки."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.pos += 1
        return token

    def parse(self):
        value = self.expr()
        if self.peek() is not None:
            raise ValueError("лишние символы")
        return value

    def expr(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.term()
            value = value + right if op == "+" else value - right
        return value

    def term(self):
        value = self.power()
        while self.peek() in ("*", "/"):
            op = self.take()
            right = self.power()
            if op == "*":
                value *= right
            else:
                if right == 0:
                    raise ZeroDivisionError
                value /= right
        return value

    def power(self):
        value = self.unary()
        if self.peek() == "**":
            self.take()
            return value ** self.power()
        return value

    def unary(self):
        if self.peek() in ("+", "-"):
            op = self.take()
            value = self.unary()
            return -value if op == "-" else value
        return self.primary()

    def primary(self):
        token = self.take()
        if token == "(":
            value = self.expr()
            if self.take() != ")":
                raise ValueError("нет закрывающей скобки")
            return value
        if token is None or not re.fullmatch(r"\d+(?:\.\d+)?", token):
            raise ValueError("ожидалось число")
        return float(token)


def _format(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", ",")


_SYMBOLS = {"+": "+", "-": "-", "*": "×", "/": "÷", "**": "^"}


def _pretty(tokens):
    """Расставляет пробелы так, чтобы читалось как пример на бумаге."""
    out, prev = "", None
    for token in tokens:
        if token == "(":
            if prev is not None and prev not in ("(", "**", "+", "-", "*", "/"):
                out += " "
            out += "("
        elif token == ")":
            out += ")"
        elif token in _SYMBOLS:
            if token == "-" and (prev is None or prev in ("(", "**", "+", "-", "*", "/")):
                out += "-"
            else:
                out += f" {_SYMBOLS[token]} "
        else:
            if prev == ")":
                out += " "
            out += token
        prev = token
    return out



def process_calc_command(command):
    expression = _build_expression(command)
    if not expression or not _ALLOWED.match(expression):
        return None
    if not re.search(r"\d", expression) or not re.search(r"[+\-*/]", expression):
        return None

    tokens = _TOKEN.findall(expression)
    if "".join(tokens) != expression.replace(" ", ""):
        return None

    try:
        value = _Parser(tokens).parse()
    except ZeroDivisionError:
        return "На ноль делить нельзя."
    except (ValueError, OverflowError, RecursionError):
        return None

    if not math.isfinite(value) or abs(value) > 1e15:
        return None

    shown = _pretty(tokens)
    return f"{shown} = {_format(value)}"


if __name__ == "__main__":
    cases = {
        "2+2*2": "2 + 2 × 2 = 6",
        "два плюс два умножить на два": "2 + 2 × 2 = 6",
        "сколько будет два плюс два умножить на два": "2 + 2 × 2 = 6",
        "(2+2)*2": "(2 + 2) × 2 = 8",
        "10 разделить на 4": "10 ÷ 4 = 2,5",
        "2 в степени 10": "2 ^ 10 = 1024",
        "сто двадцать плюс тридцать": "120 + 30 = 150",
        "две тысячи пятьсот минус 500": "2500 - 500 = 2000",
        "-3 плюс 5": "-3 + 5 = 2",
        "5 - 10 процентов": None,
        "включи радио на 20": None,
        "22.11.2026": None,
        "расскажи анекдот": None,
        "2 2": None,
    }
    bad = 0
    for src, want in cases.items():
        got = process_calc_command(src)
        if got != want:
            bad += 1
            print(f"FAIL {src!r}: got {got!r}, want {want!r}")
    print("деление на ноль:", process_calc_command("5 разделить на ноль"))
    print(f"провалов: {bad}")
