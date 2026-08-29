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
    kyiv_was = state.get("kyiv_alert", False)
    obl_was = state.get("oblast_alert", False)
    kyiv_now = current.get("kyiv", False)
    obl_now = False
    kyiv_dur = _fmt_duration(state.get("kyiv_since") or 0)
    obl_dur = _fmt_duration(state.get("oblast_since") or 0)
    repeat = _minutes_since_end(state) <= 90

    def with_dur(text: str, extra: str = "") -> str:
        if extra:
            return text + "\n\n" + extra
        return text

    if (not kyiv_now) and obl_now and not state.get("kyiv_end_sent"):
        extra = f"У Києві тривога тривала {kyiv_dur}." if kyiv_dur else ""
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_END_KYIV",
            "title": "🟢 Відбій у Києві",
            "text": with_dur(random.choice(KYIV_OFF_OBLAST_ON), extra),
            "reason": "Відбій у Києві, область ще під сиреною.",
        }

    if (not obl_now) and kyiv_now and not state.get("oblast_end_sent"):
        extra = f"В області тривога тривала {obl_dur}." if obl_dur else ""
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_END_OBLAST",
            "title": "🟢 Відбій у Київській області",
            "text": with_dur(random.choice(OBLAST_OFF_KYIV_ON), extra),
            "reason": "Відбій в області, Київ ще під сиреною.",
        }

    if (kyiv_was or obl_was) and (not kyiv_now) and (not obl_now):
        bits = []
        if kyiv_dur:
            bits.append(f"Київ — {kyiv_dur}.")
        if obl_dur:
            bits.append(f"Область — {obl_dur}.")
        pool = BOTH_CLEAR_NIGHT if _is_night() else BOTH_CLEAR_DAY
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_END",
            "title": "🟢 Відбій повітряної тривоги",
            "text": with_dur(random.choice(pool), " ".join(bits)),
            "reason": "Повний відбій.",
        }

    if kyiv_now and not kyiv_was:
        if repeat:
            where = "в Києві та Київській області" if obl_now else "в Києві"
            text = (
                f"{random.choice(REPEAT_ALERT)}\n\n"
                "Пройдіть в укриття."
            )
            title = "🚨 Повторна повітряна тривога"
        elif obl_now:
            title = "🚨 Повітряна тривога"
            text = "Оголошено повітряну тривогу в Києві та Київській області.\n\nПройдіть в укриття."
        else:
            title = "🚨 Повітряна тривога"
            text = "Оголошено повітряну тривогу в Києві.\n\nПройдіть в укриття."
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_START",
            "title": title,
            "text": text,
            "reason": "Старт по Києву.",
        }

    if obl_now and not obl_was and not kyiv_now:
        if repeat:
            text = (
                f"{random.choice(REPEAT_ALERT)}\n\n"
                "Стежимо за Києвом."
            )
            title = "🚨 Повторна повітряна тривога"
        else:
            title = "🚨 Повітряна тривога"
            text = "Оголошено повітряну тривогу в Київській області.\n\nСтежимо за Києвом."
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_START",
            "title": title,
            "text": text,
            "reason": "Старт по області.",
        }

    if kyiv_now and not kyiv_was and obl_was:
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_UPDATE",
            "title": "⚠️ Оновлення щодо повітряної загрози",
            "text": "Тривогу оголошено також у Києві.\n\nПройдіть в укриття.",
            "reason": "Київ підключився.",
        }

    return {"action": "IGNORE", "reason": "Статус не змінився."}

def format_air_post(decision: dict) -> str:
    import re

    event = decision.get("event_type") or ""
    raw_title = decision.get("title") or ""
    title = re.sub(r"^[🚨🟢⚠️✅🌙😴🔁]+\s*", "", raw_title).strip()
    title = re.sub(r"\s*🚨\s*$", "", title).strip()
    body = (decision.get("text") or "").strip()

    if event == "ALERT_START" and "Повторна" in raw_title:
        line = "🔁🚨 <b>Повторна повітряна тривога</b>🚨"
    elif event == "ALERT_START":
        line = "🚨 <b>Повітряна тривога</b> 🚨"
    elif event == "ALERT_UPDATE":
        line = "⚠️ <b>Оновлення щодо тривоги</b>⚠️"
    elif event == "ALERT_END_KYIV":
        line = "🟢 <b>Відбій у Києві</b>🟢"
    elif event == "ALERT_END_OBLAST":
        line = "🟢 <b>Відбій у Київській області</b>🟢"
    elif event == "ALERT_END":
        mark = "🌙" if _is_night() else "✅"
        line = f"{mark} <b>Відбій повітряної тривоги</b>"
    else:
        line = f"🚨 <b>{title or 'Повітряна тривога'}</b>🚨"

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
        
