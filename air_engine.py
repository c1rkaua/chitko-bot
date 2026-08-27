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
            return result
        data = resp.json()
    except Exception as e:
        print(f"AIR API error: {e}")
        return result

    oblasts = data.get("oblasts") or []
    raions = data.get("raions") or []

    for item in oblasts + raions:
        name = (item.get("name") or "") + " " + (item.get("oblast") or "")
        name_l = name.lower()
        if "м. київ" in name_l or name_l.strip() == "київ":
            result["kyiv"] = True
        if "київська область" in name_l:
            result["oblast"] = True

    return result


def decide_alert_action(current: dict, state: dict) -> dict:
    kyiv_was = state.get("kyiv_alert", False)
    obl_was = state.get("oblast_alert", False)
    kyiv_now = current.get("kyiv", False)
    obl_now = current.get("oblast", False)
    kyiv_dur = _fmt_duration(state.get("kyiv_since") or 0)
    obl_dur = _fmt_duration(state.get("oblast_since") or 0)
    repeat = _minutes_since_end(state) <= 90

    def with_dur(text: str, extra: str = "") -> str:
        if extra:
            return text + "\n\n" + extra
        return text

    if kyiv_was and not kyiv_now and obl_now:
        extra = f"У Києві тривога тривала {kyiv_dur}." if kyiv_dur else ""
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_END_KYIV",
            "title": "🟢 Відбій у Києві",
            "text": with_dur(random.choice(KYIV_OFF_OBLAST_ON), extra),
            "reason": "Відбій лише в Києві.",
        }

    if obl_was and not obl_now and kyiv_now:
        extra = f"В області тривога тривала {obl_dur}." if obl_dur else ""
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_END_OBLAST",
            "title": "🟢 Відбій у Київській області",
            "text": with_dur(random.choice(OBLAST_OFF_KYIV_ON), extra),
            "reason": "Відбій лише в області.",
        }

    if (kyiv_was or obl_was) and (not kyiv_now) and (not obl_now):
        bits = []
        if kyiv_was and kyiv_dur:
            bits.append(f"Київ — {kyiv_dur}.")
        if obl_was and obl_dur:
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
                f"Повторна повітряна тривога {where}.\n"
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
                "Повторна повітряна тривога в Київській області.\n"
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
    title = decision.get("title", "").strip()
    text = decision.get("text", "").strip()
    return f"<b>{title}</b>\n\n{text}\n\n<b>ЧІТКО</b>"


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
        if current.get("kyiv") and not state.get("kyiv_since"):
            state["kyiv_since"] = now_ts
        if current.get("oblast") and not state.get("oblast_since"):
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

    if decision.get("action") == "PUBLISH" and str(decision.get("event_type", "")).startswith("ALERT_END"):
        state["last_end_at"] = now_ts

    state["kyiv_alert"] = current.get("kyiv", False)
    state["oblast_alert"] = current.get("oblast", False)
    state["initialized"] = True
    save_state(state)

    decision["current"] = current
    return decision

        
