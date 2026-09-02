import json
import os
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

STATE_FILE = "air_state.json"


def _now_kyiv():
    return datetime.now(ZoneInfo("Europe/Kyiv"))


def load_state() -> dict:
    empty = {
        "kyiv_alert": False,
        "oblast_alert": False,
        "initialized": False,
        "kyiv_since": 0,
        "oblast_since": 0,
        "last_end_at": 0,
        "last_post_at": 0,
        "last_event": "",
        "kyiv_end_sent": False,
        "oblast_end_sent": False,
    }
    if not os.path.exists(STATE_FILE):
        return empty
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        empty.update(data)
        return empty
    except Exception:
        return empty


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

def _fmt_duration(started_ts: float) -> str:
    if not started_ts:
        return ""
    sec = max(0, int(time.time() - started_ts))
    hours, rem = divmod(sec, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} год {minutes} хв"
    if hours:
        return f"{hours} год"
    if minutes:
        return f"{minutes} хв"
    return "кілька хвилин"


def _is_night() -> bool:
    hour = _now_kyiv().hour
    return hour >= 22 or hour < 6


def _minutes_since_end(state: dict) -> float:
    ts = state.get("last_end_at") or 0
    if not ts:
        return 999
    return (time.time() - ts) / 60


KYIV_OFF_OBLAST_ON = [
    "Відбій у Києві.\n\nНебо чисте.",
    "Сирена в столиці затихла.\n\nНебо чисте.",
    "Київ — відбій.\n\nМожна видихнути.",
    "Тиша в Києві.\n\nНебо чисте.",
    "Відбій.\n\nНебо чисте. Бережіть себе.",
]

OBLAST_OFF_KYIV_ON = [
    "Київ ще під тривогою.\n\nПройдіть в укриття.",
]

FULL_CLEAR_DAY = [
    "Відбій у Києві.\n\nНебо чисте.",
    "Сирена затихла.\n\nМожна з укриття. Без героїзму на вулиці — спочатку озирніться.",
    "Київ — відбій.\n\nКава ще тепла. Небо чисте.",
    "Тиша.\n\nХто в метро — можна нагору. Хто в коридорі — теж.",
    "Відбій.\n\nНебо чисте. Телефон можна прибрати в кишеню.",
    "Столиця без сирени.\n\nНе розслабляйтесь на уламках. Просто живіть далі.",
    "Відбій у Києві.\n\nЛіфт знову можна. Небо чисте.",
    "Сирена вимкнулась.\n\nДень не скасовується.",
    "Київ тихо.\n\nХто встиг налякатись — нормально. Хто ні — теж.",
    "Відбій.\n\nНебо чисте. Тварин вигуляти можна, голосно не треба.",
    "Столиця відпустила.\n\nПрацюйте, якщо працюється. Відпочиньте, якщо ні.",
    "Відбій у Києві.\n\nКоридор можна залишити. Стіни подякують.",
    "Сирена стихла.\n\nНебо чисте. Новини читайте в нас, не в чатах під’їзду.",
    "Київ — відбій.\n\nКоротко і по суті: небезпека знята.",
    "Відбій.\n\nНебо чисте. Бережіть себе без пафосу.",
]

FULL_CLEAR_NIGHT = [
    "Відбій у Києві.\n\nВідбились. Спокійної ночі.",
    "Сирена затихла.\n\nСпати можна. Будильник хай буде не сирена.",
    "Київ — відбій.\n\nВідбились. Доброї ночі.",
    "Тиша.\n\nХто не спав — тепер можна. Спокійної ночі.",
    "Відбій.\n\nНебо чисте. Світло в коридорі можна гасити.",
    "Столиця тихо.\n\nВідбились. Спати пора.",
    "Відбій у Києві.\n\nКотам теж відбій. Спокійної ночі.",
    "Сирена вимкнулась.\n\nНіч ще є. Використайте її на сон.",
    "Київ відпустив.\n\nВідбились. Не сидіть до ранку в стрічці.",
    "Відбій.\n\nНебо чисте. Подушка важливіша за мапу.",
    "Столиця без сирени.\n\nВідбились. Доброї ночі.",
    "Відбій у Києві.\n\nЛіфт, ліжко, тиша. Спокійної ночі.",
    "Сирена стихла.\n\nХто в укритті — нагору і спати.",
    "Київ — відбій.\n\nКоротко: ніч наша. Спати.",
    "Відбій.\n\nВідбились. Світанок хай буде без сирени.",
]

