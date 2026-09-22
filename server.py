"""
Локальный сервер расписания КубГТУ.

Отдаёт:
  GET /                          -> страница расписания (static/index.html)
  GET /api/faculties?foe=ofo     -> список институтов/факультетов
  GET /api/groups?fak_id=&kurs=&foe=ofo -> список групп
  GET /api/schedule?gr=&fak_id=&kurs=&foe=ofo&ugod=&semestr= -> расписание группы

Запуск (Termux):
    pkg install python
    pip install -r requirements.txt
    python server.py
Затем открыть в браузере телефона: http://127.0.0.1:8787
(с другого устройства в той же Wi-Fi сети - по локальному IP телефона,
см. README.md)
"""
import os
import time
from flask import Flask, request, jsonify, send_from_directory

import scraper

app = Flask(__name__, static_folder="static", static_url_path="")

_CACHE = {}


def cached(key, ttl_seconds, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit["ts"] < ttl_seconds:
        return hit["data"]
    data = fn()
    _CACHE[key] = {"ts": now, "data": data}
    return data


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/faculties")
def api_faculties():
    foe = request.args.get("foe", "ofo")
    try:
        data = cached(f"faculties:{foe}", 6 * 3600, lambda: scraper.get_faculties(foe))
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.get("/api/groups")
def api_groups():
    fak_id = request.args.get("fak_id")
    kurs = request.args.get("kurs")
    foe = request.args.get("foe", "ofo")
    if not fak_id or not kurs:
        return jsonify({"ok": False, "error": "fak_id и kurs обязательны"}), 400
    try:
        key = f"groups:{foe}:{fak_id}:{kurs}"
        data = cached(key, 3600, lambda: scraper.get_groups(fak_id, kurs, foe))
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.get("/api/schedule")
def api_schedule():
    gr = request.args.get("gr")
    fak_id = request.args.get("fak_id")
    kurs = request.args.get("kurs")
    foe = request.args.get("foe", "ofo")
    ugod = request.args.get("ugod")
    semestr = request.args.get("semestr")
    if not gr:
        return jsonify({"ok": False, "error": "gr обязателен"}), 400
    try:
        key = f"schedule:{foe}:{gr}:{ugod}:{semestr}"
        data = cached(
            key, 1800,
            lambda: scraper.get_schedule(gr, fak_id=fak_id, kurs=kurs, foe=foe, ugod=ugod, semestr=semestr),
        )
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


if __name__ == "__main__":
    # PORT задаёт хостинг (Render и т.п.); локально/в Termux по умолчанию 8787
    port = int(os.environ.get("PORT", 8787))
    app.run(host="0.0.0.0", port=port)
