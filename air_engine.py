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
    "У Києві відбій. На Київщині тривога ще триває.",
    "Столиця — тихо. Область поки під сиреною.",
    "У Києві можна видихнути. Київщина ще чекає відбою.",
    "Відбій по Києву. Область не відпускає.",
    "Київ без сирени. У області поки небезпечно.",
    "По місту — відбій. По області сирена ще працює.",
    "У столиці відбій. Не розслабляйтесь, якщо ви в області.",
    "Київ відпустило. Київщина ще в укритті.",
    "Відбій у Києві. Область — без змін, тривога триває.",
    "Місто тихе. Область ще під загрозою.",
    "Київ — відбій. Хто в області, залишайтесь на місці.",
    "Сирену в Києві зняли. На Київщині поки ні.",
]

OBLAST_OFF_KYIV_ON = [
    "У області відбій. Київ ще під тривогою.",
    "Київщину відпустило. Столиця поки в укритті.",
    "По області — відбій. По Києву сирена ще тримає.",
    "Область тихо. Київ — без змін, тривога триває.",
    "Відбій на Київщині. У місті поки рано виходити.",
    "Область відпустила. Київ ще чекає відбою.",
    "По області чисто. Столиця ще під сиреною.",
    "Київська область — відбій. Київ залишається в тривозі.",
    "Область можна видихнути. Київ — ні.",
    "Відбій по області. У Києві сирена ще лунає.",
]

BOTH_CLEAR_DAY = [
    "Відбій у Києві та області.\n\nНебо чисте.",
    "Сирену зняли і в місті, і на Київщині.\n\nНебо чисте.",
    "Київ і область — відбій.\n\nМожна видихнути.",
    "Тиша. Відбій по Києву і області.\n\nНебо чисте.",
    "Обидві сирени знято.\n\nНебо чисте. Обережно з уламками.",
    "Відбій. Столиця і область знову без тривоги.\n\nНебо чисте.",
    "По Києву і Київщині — відбій.\n\nТримаємось.",
    "Сирена затихла в місті й області.\n\nНебо чисте.",
    "Відбій повний.\n\nНебо чисте. Бережіть себе.",
    "Київ, область — тихо.\n\nНебо чисте.",
    "Зняли і там, і там.\n\nНебо чисте.",
    "Відбій. День триває.\n\nНебо чисте.",
]