REPEAT_ALERT = [
    "Знову сирена. Відбій довго не пожив.",
    "Повертаємось в укриття. Так, ще раз.",
    "Повторна тривога. Короткий антракт закінчився.",
    "Знову по Києву. Відбій був розминкою.",
    "Сирена повторно. Не встигли розійтись — і правильно.",
    "Ще одна. Відбій виявився паузою, не фіналом.",
    "Повторно. Укриття ніхто не прибирав.",
    "Знову повітряна. День такий день.",
    "Сирена вдруге. Коротко видихнули — і назад.",
    "Повторна тривога. Класика, на жаль.",
    "Відбій не витримав. Знову в укриття.",
    "Ще раз. Небо передумало.",
    "Повторно по столиці. Бережіть нерви і стіни.",
    "Сирена знову. Чай можна допити вже внизу.",
    "Короткий відбій, довга зміна. Знову тривога.",
]


_ALERT_CACHE = {"at": 0.0, "data": {"kyiv": False, "oblast": False}}

_ALERT_CACHE = {"at": 0.0, "data": {"kyiv": False, "oblast": False}, "kyiv_off": 0}

def fetch_official_alerts() -> dict:
    import time

    now = time.time()
    if now - _ALERT_CACHE["at"] < 8:
        return dict(_ALERT_CACHE["data"])

    result = {"kyiv": False, "oblast": False}
    try:
        resp = requests.get("https://neptun.in.ua/api/v1/alerts", timeout=5)
        if resp.status_code != 200:
            print(f"AIR API status {resp.status_code}")
            return dict(_ALERT_CACHE["data"]) if _ALERT_CACHE["at"] else result
        data = resp.json()
    except Exception as e:
        print(f"AIR API error: {e}")
        return dict(_ALERT_CACHE["data"]) if _ALERT_CACHE["at"] else result

    items = (data.get("oblasts") or []) + (data.get("raions") or []) + (data.get("hromadas") or [])
    for item in items:
        name = (item.get("name") or "").strip().lower().replace("м.", " ").replace("місто", " ")
        oblast = (item.get("oblast") or "").strip().lower()
        key = (item.get("key") or "").strip().lower()
        blob = f"{name} {oblast} {key}"
        clean = " ".join(name.split())
        if clean in ("київ", "kyiv") or key in ("kyiv", "m.kyiv", "kyiv_city", "ua-30", "31"):
            result["kyiv"] = True
        elif "київська" in blob or "kyivska" in blob or "киевск" in blob:
            if clean not in ("київ", "kyiv"):
                result["oblast"] = True

    prev = _ALERT_CACHE["data"]
    if prev.get("kyiv") and not result["kyiv"]:
        _ALERT_CACHE["kyiv_off"] = int(_ALERT_CACHE.get("kyiv_off") or 0) + 1
        if _ALERT_CACHE["kyiv_off"] < 3:
            print("AIR hold Kyiv ON")
            result["kyiv"] = True
    else:
        _ALERT_CACHE["kyiv_off"] = 0

    _ALERT_CACHE["at"] = now
    _ALERT_CACHE["data"] = result
    print(f"AIR status kyiv={result['kyiv']} oblast={result['oblast']}")
    return dict(result)

