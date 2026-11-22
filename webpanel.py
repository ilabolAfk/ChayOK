"""Веб-панель ЧайОК: статус, радио, будильник, таймер, громкость и настройки.

Без внешних зависимостей — стандартная библиотека. Открывается с телефона
в домашней сети: http://<ip>:8000
"""

import glob
import json
import os
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import alarm
import config
import radio as radio_mod
import timer as timer_mod
import volume

_status_provider = None
_restart_callback = None
PIPER_DIR = "/home/pi/piper"
BASE_DIR = "/home/pi/ChayOK"
UPDATE_LOG = "/tmp/chayok_update.log"


def _password():
    return str(config.get("web", "password", default="") or "")


def _authorized(handler):
    password = _password()
    if not password:
        return True
    if handler.headers.get("X-Token", "") == password:
        return True
    query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    return query.get("token", [""])[0] == password


def _status():
    alarm_data = alarm.load_alarm()
    result = {
        "ok": True,
        "radio": {
            "active": radio_mod.player.active(),
            "station": radio_mod.player.station_name(),
            "index": radio_mod.player.index,
            "stations": [s["name"] for s in radio_mod.player.stations],
        },
        "alarm": alarm_data,
        "timer": {
            "running": timer_mod.is_running(),
            "ringing": timer_mod.is_ringing(),
            "text": timer_mod.describe(),
        },
        "volume": volume.percent(),
    }
    if _status_provider:
        try:
            result.update(_status_provider() or {})
        except Exception as e:
            result["status_error"] = str(e)
    return result


_prev_cpu = None


def _cpu_percent():
    """Загрузка ЦП по дельте /proc/stat между запросами."""
    global _prev_cpu
    try:
        with open("/proc/stat") as handle:
            parts = [int(x) for x in handle.readline().split()[1:9]]
    except Exception:
        return 0.0
    idle = parts[3] + parts[4]
    total = sum(parts)
    prev, _prev_cpu = _prev_cpu, (idle, total)
    if not prev:
        return 0.0
    d_idle, d_total = idle - prev[0], total - prev[1]
    return round(100.0 * (1 - d_idle / d_total), 1) if d_total > 0 else 0.0


def _mem_percent():
    info = {}
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                key, *rest = line.replace(":", "").split()
                if rest:
                    info[key] = int(rest[0])
    except Exception:
        return 0.0
    total = info.get("MemTotal", 0)
    if not total:
        return 0.0
    used = total - info.get("MemAvailable", info.get("MemFree", 0))
    return round(100.0 * used / total, 1)


def _vcgencmd(*args):
    try:
        out = subprocess.run(["vcgencmd", *args], capture_output=True, text=True,
                             timeout=2).stdout.strip()
    except Exception:
        return None
    return out.split("=")[-1] if "=" in out else out


def _metrics():
    """ЦП, ОЗУ, температура и частота видеоядра — без внешних зависимостей."""
    result = {"cpu": _cpu_percent(), "ram": _mem_percent(), "temp": None,
              "gpu_mhz": None, "volts": None, "load": None}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as handle:
            result["temp"] = round(int(handle.read().strip()) / 1000, 1)
    except Exception:
        pass
    gpu = _vcgencmd("measure_clock", "v3d")
    if gpu and gpu.isdigit():
        result["gpu_mhz"] = round(int(gpu) / 1_000_000)
    volts = _vcgencmd("measure_volts", "core")
    if volts:
        try:
            result["volts"] = float(volts.rstrip("V"))
        except ValueError:
            pass
    try:
        result["load"] = round(os.getloadavg()[0], 2)
    except Exception:
        pass
    return result


PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>ЧайОК</title>
<style>
 :root { color-scheme: dark; }
 body { margin:0; padding:16px; font:16px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif;
        background:#0b0e14; color:#cfd8e6; }
 h1 { font-size:20px; margin:0 0 4px; color:#00b4ff; }
 .sub { color:#6b7c93; font-size:13px; margin-bottom:14px; }
 .card { background:#141a24; border:1px solid #1e2a3a; border-radius:12px;
         padding:14px; margin-bottom:12px; }
 .row { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end; }
 button { background:#0d5f8f; color:#fff; border:0; border-radius:9px;
          padding:10px 14px; font-size:15px; }
 button.alt { background:#1d2734; }
 button.red { background:#8f2d2d; }
 button:active { opacity:.75; }
 .status { font-size:14px; color:#8fa4bd; }
 .big { font-size:26px; font-weight:600; color:#e8f0fa; }
 input, select, textarea { background:#0f1520; color:#cfd8e6; border:1px solid #24303f;
        border-radius:8px; padding:8px; font-size:15px; width:100%; box-sizing:border-box; }
 textarea { min-height:110px; }
 label { font-size:13px; color:#8fa4bd; display:block; margin:10px 0 4px; }
 .field { flex:1; min-width:130px; }
 .ok { color:#7ee0a5; }
 .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
 .metric { background:#0f1520; border:1px solid #24303f; border-radius:9px;
           padding:8px 9px; min-width:0; }
 .mhead { display:flex; justify-content:space-between; align-items:baseline; gap:6px;
          font-size:12px; color:#8fa4bd; }
 .mhead span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
 .mhead b { font-size:15px; color:#e8f0fa; font-weight:600; white-space:nowrap; }
 .spark { display:block; width:100%; height:40px; margin-top:4px; }
 .spark polyline { fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
</style>
</head>
<body>
<h1>ЧайОК</h1>
<div class="sub" id="sub">подключаюсь…</div>

<div class="card">
  <div class="row" style="justify-content:space-between;align-items:baseline">
    <div class="status">Железо</div>
    <div class="status" id="hw_extra">—</div>
  </div>
  <div class="grid">
    <div class="metric"><div class="mhead"><span>ЦП</span><b id="m_cpu">—</b></div>
      <svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none"><polyline id="p_cpu" points=""/></svg></div>
    <div class="metric"><div class="mhead"><span>ОЗУ</span><b id="m_ram">—</b></div>
      <svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none"><polyline id="p_ram" points=""/></svg></div>
    <div class="metric"><div class="mhead"><span>Температура</span><b id="m_temp">—</b></div>
      <svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none"><polyline id="p_temp" points=""/></svg></div>
    <div class="metric"><div class="mhead"><span>Видеоядро</span><b id="m_gpu">—</b></div>
      <svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none"><polyline id="p_gpu" points=""/></svg></div>
  </div>
</div>

<div class="card">
  <div class="row" style="justify-content:space-between">
    <div><div class="status">Радио</div><div class="big" id="station">—</div></div>
    <div class="status" id="timer"></div>
  </div>
  <div class="row" style="margin-top:10px">
    <button onclick="api('radio',{action:'start'})">Включить</button>
    <button onclick="api('radio',{action:'next'})">Следующая</button>
    <button class="alt" onclick="api('radio',{action:'stop'})">Выключить</button>
  </div>
  <div class="row" style="margin-top:10px">
    <select id="stations"></select>
    <button onclick="playSelected()">Играть</button>
  </div>
</div>

<div class="card">
  <label>Громкость</label>
  <div class="row">
    <button class="alt" onclick="api('volume',{step:-10})">−</button>
    <div class="big" id="volume" style="min-width:70px;text-align:center">—</div>
    <button class="alt" onclick="api('volume',{step:10})">+</button>
    <button class="alt" onclick="api('volume',{value:100})">На всю</button>
  </div>
</div>

<div class="card">
  <label>Таймер</label>
  <div class="row">
    <button onclick="api('timer',{action:'start',minutes:5})">5 мин</button>
    <button onclick="api('timer',{action:'start',minutes:15})">15 мин</button>
    <button class="alt" onclick="api('timer',{action:'stop'})">Стоп</button>
  </div>
</div>

<div class="card">
  <label>Будильник</label>
  <div class="row">
    <input id="alarm_time" type="time" step="60" style="flex:1">
    <select id="alarm_level" style="flex:1">
      <option value="мягкий">мягкий</option>
      <option value="средний">средний</option>
      <option value="жёсткий">жёсткий</option>
    </select>
  </div>
  <div class="row" style="margin-top:10px">
    <button onclick="saveAlarm()">Сохранить</button>
    <button class="alt" onclick="api('alarm',{enabled:false})">Выключить</button>
  </div>
  <div class="status" id="alarm_state" style="margin-top:8px"></div>
</div>

<div class="card">
  <div class="status">Голос</div>
  <label>Модель (голос)</label>
  <select id="v_model"></select>
  <div class="row">
    <div class="field"><label>Темп речи</label>
      <input id="v_len" type="number" step="0.01" min="0.7" max="1.5"></div>
    <div class="field"><label>Пауза между фразами, с</label>
      <input id="v_sil" type="number" step="0.05" min="0" max="1.5"></div>
  </div>
  <label>Характер и правила ответов</label>
  <textarea id="v_prompt"></textarea>
</div>

<div class="card">
  <div class="status">Слух</div>
  <label>Слова-активаторы (через запятую)</label>
  <input id="v_wake">
  <div class="row">
    <div class="field"><label>Тишина до конца команды, с</label>
      <input id="v_silence" type="number" step="0.1" min="0.5" max="10"></div>
    <div class="field"><label>Окно продолжения, с</label>
      <input id="v_follow" type="number" step="1" min="0" max="30"></div>
  </div>
</div>

<div class="card">
  <div class="status">Ответы</div>
  <div class="row">
    <div class="field"><label>Реплик в памяти</label>
      <input id="v_hist" type="number" step="1" min="0" max="20"></div>
    <div class="field"><label>Ждать ответ, с</label>
      <input id="v_read" type="number" step="10" min="10" max="600"></div>
  </div>
</div>

<div class="card">
  <div class="status">Погода</div>
  <label>Город (для ответа)</label>
  <input id="v_city">
  <div class="row">
    <div class="field"><label>Широта</label>
      <input id="v_lat" type="number" step="0.0001"></div>
    <div class="field"><label>Долгота</label>
      <input id="v_lon" type="number" step="0.0001"></div>
  </div>
</div>

<div class="card">
  <div class="status">Панель</div>
  <div class="row">
    <div class="field"><label>Порт</label>
      <input id="v_port" type="number" min="1024" max="65535"></div>
    <div class="field"><label>Пароль (пусто — без пароля)</label>
      <input id="v_pw" type="password" autocomplete="new-password"></div>
  </div>
  <div class="row" style="margin-top:12px">
    <button onclick="saveSettings()">Сохранить настройки</button>
    <button class="red" onclick="restartApp()">Перезапустить ЧайОК</button>
  </div>
  <div class="status" id="cfg_state" style="margin-top:8px"></div>
</div>

<div class="card">
  <div class="status">Обновление</div>
  <div class="row" style="margin-top:8px">
    <button onclick="runUpdate()">Обновить из GitHub</button>
  </div>
  <pre id="upd_log" style="background:#0f1520;border:1px solid #24303f;border-radius:8px;
       padding:8px;font-size:12px;max-height:200px;overflow:auto;margin:10px 0 0"></pre>
</div>

<script>
const token = new URLSearchParams(location.search).get('token') || '';
let cfg = null;

async function api(path, body) {
  const res = await fetch('/api/' + path, {
    method: body ? 'POST' : 'GET',
    headers: {'Content-Type': 'application/json', 'X-Token': token},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) { alert('Ошибка: ' + res.status); return null; }
  return res.json();
}

function set(id, value) { document.getElementById(id).value = value; }
function val(id) { return document.getElementById(id).value; }
function num(id, fallback) { const v = parseFloat(val(id)); return isNaN(v) ? fallback : v; }

async function refresh() {
  const s = await api('status');
  if (!s) return;
  document.getElementById('station').textContent = s.radio.active ? s.radio.station : 'выключено';
  document.getElementById('volume').textContent = s.volume + '%';
  document.getElementById('timer').textContent = s.timer.text || '';
  document.getElementById('sub').textContent = (s.app_status || 'работает');
  const a = s.alarm;
  document.getElementById('alarm_state').textContent = a.enabled
    ? ('включён на ' + String(a.hour).padStart(2,'0') + ':' + String(a.minute).padStart(2,'0') +
       ', ' + a.level + ', ' + (a.sound || ''))
    : 'выключен';
  if (!document.getElementById('alarm_time').value) {
    document.getElementById('alarm_time').value =
      String(a.hour).padStart(2,'0') + ':' + String(a.minute).padStart(2,'0');
  }
  const sel = document.getElementById('stations');
  if (!sel.dataset.filled && s.radio.stations.length) {
    sel.innerHTML = s.radio.stations.map((n,i) => `<option value="${i}">${n}</option>`).join('');
    sel.dataset.filled = '1';
    sel.value = s.radio.index;
  }
}

async function loadVoices() {
  const data = await api('voices');
  const sel = document.getElementById('v_model');
  const list = (data && data.voices) || [];
  sel.innerHTML = list.map(p => {
    const name = p.split('/').pop().replace('.onnx','');
    return `<option value="${p}">${name}</option>`;
  }).join('');
}

async function loadSettings() {
  cfg = await api('config');
  if (!cfg) return;
  set('v_model', cfg.voice.model);
  set('v_len', cfg.voice.length_scale);
  set('v_sil', cfg.voice.sentence_silence);
  set('v_prompt', cfg.llm.system_prompt);
  set('v_hist', cfg.llm.history_limit);
  set('v_read', cfg.llm.timeout_read);
  set('v_wake', (cfg.voice_input.wake_words || []).join(', '));
  set('v_silence', cfg.voice_input.command_silence);
  set('v_follow', cfg.voice_input.followup_seconds);
  set('v_city', cfg.weather.city);
  set('v_lat', cfg.weather.latitude);
  set('v_lon', cfg.weather.longitude);
  set('v_port', cfg.web.port);
  set('v_pw', cfg.web.password || '');
  document.getElementById('cfg_state').textContent = '';
}

async function saveSettings() {
  if (!cfg) return;
  const updated = JSON.parse(JSON.stringify(cfg));
  updated.voice.model = val('v_model');
  updated.voice.length_scale = num('v_len', 1.05);
  updated.voice.sentence_silence = num('v_sil', 0.35);
  updated.llm.system_prompt = val('v_prompt');
  updated.llm.history_limit = Math.round(num('v_hist', 4));
  updated.llm.timeout_read = Math.round(num('v_read', 180));
  updated.voice_input.wake_words = val('v_wake').split(',')
      .map(w => w.trim().toLowerCase()).filter(w => w.length > 0);
  updated.voice_input.command_silence = num('v_silence', 2.5);
  updated.voice_input.followup_seconds = num('v_follow', 5);
  updated.weather.city = val('v_city');
  updated.weather.latitude = num('v_lat', 55.7558);
  updated.weather.longitude = num('v_lon', 37.6173);
  updated.web.port = Math.round(num('v_port', 8000));
  updated.web.password = val('v_pw');

  const saved = await api('config', updated);
  if (saved) {
    cfg = saved;
    document.getElementById('cfg_state').textContent =
      'сохранено — нажмите «Перезапустить ЧайОК», чтобы применить';
  } else {
    document.getElementById('cfg_state').textContent = 'не сохранилось';
  }
}

async function playSelected() {
  await api('radio', {action: 'start', station: Number(document.getElementById('stations').value)});
  refresh();
}

async function saveAlarm() {
  const t = document.getElementById('alarm_time').value.split(':');
  await api('alarm', {
    hour: Number(t[0]), minute: Number(t[1]),
    level: document.getElementById('alarm_level').value, enabled: true,
  });
  refresh();
}

async function restartApp() {
  if (!confirm('Перезапустить ЧайОК?')) return;
  const res = await api('restart', {});
  document.getElementById('cfg_state').textContent = res ? 'перезапускаю…' : 'не вышло';
}

let updTimer = null;

async function runUpdate() {
  if (!confirm('Забрать обновление из GitHub и перезапустить?')) return;
  const r = await api('update', {});
  if (!r) return;
  document.getElementById('upd_log').textContent = 'запущено…';
  if (updTimer) clearInterval(updTimer);
  updTimer = setInterval(pollUpdate, 2000);
  pollUpdate();
}

async function pollUpdate() {
  const box = document.getElementById('upd_log');
  try {
    const res = await fetch('/api/update/log', {headers: {'X-Token': token}});
    if (!res.ok) throw new Error('нет ответа');
    const data = await res.json();
    box.textContent = data.log || '…';
    box.scrollTop = box.scrollHeight;
    if (!data.running && updTimer) { clearInterval(updTimer); updTimer = null; }
  } catch (e) {
    box.textContent += '\\n… панель недоступна, ждём перезапуска';
  }
}

loadVoices().then(loadSettings);
refresh();
setInterval(refresh, 3000);

const HW_LEN = 60;
const HW = {cpu: [], ram: [], temp: [], gpu: []};
const HW_RANGE = {cpu: [0, 100], ram: [0, 100], temp: [30, 85], gpu: [0, 700]};
const HW_COLOR = {cpu: '#00b4ff', ram: '#7ee0a5', temp: '#ff8a5b', gpu: '#c084fc'};

function hwPush(arr, value) {
  arr.push(value);
  if (arr.length > HW_LEN) arr.shift();
}

function hwDraw(key) {
  const [lo, hi] = HW_RANGE[key];
  const arr = HW[key];
  const span = Math.max(arr.length - 1, 1);
  const pts = arr.map((v, i) => {
    const x = (100 * i) / span;
    const k = Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
    return x.toFixed(1) + ',' + (32 - 30 * k).toFixed(1);
  }).join(' ');
  const line = document.getElementById('p_' + key);
  line.setAttribute('points', pts);
  line.setAttribute('stroke', HW_COLOR[key]);
}

async function pollHw() {
  try {
    const res = await fetch('/api/metrics', {headers: {'X-Token': token}});
    if (!res.ok) return;
    const m = await res.json();
    hwPush(HW.cpu, m.cpu);
    hwPush(HW.ram, m.ram);
    hwPush(HW.temp, m.temp == null ? 30 : m.temp);
    hwPush(HW.gpu, m.gpu_mhz == null ? 0 : m.gpu_mhz);
    ['cpu', 'ram', 'temp', 'gpu'].forEach(hwDraw);
    document.getElementById('m_cpu').textContent = m.cpu.toFixed(0) + '%';
    document.getElementById('m_ram').textContent = m.ram.toFixed(0) + '%';
    document.getElementById('m_temp').textContent = m.temp == null ? '—' : m.temp.toFixed(1) + '°';
    document.getElementById('m_gpu').textContent = m.gpu_mhz == null ? '—' : m.gpu_mhz + ' МГц';
    const parts = [];
    if (m.load != null) parts.push('load ' + m.load);
    if (m.volts != null) parts.push(m.volts.toFixed(3) + ' В');
    document.getElementById('hw_extra').textContent = parts.join(' · ') || '—';
  } catch (e) { /* панель могла уйти в перезапуск */ }
}

pollHw();
setInterval(pollHw, 2000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ChayOKWeb/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, ensure_ascii=False))

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if not _authorized(self):
            self._send(401, "нужен пароль: ?token=...", "text/plain")
            return
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html")
            return
        if path == "/api/status":
            self._json(_status())
            return
        if path == "/api/metrics":
            self._json(_metrics())
            return
        if path == "/api/config":
            self._json(config.as_dict())
            return
        if path == "/api/voices":
            files = sorted(glob.glob(os.path.join(PIPER_DIR, "*.onnx")))
            self._json({"voices": files})
            return
        if path == "/api/update/log":
            lines = []
            try:
                with open(UPDATE_LOG, "r", encoding="utf-8", errors="replace") as handle:
                    lines = handle.read().splitlines()[-40:]
            except FileNotFoundError:
                pass
            running = subprocess.run(["pgrep", "-f", "update.sh"],
                                     capture_output=True).returncode == 0
            self._json({"running": running, "log": "\n".join(lines)})
            return
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not _authorized(self):
            self._json({"error": "unauthorized"}, 401)
            return
        data = self._body()

        try:
            if path == "/api/radio":
                action = data.get("action", "start")
                if action == "stop":
                    self._json({"result": radio_mod.player.stop()})
                elif action == "next":
                    name = radio_mod.player.next_station()
                    self._json({"result": f"Станция: {name}" if name else "не вышло"})
                else:
                    station = data.get("station")
                    name = radio_mod.player.start(station if isinstance(station, int) else None)
                    self._json({"result": f"Включаю {name}" if name else "не вышло"})
                return

            if path == "/api/timer":
                if data.get("action") == "stop":
                    self._json({"result": timer_mod.stop()})
                else:
                    seconds = int(data.get("seconds") or int(data.get("minutes", 5)) * 60)
                    timer_mod.start(seconds, "веб-панель")
                    self._json({"result": f"Таймер на {seconds // 60} мин" if seconds >= 60
                                else f"Таймер на {seconds} с"})
                return

            if path == "/api/alarm":
                current = alarm.load_alarm()
                self._json(alarm.save_alarm(
                    int(data.get("hour", current["hour"])),
                    int(data.get("minute", current["minute"])),
                    data.get("level", current.get("level", "средний")),
                    enabled=bool(data.get("enabled", True)),
                    sound=data.get("sound", current.get("sound")),
                ))
                return

            if path == "/api/volume":
                if "value" in data:
                    value = float(data["value"]) / 100.0
                else:
                    value = volume.load() + float(data.get("step", 10)) / 100.0
                value = max(0.0, min(1.0, value))
                volume.save(value)
                if radio_mod.player.active():
                    radio_mod.player.set_volume(value)
                self._json({"volume": volume.percent()})
                return

            if path == "/api/config":
                self._json(config.save(data))
                return

            if path == "/api/update":
                log_handle = open(UPDATE_LOG, "wb")
                subprocess.Popen(["bash", os.path.join(BASE_DIR, "update.sh")],
                                 stdout=log_handle, stderr=subprocess.STDOUT,
                                 start_new_session=True)
                log_handle.close()
                self._json({"result": "обновление запущено"})
                return

            if path == "/api/restart":
                if _restart_callback:
                    _restart_callback()
                    self._json({"result": "перезапуск"})
                else:
                    self._json({"error": "перезапуск недоступен"}, 500)
                return
        except Exception as e:
            self._json({"error": str(e)}, 500)
            return

        self._send(404, "not found", "text/plain")


def start(status_provider=None, restart_callback=None):
    """Поднимает панель в фоновом потоке (если включена в конфиге)."""
    global _status_provider, _restart_callback
    if not config.get("web", "enabled", default=True):
        print("веб-панель выключена в конфиге")
        return None

    _status_provider = status_provider
    _restart_callback = restart_callback

    host = config.get("web", "host", default="0.0.0.0")
    port = int(config.get("web", "port", default=8000))

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except Exception as e:
        print(f"веб-панель не поднялась на {host}:{port}: {e}")
        return None

    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Веб-панель: http://{host}:{port}")
    return server
