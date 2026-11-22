"""Радио для ЧайОК: поток ffplay → cvlc → mpg123, громкость через pactl.

pw-play сетевые URL не умеет (libsndfile требует файл), поэтому потоки играет
ffplay с SDL_AUDIODRIVER=pulse — иначе SDL цепляется за встроенную звуковуху.
"""

import json
import os
import shutil
import subprocess
import threading
import time

import config
import volume

BASE_DIR = "/home/pi/ChayOK"
STATIONS_FILE = os.path.join(BASE_DIR, "radio.json")

os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())

DEFAULT_STATIONS = [
    {"name": "Европа Плюс", "url": "https://ep128.hostingradio.ru:8030/ep128"},
    {"name": "Ретро ФМ", "url": "https://retroserver.streamr.ru:8043/retro128"},
    {"name": "Наше Радио", "url": "https://nashe1.hostingradio.ru:80/nashe-128.mp3"},
    {"name": "Максимум", "url": "https://maximum.hostingradio.ru/maximum96.aacp"},
    {"name": "DFM", "url": "https://dfm.hostingradio.ru/dfm96.aacp"},
]

DUCK_FACTOR = float(config.get("radio", "duck_factor", default=0.2))


def load_stations():
    try:
        with open(STATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        stations = [s for s in data.get("stations", []) if s.get("url")]
        if stations:
            default = int(data.get("default", 0))
            return stations, default if 0 <= default < len(stations) else 0
    except Exception:
        pass
    return DEFAULT_STATIONS, 0


class Radio:
    def __init__(self):
        self.stations, self.index = load_stations()
        self.proc = None
        self.stream_id = None
        self.ducked = False
        self._lock = threading.Lock()

    # ---------- состояние ----------

    def active(self):
        return self.proc is not None and self.proc.poll() is None

    def station_name(self):
        if not self.stations:
            return ""
        return self.stations[self.index]["name"]

    # ---------- запуск ----------

    def _player_command(self, url):
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
        if shutil.which("ffplay"):
            env["SDL_AUDIODRIVER"] = "pulse"
            return ["ffplay", "-nodisp", "-loglevel", "quiet", "-volume", "100", url], env
        if shutil.which("cvlc"):
            return ["cvlc", "--aout=pulse", "--intf", "dummy", "--quiet", url], env
        if shutil.which("mpg123"):
            return ["mpg123", "-q", url], env
        return None, env

    @staticmethod
    def _sink_input_ids():
        try:
            out = subprocess.run(["pactl", "list", "short", "sink-inputs"],
                                 capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return set()
        return {line.split("\t")[0] for line in out.splitlines() if line.strip()}

    def _apply_volume(self, fraction):
        if not self.stream_id:
            return
        pct = max(0, min(100, int(round(fraction * 100))))
        try:
            subprocess.run(["pactl", "set-sink-input-volume", self.stream_id, f"{pct}%"],
                           capture_output=True, timeout=5)
        except Exception:
            pass

    def start(self, station=None):
        with self._lock:
            if station is not None:
                self.index = station
            if not self.stations:
                return None
            self.stop_locked()

            url = self.stations[self.index]["url"]
            before = self._sink_input_ids()
            cmd, env = self._player_command(url)
            if not cmd:
                print("Радио: нет доступного плеера")
                return None
            try:
                self.proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
            except Exception as e:
                print("Радио: не удалось запустить плеер:", e)
                self.proc = None
                return None

            self.stream_id = None
            for _ in range(20):
                time.sleep(0.25)
                if self.proc.poll() is not None:
                    break
                new_ids = self._sink_input_ids() - before
                if new_ids:
                    self.stream_id = sorted(new_ids)[-1]
                    break

            self.ducked = False
            self._apply_volume(volume.load())
            print(f"Радио: {self.station_name()}")
            return self.station_name()

    def stop_locked(self):
        if self.proc is not None:
            try:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
            except Exception:
                pass
            self.proc = None
        self.stream_id = None
        self.ducked = False

    def stop(self):
        with self._lock:
            self.stop_locked()
        return "Радио выключено"

    # ---------- управление ----------

    def next_station(self):
        if not self.stations:
            return None
        nxt = (self.index + 1) % len(self.stations)
        return self.start(nxt)

    def prev_station(self):
        if not self.stations:
            return None
        return self.start((self.index - 1) % len(self.stations))

    def set_volume(self, fraction):
        volume.save(fraction)
        self._apply_volume(fraction)
        return fraction

    def duck(self):
        if not self.active() or self.ducked:
            return
        self.ducked = True
        self._apply_volume(volume.load() * DUCK_FACTOR)

    def restore(self):
        if not self.active() or not self.ducked:
            return
        self.ducked = False
        self._apply_volume(volume.load())

    def describe(self):
        if self.active():
            return f"Радио: {self.station_name()}"
        return "Радио выключено"


player = Radio()
