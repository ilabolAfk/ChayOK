#!/usr/bin/env python3
"""Повторные замеры одного и того же промпта: видно разогрев и кэш префикса."""
import json
import sys
import time

import requests

BASE = "/home/pi/ChayOK"
sys.path.insert(0, BASE)
from bench.bench_all import build_prompt, load_llm_settings  # noqa: E402

system, url, max_tokens = load_llm_settings()
prompt = build_prompt(system, "почему небо синее")

for run in range(3):
    payload = {"prompt": prompt, "n_predict": 20, "temperature": 0.3,
               "stop": ["<|im_end|>"], "stream": True}
    started = time.time()
    first = None
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
            if chunk.get("content"):
                if first is None:
                    first = time.time() - started
                tokens += 1
            if chunk.get("stop"):
                break
    total = time.time() - started
    print(f"run {run + 1}: ttfb={first:.1f}c всего={total:.1f}c токенов={tokens} "
          f"{tokens / total:.2f} ток/с")

print("системный промпт, символов:", len(system))
