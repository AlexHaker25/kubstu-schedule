"""
Скрапер расписания КубГТУ с elkaf.kubstu.ru (тот же источник, что использует
официальный ИнфоКиоск k2.kubstu.ru/tt).

Никакого скрытого API нет - обычные GET-запросы, ответ - HTML-страница с
раскрывающимися панелями (Bootstrap accordion). Здесь этот HTML разбирается
в обычный JSON.
"""
import re
import requests
import urllib3
from bs4 import BeautifulSoup
from datetime import date

# Сайт КубГТУ использует сертификат российского УЦ, которого нет в стандартном
# наборе доверенных сертификатов Python. Данные публичные (расписание),
# поэтому отключаем проверку сертификата вместо того чтобы тащить отдельный
# бандл сертификатов Минцифры.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://elkaf.kubstu.ru/timetable/default"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

TYPE_MAP = {
    "Лекции": "lecture",
    "Практические занятия": "practice",
    "Лабораторные занятия": "lab",
}

DAY_ORDER = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def default_period():
    """Повторяет логику timetable_tgbot: определяет текущий учебный год/семестр."""
    today = date.today()
    ugod = today.year - (0 if today.month >= 7 else 1)
    semestr = 1 if today.month >= 7 else 2
    return ugod, semestr


def _get(path, params, timeout=15):
    r = requests.get(f"{BASE}/{path}", params={**params, "iskiosk": 1}, headers=HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def get_faculties(foe="ofo"):
    """Список факультетов/институтов. foe: 'ofo' или 'zfo'."""
    path = f"time-table-student-{foe}"
    soup = _get(path, {})
    select = soup.find("select", {"name": "fak_id"})
    out = []
    for opt in select.find_all("option"):
        val = opt.get("value", "").strip()
        if not val:
            continue
        out.append({"id": val, "name": opt.text.strip()})
    return out


def get_groups(fak_id, kurs, foe="ofo"):
    """Список групп для данного факультета и курса."""
    path = f"time-table-student-{foe}"
    ugod, semestr = default_period()
    soup = _get(path, {"fak_id": fak_id, "kurs": kurs, "gr": "", "ugod": ugod, "semestr": semestr})
    select = soup.find("select", {"name": "gr"})
    out = []
    for opt in select.find_all("option"):
        val = opt.get("value", "").strip()
        if not val:
            continue
        out.append(val)
    return out


def _parse_lesson_panel(panel):
    """Разбирает один panel лекции/пары."""
    heading_span = panel.select_one(".panel-heading span")
    title = heading_span.get_text(strip=True) if heading_span else ""

    m = re.match(r"(\d+)\s*пара\s*\(([^)]+)\)\s*/\s*(.+?)\s*/\s*(.+)", title)
    if not m:
        return None
    num, time_range, subject, type_ru = m.groups()
    start, end = [t.strip() for t in time_range.split("-")]

    body = panel.select_one(".panel-body")
    fields = {}
    if body:
        for p in body.find_all("p"):
            strong = p.find("strong")
            if not strong:
                continue
            label = strong.get_text(strip=True).rstrip(":")
            value = p.get_text(strip=True)
            value = value[len(strong.get_text(strip=True)):].strip()
            fields[label] = value

    return {
        "num": int(num),
        "start": start,
        "end": end,
        "subject": subject.strip(),
        "type": TYPE_MAP.get(type_ru.strip(), "practice"),
        "typeLabel": type_ru.strip(),
        "teacher": fields.get("Преподаватель", "").strip(),
        "room": fields.get("Аудитория", "").strip(),
        "period": fields.get("Период", "").strip(),
        "isStream": fields.get("В лекционном потоке", "").strip().lower() == "да",
        "percentOfGroup": fields.get("Процент группы", "").strip(),
        "note": fields.get("Примечание", "").strip(),
    }


def _parse_day_panel(panel):
    heading = panel.select_one(".panel-heading span")
    day_name = heading.get_text(strip=True) if heading else ""

    lessons = []
    body = panel.select_one(":scope > .panel-collapse > .panel-body")
    if body:
        for lesson_panel in body.find_all("div", class_="panel", recursive=False):
            lesson = _parse_lesson_panel(lesson_panel)
            if lesson:
                lessons.append(lesson)
    lessons.sort(key=lambda l: l["num"])
    return day_name, lessons


def _parse_week_panel(panel):
    heading = panel.select_one(".panel-heading strong")
    week_title = heading.get_text(strip=True) if heading else ""
    is_even = "чет" in week_title.lower() and "нечет" not in week_title.lower()

    days = {}
    body = panel.select_one(":scope > .panel-collapse > .panel-body")
    if body:
        for day_panel in body.find_all("div", class_="panel", recursive=False):
            day_name, lessons = _parse_day_panel(day_panel)
            if day_name:
                days[day_name] = lessons

    # На случай если в HTML нет всех 7 дней - заполняем отсутствующие пустым списком
    for d in DAY_ORDER:
        days.setdefault(d, [])

    return "even" if is_even else "odd", days


def get_schedule(gr, fak_id=None, kurs=None, foe="ofo", ugod=None, semestr=None):
    """
    Возвращает структурированное расписание группы:
    {
      "group": "...",
      "period": {"ugod": 2026, "semestr": 1, "studyPeriod": "31.08.2026 - 27.12.2026", "weekParityNow": "even"},
      "availablePeriods": [{"label": "...", "ugod":.., "semestr":..}, ...],
      "schedule": {"odd": {day: [lessons]}, "even": {day: [lessons]}}
    }
    """
    if ugod is None or semestr is None:
        ugod, semestr = default_period()

    path = f"time-table-student-{foe}"
    params = {"gr": gr, "ugod": ugod, "semestr": semestr}
    if fak_id is not None:
        params["fak_id"] = fak_id
    if kurs is not None:
        params["kurs"] = kurs

    soup = _get(path, params)

    schedule = {"odd": {}, "even": {}}
    for ned_box in soup.select(".ned-box"):
        week_panel = ned_box.find("div", class_="panel", recursive=False)
        if not week_panel:
            continue
        parity, days = _parse_week_panel(week_panel)
        schedule[parity] = days

    # Инфо о периоде занятий и текущей чётности недели
    info_p = soup.find_all("p")
    study_period = ""
    week_parity_now = None
    for p in info_p:
        txt = p.get_text(" ", strip=True)
        if txt.startswith("График занятий:"):
            study_period = txt.replace("График занятий:", "").strip()
        if "Текущая неделя:" in txt:
            mm = re.search(r"Текущая неделя:\s*(четная|нечетная)", txt)
            if mm:
                week_parity_now = "even" if mm.group(1) == "четная" else "odd"

    # Доступные учебные периоды (кнопки года/семестра)
    available = []
    for a in soup.select("a.btn-schedule, a.btn-primary"):
        href = a.get("href", "")
        mm = re.search(r"ugod=(\d+)&semestr=(\d)", href) or re.search(r"ugod=(\d+)&amp;semestr=(\d)", href)
        if mm:
            available.append({
                "label": a.get_text(strip=True),
                "ugod": int(mm.group(1)),
                "semestr": int(mm.group(2)),
            })

    return {
        "group": gr,
        "period": {
            "ugod": int(ugod),
            "semestr": int(semestr),
            "studyPeriod": study_period,
            "weekParityNow": week_parity_now,
        },
        "availablePeriods": available,
        "schedule": schedule,
    }


if __name__ == "__main__":
    # Локальный тест на сохранённом заранее HTML (без сети) - см. test_offline.py
    pass