BOTH_CLEAR_DAY = [
    "Відбій у Києві.\n\nНебо чисте.",
    "Сирена затихла.\n\nМожна з укриття. Без героїзму на вулиці — спочатку озирніться.",
    "Київ — відбій.\n\nКава ще тепла. Небо чисте.",
    "Тиша.\n\nХто в метро — можна нагору. Хто в коридорі — теж.",
    "Відбій.\n\nНебо чисте. Телефон можна прибрати в кишеню.",
    "Столиця без сирени.\n\nНе розслабляйтесь на уламках. Просто живіть далі.",
    "Відбій у Києві.\n\nЛіфт знову можна. Небо чисте.",
    "Сирена вимкнулась.\n\nДень не скасовується.",
    "Київ тихо.\n\nХто встиг налякатись — нормально. Хто ні — теж.",
    "Відбій.\n\nНебо чисте. Тварин вигуляти можна, голосно не треба.",
    "Столиця відпустила.\n\nПрацюйте, якщо працюється. Відпочиньте, якщо ні.",
    "Відбій у Києві.\n\nКоридор можна залишити. Стіни подякують.",
    "Сирена стихла.\n\nНебо чисте. Новини читайте в нас, не в чатах під’їзду.",
    "Київ — відбій.\n\nКоротко і по суті: небезпека знята.",
    "Відбій.\n\nНебо чисте. Бережіть себе без пафосу.",
]

BOTH_CLEAR_NIGHT = [
    "Відбій у Києві.\n\nВідбились. Спокійної ночі.",
    "Сирена затихла.\n\nСпати можна. Будильник хай буде не сирена.",
    "Київ — відбій.\n\nВідбились. Доброї ночі.",
    "Тиша.\n\nХто не спав — тепер можна. Спокійної ночі.",
    "Відбій.\n\nНебо чисте. Світло в коридорі можна гасити.",
    "Столиця тихо.\n\nВідбились. Спати пора.",
    "Відбій у Києві.\n\nКотам теж відбій. Спокійної ночі.",
    "Сирена вимкнулась.\n\nНіч ще є. Використайте її на сон.",
    "Київ відпустив.\n\nВідбились. Не сидіть до ранку в стрічці.",
    "Відбій.\n\nНебо чисте. Подушка важливіша за мапу.",
    "Столиця без сирени.\n\nВідбились. Доброї ночі.",
    "Відбій у Києві.\n\nЛіфт, ліжко, тиша. Спокійної ночі.",
    "Сирена стихла.\n\nХто в укритті — нагору і спати.",
    "Київ — відбій.\n\nКоротко: ніч наша. Спати.",
    "Відбій.\n\nВідбились. Світанок хай буде без сирени.",
]

def decide_alert_action(current: dict, state: dict) -> dict:
    kyiv_was = bool(state.get("kyiv_alert", False))
    kyiv_now = bool(current.get("kyiv", False))
    kyiv_dur = _fmt_duration(state.get("kyiv_since") or 0)
    repeat = _minutes_since_end(state) <= 90

    if kyiv_now and not kyiv_was:
        if repeat:
            return {
                "action": "PUBLISH",
                "event_type": "ALERT_START",
                "title": "🚨 Повторна повітряна тривога",
                "text": f"{random.choice(REPEAT_ALERT)}\n\nПройдіть в укриття.",
                "reason": "repeat Kyiv",
            }
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_START",
            "title": "🚨 Повітряна тривога",
            "text": "Оголошено повітряну тривогу в Києві.\n\nПройдіть в укриття.",
            "reason": "start Kyiv",
        }

    if (not kyiv_now) and kyiv_was and not state.get("kyiv_end_sent"):
        extra = f"У Києві тривога тривала {kyiv_dur}." if kyiv_dur else ""
        pool = BOTH_CLEAR_NIGHT if _is_night() else BOTH_CLEAR_DAY
        text = random.choice(pool)
        if extra:
            text = text + "\n\n" + extra
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_END",
            "title": "🟢 Відбій у Києві",
            "text": text,
            "reason": "end Kyiv",
        }

    return {"action": "IGNORE", "reason": "no change"}

