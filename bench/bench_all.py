#!/usr/bin/env python3
"""Замеры ЧайОКа: LLM (TTFB, токены/с), Piper (скорость синтеза), быстрые ответы.

Запуск на Pi:  ./venv/bin/python bench/bench_all.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave

import requests

BASE = "/home/pi/ChayOK"
sys.path.insert(0, BASE)

PROMPTS = [
    "расскажи про космос",
    "что такое фотосинтез",
    "посоветуй фильм на вечер",
    "почему небо синее",
    "как заварить чай",
]

PIPER = os.path.join("/home/pi/piper", "piper")
PIPER_MODEL = os.path.join("/home/pi/piper", "ru_RU-ruslan-medium.onnx")
PIPER_TEXT = ("Привет! Я ЧайОК, голосовой помощник. Сегодня двадцать третье ноября, "
              "за окном минус три градуса.")


def load_llm_settings():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as handle:
        llm = json.load(handle).get("llm", {})
    provider = next((p for p in llm.get("providers", [])
                     if "llama.cpp" in p.get("name", "")), {})
    return (llm.get("system_prompt", "Ты — ЧайОК."),
            provider.get("url", "http://127.0.0.1:8080/completion"),
            int(provider.get("max_tokens", 60)))


def build_prompt(system, question):
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{question}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n</think>\n")


def bench_llm():
    system, url, max_tokens = load_llm_settings()
    rows = []
    print(f"LLM: {url}, n_predict={max_tokens}")
    for question in PROMPTS:
        payload = {"prompt": build_prompt(system, question), "n_predict": max_tokens,
                   "temperature": 0.3, "top_p": 0.9, "repeat_penalty": 1.15,
                   "stop": ["<|im_end|>", "<|im_start|>"], "stream": True}
        started = time.time()
        first = None
        text = ""
        tokens = 0
        with requests.post(url, json=payload, stream=True, timeout=300) as response:
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = chunk.get("content") or ""
                if piece:
                    if first is None:
                        first = time.time() - started
                    text += piece
                    tokens += 1
                if chunk.get("stop"):
                    break
        total = time.time() - started
        speed = tokens / total if total else 0
        sentences = len(re.findall(r"[.!?…]+", text))
        rows.append({"prompt": question, "ttfb": first or total, "total": total,
                     "tokens": tokens, "tok_s": speed, "chars": len(text),
                     "sentences": sentences})
        print(f"  {question:28} ttfb={rows[-1]['ttfb']:5.1f}c  "
              f"всего={total:5.1f}c  {tokens:3} ток  {speed:4.2f} ток/с  "
              f"{len(text)} симв  {sentences} предл.")
    return rows


def bench_piper():
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for scale, silence in (("1.05", "0.35"), ("1.00", "0.20")):
            out = os.path.join(tmp, f"t_{scale}.wav")
            started = time.time()
            proc = subprocess.run(
                [PIPER, "--model", PIPER_MODEL, "--output_file", out,
                 "--length_scale", scale, "--sentence_silence", silence],
                input=PIPER_TEXT.encode("utf-8"), capture_output=True, timeout=180)
            synth = time.time() - started
            if proc.returncode != 0:
                print("  piper error:", proc.stderr.decode()[:200])
                continue
            with wave.open(out) as handle:
                duration = handle.getnframes() / handle.getframerate()
            results.append({"length_scale": scale, "synth_s": synth,
                            "audio_s": duration,
                            "rtf": synth / duration if duration else 0})
            print(f"  piper length={scale} silence={silence}: "
                  f"синтез {synth:.2f}c, звук {duration:.2f}c, RTF {synth / duration:.2f}")
    return results


def bench_fast_paths():
    import calc
    import quick

    started = time.time()
    for _ in range(200):
        calc.process_calc_command("два плюс два умножить на два")
    calc_ms = (time.time() - started) / 200 * 1000

    started = time.time()
    for _ in range(200):
        quick.process_quick_command("который час")
    quick_ms = (time.time() - started) / 200 * 1000

    print(f"  calc: {calc_ms:.3f} мс, quick: {quick_ms:.3f} мс")
    return {"calc_ms": calc_ms, "quick_ms": quick_ms}


def main():
    report = {"llm": bench_llm(), "piper": bench_piper(), "fast": bench_fast_paths()}
    path = os.path.join(BASE, "bench", "bench_report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("отчёт:", path)


if __name__ == "__main__":
    main()