BOTH_CLEAR_NIGHT = [
    "Відбій у Києві та області.\n\nВідбились. Усім спокійної ночі.",
    "Сирену зняли.\n\nНебо чисте. Спати, якщо виходить.",
    "Київ і область — відбій.\n\nВідбились. Доброї ночі.",
    "Тиша. Можна лягати.\n\nНебо чисте. Спокійної ночі.",
    "Повний відбій.\n\nБережіть себе. Надобраніч.",
    "Сирена затихла.\n\nВідбились. Усім тихої ночі.",
    "Відбій. Місто і область відпустило.\n\nСпокійної ночі.",
    "Небо чисте.\n\nВідбились. Спати.",
    "Зняли тривогу в Києві й на Київщині.\n\nДоброї ночі.",
    "Тихо.\n\nНебо чисте. Надобраніч.",
    "Відбій. Ніч ще наша.\n\nСпокійної ночі.",
    "Повний відбій по столиці й області.\n\nВідбились. Спати пора.",
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


def fetch_official_alerts() -> dict:
    result = {"kyiv": False, "oblast": False}
    try:
        resp = requests.get("https://neptun.in.ua/api/v1/alerts", timeout=8)
        if resp.status_code != 200:
            print(f"AIR API status {resp.status_code}")
            return result
        data = resp.json()
    except Exception as e:
        print(f"AIR API error: {e}")
        return result

    items = (data.get("oblasts") or []) + (data.get("raions") or [])
    for item in items:
        name = (item.get("name") or "").strip().lower()
        oblast = (item.get("oblast") or "").strip().lower()
        key = (item.get("key") or "").strip().lower()
        blob = f"{name} {oblast} {key}"

        if name in ("київ", "м. київ", "місто київ") or key in ("kyiv", "m.kyiv", "kyiv_city"):
            result["kyiv"] = True
        elif "київська область" in blob or key.startswith("kyivska"):
            if name not in ("київ", "м. київ"):
                result["oblast"] = True

    print(f"AIR status kyiv={result['kyiv']} oblast={result['oblast']}")
    return result

def decide_alert_action(state: dict, kyiv_now: bool, oblast_now: bool) -> dict:
    import random
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    kyiv_was = bool(state.get("kyiv_alert"))
    oblast_was = bool(state.get("oblast_alert"))
    initialized = bool(state.get("initialized"))

    def minutes_since_end():
        raw = state.get("last_end_at")
        if not raw:
            return 9999
        try:
            end = datetime.fromisoformat(str(raw))
            return (now - end).total_seconds() / 60
        except Exception:
            return 9999

    is_repeat = minutes_since_end() <= 90

    if not initialized:
        return {
            "action": "IGNORE",
            "text": "",
            "kyiv": kyiv_now,
            "oblast": oblast_now,
            "initialized": True,
        }

    started_kyiv = kyiv_now and not kyiv_was
    started_oblast = oblast_now and not oblast_was
    ended_kyiv = (not kyiv_now) and kyiv_was
    ended_oblast = (not oblast_now) and oblast_was

    if started_kyiv or started_oblast:
        kind = "repeat" if is_repeat else "start"
        closer = random.choice(REPEAT_ALERT) if kind == "repeat" else ""
        text = build_alert_start_text(
            kind=kind,
            kyiv=kyiv_now,
            oblast=oblast_now,
            closer=closer,
        )
        return {
            "action": "start",
            "text": text,
            "kyiv": kyiv_now,
            "oblast": oblast_now,
            "initialized": True,
        }

    if ended_kyiv and oblast_now:
        return {
            "action": "kyiv_off",
            "text": random.choice(KYIV_OFF_OBLAST_ON),
            "kyiv": False,
            "oblast": True,
            "initialized": True,
        }

    if ended_oblast and kyiv_now:
        return {
            "action": "oblast_off",
            "text": random.choice(OBLAST_OFF_KYIV_ON),
            "kyiv": True,
            "oblast": False,
            "initialized": True,
        }

    if (ended_kyiv or ended_oblast) and (not kyiv_now) and (not oblast_now):
        hour = now.hour
        pool = BOTH_CLEAR_NIGHT if hour >= 22 or hour < 6 else BOTH_CLEAR_DAY
        return {
            "action": "all_clear",
            "text": random.choice(pool),
            "kyiv": False,
            "oblast": False,
            "initialized": True,
            "last_end_at": now.isoformat(),
        }

    return {
        "action": "IGNORE",
        "text": "",
        "kyiv": kyiv_now,
        "oblast": oblast_now,
        "initialized": True,
    }

def format_air_post(decision: dict) -> str:
    title = decision.get("title", "").strip()
    text = decision.get("text", "").strip()
    return f"<b>{title}</b>\n\n{text}\n\n<b>ЧІТКО</b>"

def build_alert_start_text(kind: str, kyiv: bool, oblast: bool, closer: str = "") -> str:
    if kyiv and oblast:
        where = "у Києві та Київській області"
    elif kyiv:
        where = "у Києві"
    else:
        where = "у Київській області"

    if kind == "repeat":
        line = closer.strip() if closer else "Повторна тривога. Короткий антракт закінчився."
        if line.lower().startswith("повторна"):
            body = line
        else:
            body = line
        return (
            f"🚨 <b>Повторна повітряна тривога</b>\n\n"
            f"{body}\n\n"
            f"Пройдіть в укриття."
        )

    return (
        f"🚨 <b>Повітряна тривога</b>\n\n"
        f"Оголошена {where}.\n\n"
        f"Пройдіть в укриття."
    )

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
        if (
            decision.get("event_type") == last_event
            and now_ts - state.get("last_post_at", 0) < 20
        ):
            decision = {"action": "IGNORE", "reason": "Антиспам 20с."}
        else:
            state["last_post_at"] = now_ts
            state["last_event"] = decision.get("event_type", "")

    if current.get("kyiv") and not state.get("kyiv_since"):
        state["kyiv_since"] = now_ts
    if not current.get("kyiv"):
        state["kyiv_since"] = 0

    if current.get("oblast") and not state.get("oblast_since"):
        state["oblast_since"] = now_ts
    if not current.get("oblast"):
        state["oblast_since"] = 0

    et = decision.get("event_type", "")
    if et == "ALERT_END_KYIV":
        state["kyiv_end_sent"] = True
        state["last_end_at"] = now_ts
    if et == "ALERT_END_OBLAST":
        state["oblast_end_sent"] = True
        state["last_end_at"] = now_ts
    if et == "ALERT_END":
        state["kyiv_end_sent"] = True
        state["oblast_end_sent"] = True
        state["last_end_at"] = now_ts
    if et in ("ALERT_START", "ALERT_UPDATE"):
        if current.get("kyiv"):
            state["kyiv_end_sent"] = False
        if current.get("oblast"):
            state["oblast_end_sent"] = False

    state["kyiv_alert"] = current.get("kyiv", False)
    state["oblast_alert"] = current.get("oblast", False)
    state["initialized"] = True
    save_state(state)

    decision["current"] = current
    return decision
        
