"""Веб-панель ЧайОК: статус, радио, будильник, таймер, громкость и настройки.

Без внешних зависимостей — стандартная библиотека. Открывается с телефона
в домашней сети: http://<ip>:8000
"""

import json
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


def _password():
    return str(config.get("web", "password", default="") or "")


def _authorized(handler):
    password = _password()
    if not password:
        return True
    header = handler.headers.get("X-Token", "")
    if header == password:
        return True
    query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    return query.get("token", [""])[0] == password


def _status():
    stations = radio_mod.player.stations
    alarm_data = alarm.load_alarm()
    result = {
        "ok": True,
        "radio": {
            "active": radio_mod.player.active(),
            "station": radio_mod.player.station_name(),
            "index": radio_mod.player.index,
            "stations": [s["name"] for s in stations],
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
 .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
 button { background:#0d5f8f; color:#fff; border:0; border-radius:9px;
          padding:10px 14px; font-size:15px; }
 button.alt { background:#1d2734; }
 button.red { background:#8f2d2d; }
 button:active { opacity:.75; }
 .status { font-size:14px; color:#8fa4bd; }
 .big { font-size:26px; font-weight:600; color:#e8f0fa; }
 input, select, textarea { background:#0f1520; color:#cfd8e6; border:1px solid #24303f;
        border-radius:8px; padding:8px; font-size:15px; }
 textarea { width:100%; box-sizing:border-box; min-height:220px; font-family:monospace;
            font-size:13px; }
 label { font-size:13px; color:#8fa4bd; display:block; margin:6px 0 2px; }
 .ok { color:#7ee0a5; } .warn { color:#ffb347; }
</style>
</head>
<body>
<h1>ЧайОК</h1>
<div class="sub" id="sub">подключаюсь…</div>

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
    <select id="stations" style="flex:1"></select>
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
    <input id="alarm_time" type="time" step="60">
    <select id="alarm_level">
      <option value="мягкий">мягкий</option>
      <option value="средний">средний</option>
      <option value="жёсткий">жёсткий</option>
    </select>
    <button onclick="saveAlarm()">Сохранить</button>
    <button class="alt" onclick="api('alarm',{enabled:false})">Выключить</button>
  </div>
  <div class="status" id="alarm_state" style="margin-top:8px"></div>
</div>

<div class="card">
  <label>Настройки (config.json)</label>
  <textarea id="cfg" spellcheck="false"></textarea>
  <div class="row" style="margin-top:10px">
    <button onclick="saveConfig()">Сохранить</button>
    <button class="alt" onclick="loadConfig()">Перечитать</button>
    <button class="red" onclick="restartApp()">Перезапустить ЧайОК</button>
  </div>
  <div class="status" id="cfg_state" style="margin-top:8px"></div>
</div>

<script>
const token = new URLSearchParams(location.search).get('token') || '';
async function api(path, body) {
  const res = await fetch('/api/' + path, {
    method: body ? 'POST' : 'GET',
    headers: {'Content-Type': 'application/json', 'X-Token': token},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) { alert('Ошибка: ' + res.status); return null; }
  return res.json();
}
async function refresh() {
  const s = await api('status');
  if (!s) return;
  document.getElementById('station').textContent = s.radio.active ? s.radio.station : 'выключено';
  document.getElementById('volume').textContent = s.volume + '%';
  document.getElementById('timer').textContent = s.timer.text || '';
  document.getElementById('sub').textContent =
    (s.app_status ? s.app_status : 'работает') + (s.app_version ? ' · ' + s.app_version : '');
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
  if (!sel.dataset.filled) {
    sel.innerHTML = s.radio.stations.map((n,i) => `<option value="${i}">${n}</option>`).join('');
    sel.dataset.filled = '1';
    sel.value = s.radio.index;
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
async function loadConfig() {
  const cfg = await api('config');
  document.getElementById('cfg').value = JSON.stringify(cfg, null, 2);
}
async function saveConfig() {
  const el = document.getElementById('cfg');
  let parsed;
  try { parsed = JSON.parse(el.value); }
  catch (e) { document.getElementById('cfg_state').textContent = 'JSON с ошибкой: ' + e.message; return; }
  const res = await api('config', parsed);
  document.getElementById('cfg_state').textContent = res ? 'сохранено' : 'не сохранилось';
  if (res) el.value = JSON.stringify(res, null, 2);
}
async function restartApp() {
  if (!confirm('Перезапустить ЧайОК?')) return;
  const res = await api('restart', {});
  document.getElementById('cfg_state').textContent = res ? 'перезапускаю…' : 'не вышло';
}
loadConfig();
refresh();
setInterval(refresh, 3000);
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
        if path == "/api/config":
            self._json(config.as_dict())
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