def format_air_post(decision: dict) -> str:
    import re

    CE_SIREN = '<tg-emoji emoji-id="5240038780349489613">🚨</tg-emoji>'
    CE_REPEAT = '<tg-emoji emoji-id="5238053487551490162">🔁</tg-emoji>'
    CE_GREEN = '<tg-emoji emoji-id="5240321801514427483">🟢</tg-emoji>'
    CE_WARN = '<tg-emoji emoji-id="5238203141391951812">⚠️</tg-emoji>'
    CE_DAY = '<tg-emoji emoji-id="5240025208252833961">✅</tg-emoji>'
    CE_NIGHT = '<tg-emoji emoji-id="5240446544544572869">🌙</tg-emoji>'

    event = decision.get("event_type") or ""
    raw_title = decision.get("title") or ""
    title = re.sub(r"^[🚨🟢⚠️✅🌙😴🔁]+\s*", "", raw_title).strip()
    title = re.sub(r"\s*🚨\s*$", "", title).strip()
    body = (decision.get("text") or "").strip()
    is_repeat = "Повторна" in raw_title or event.startswith("ALERT_REPEAT")

    if is_repeat:
        line = f"{CE_REPEAT}{CE_SIREN} <b>Повторна повітряна тривога</b> {CE_SIREN}"
    elif event.startswith("ALERT_START"):
        line = f"{CE_SIREN} <b>Повітряна тривога</b> {CE_SIREN}"
    elif event.startswith("ALERT_UPDATE"):
        line = f"{CE_WARN} <b>Оновлення щодо тривоги</b> {CE_WARN}"
    elif event.startswith("ALERT_END"):
        line = f"{CE_GREEN} <b>Відбій повітряної тривоги</b> {CE_GREEN}"
        mark = CE_NIGHT if _is_night() else CE_DAY
        body = f"{mark} {body}" if body else mark
    else:
        line = f"{CE_SIREN} <b>{title or 'Повітряна тривога'}</b> {CE_SIREN}"

    return f"{line}\n\n{body}\n\n<b>ЧІТКО</b>"


def process_air_cycle() -> dict:
    state = load_state()
    current = fetch_official_alerts()

    if not state.get("initialized"):
        now_ts = time.time()
        state["kyiv_alert"] = current.get("kyiv", False)
        state["oblast_alert"] = current.get("oblast", False)
        state["initialized"] = True
        state["last_post_at"] = 0
        state["last_event"] = ""
        if current.get("kyiv"):
            state["kyiv_since"] = now_ts
        if current.get("oblast"):
            state["oblast_since"] = now_ts
        save_state(state)
        return {
            "action": "IGNORE",
            "reason": "Старт бота: стан записано, без публікації.",
            "current": current,
        }

    decision = decide_alert_action(current, state)
    now_ts = time.time()

    if decision.get("action") == "PUBLISH":
        last_event = state.get("last_event", "")
        et = str(decision.get("event_type") or "")
        gap = 900 if et.startswith("ALERT_END") else 20
        if et == last_event and now_ts - state.get("last_post_at", 0) < gap:
            decision = {"action": "IGNORE", "reason": "Антиспам відбій."}
        else:
            state["last_post_at"] = now_ts
            state["last_event"] = et

    if current.get("kyiv") and not state.get("kyiv_since"):
        state["kyiv_since"] = now_ts
    if not current.get("kyiv"):
        state["kyiv_since"] = 0

    if current.get("oblast") and not state.get("oblast_since"):
        state["oblast_since"] = now_ts
    if not current.get("oblast"):
        state["oblast_since"] = 0

    et = decision.get("event_type", "")
    if et in ("ALERT_END", "ALERT_END_KYIV"):
        state["kyiv_end_sent"] = True
        state["last_end_at"] = now_ts
    if et in ("ALERT_START", "ALERT_UPDATE"):
        if current.get("kyiv"):
            state["kyiv_end_sent"] = False

    state["kyiv_alert"] = current.get("kyiv", False)
    state["oblast_alert"] = current.get("oblast", False)
    state["initialized"] = True
    save_state(state)

    decision["current"] = current
    return decision
