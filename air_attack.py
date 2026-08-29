import json
import os
import time

ATTACK_FILE = "air_attack.json"
PAUSE_NEW_EVENT_SEC = 45 * 60  # нова атака, якщо тиша 45 хв

TYPE_UA = {
    "BALLISTIC": "балістичні цілі",
    "CRUISE": "крилаті ракети",
    "AERO": "аеробалістичні ракети",
    "HYPER": "гіперзвукові ракети",
    "UAV": "ударні БПЛА",
    "UNKNOWN": "невстановлені повітряні цілі",
}

TYPE_UA_ONE = {
    "BALLISTIC": "балістична ціль",
    "CRUISE": "крилата ракета",
    "AERO": "аеробалістична ракета",
    "HYPER": "гіперзвукова ракета",
    "UAV": "ударний БПЛА",
    "UNKNOWN": "невстановлена повітряна ціль",
}

EMOJI = {
    "BALLISTIC": "🔴",
    "CRUISE": "🚀",
    "AERO": "🔴",
    "HYPER": "🔴",
    "UAV": "🛩",
    "UNKNOWN": "⚠️",
    "COMBO": "🔴",
}


def load_attack() -> dict:
    if not os.path.exists(ATTACK_FILE):
        return empty_attack()
    try:
        with open(ATTACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return empty_attack()


def empty_attack() -> dict:
    return {
        "event_id": "",
        "active": False,
        "target": "Київ",
        "totals": {
            "BALLISTIC": 0,
            "CRUISE": 0,
            "AERO": 0,
            "HYPER": 0,
            "UAV": 0,
            "UNKNOWN": 0,
        },
        "last_update": 0,
        "updates_count": 0,
    }


def save_attack(data: dict):
    with open(ATTACK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _count_phrase(n: int, t: str) -> str:
    if n == 1:
        return f"1 {TYPE_UA_ONE[t]}"
    return f"{n} {TYPE_UA[t]}"


def _direction(target: str) -> str:
    if target == "Київ":
        return "у напрямку Києва"
    return "у напрямку Київщини"


def _active_types(totals: dict) -> list:
    return [t for t, n in totals.items() if n > 0]


def format_first_post(t: str, n: int, target: str) -> str:
    emoji = EMOJI.get(t, "⚠️")
    return (
        f"🚨 <b>Повітряна загроза</b> 🚨\n\n"
        f"{emoji} Зафіксовано {_count_phrase(n, t)} {_direction(target)}.\n"
        f"Пройдіть в укриття.\n\n"
        f"<b>ЧІТКО</b>"
    )


def format_upd_same(t: str, n: int, target: str) -> str:
    emoji = EMOJI.get(t, "⚠️")
    if n == 1:
        body = f"{emoji} +1 {TYPE_UA_ONE[t]} {_direction(target)}."
    else:
        body = f"{emoji} +{n} {TYPE_UA[t]} {_direction(target)}."
    return (
        f"⚠️ <b>Оновлення щодо загрози</b> ⚠️\n\n️"
        f"{body}\n\n"
        f"<b>ЧІТКО</b>"
    )


def format_upd_new_type(t: str, n: int, target: str) -> str:
    emoji = EMOJI.get(t, "⚠️")
    return (
        f"⚠️ <b>Оновлення щодо загрози</b> ⚠️\n\n"
        f"{emoji} Додатково {_count_phrase(n, t)} {_direction(target)}.\n\n"
        f"<b>ЧІТКО</b>"
    )


def format_combo(totals: dict, target: str) -> str:
    lines = []
    for t in ("BALLISTIC", "HYPER", "AERO", "CRUISE", "UAV", "UNKNOWN"):
        n = totals.get(t, 0)
        if n:
            lines.append(f"{EMOJI.get(t, '⚠️')} {_count_phrase(n, t)}")
    return (
        f"🚨 <b>Комбінована повітряна загроза</b> 🚨\n\n"
        f"Зафіксовано {_direction(target)}:\n"
        + "\n".join(lines)
        + "\n\nПройдіть в укриття.\n\n"
        f"<b>ЧІТКО</b>"
    )

def format_summary(totals: dict, target: str) -> str:
    parts = []
    for t in ("BALLISTIC", "HYPER", "AERO", "CRUISE", "UAV", "UNKNOWN"):
        n = totals.get(t, 0)
        if n:
            parts.append(f"{EMOJI.get(t, '⚠️')} {_count_phrase(n, t)}")
    joined = "\n".join(parts) if parts else "цілі"
    return (
        f"⚠️ <b>Станом на зараз</b> ⚠️\n\n"
        f"{joined}\n"
        f"{_direction(target).capitalize()}.\n\n"
        f"<b>ЧІТКО</b>"
    )


def ingest_targets(target_type: str, count: int, target: str = "Київ", is_new: bool = True) -> dict:
    """
    target_type: BALLISTIC / CRUISE / UAV / AERO / HYPER / UNKNOWN
    count: скільки НОВИХ цілей (не загальний тотал джерела)
    is_new=False — повтор того самого, IGNORE
    """
    t = target_type.upper()
    if t not in TYPE_UA:
        t = "UNKNOWN"
    if count < 1:
        return {"action": "IGNORE", "reason": "Немає кількості.", "message": ""}

    data = load_attack()
    now = time.time()

    if data.get("active") and now - data.get("last_update", 0) > PAUSE_NEW_EVENT_SEC:
        data = empty_attack()

    if not is_new:
        return {
            "action": "IGNORE",
            "reason": "Повтор тих самих цілей, не нові.",
            "message": "",
        }

    if not data.get("active"):
        data = empty_attack()
        data["active"] = True
        data["event_id"] = f"ATTACK_KYIV_{int(now)}"
        data["target"] = target
        data["totals"][t] = count
        data["last_update"] = now
        data["updates_count"] = 0
        save_attack(data)
        return {
            "action": "PUBLISH",
            "event_id": data["event_id"],
            "message": format_first_post(t, count, target),
            "reason": "Нова атака.",
            "totals": data["totals"],
        }

    already = _active_types(data["totals"])
    data["totals"][t] = data["totals"].get(t, 0) + count
    data["last_update"] = now
    data["updates_count"] = data.get("updates_count", 0) + 1
    save_attack(data)

    if t in already:
        msg = format_upd_same(t, count, target)
    else:
        msg = format_upd_new_type(t, count, target)

    return {
        "action": "UPDATE",
        "event_id": data["event_id"],
        "message": msg,
        "reason": f"+{count} {t}",
        "totals": data["totals"],
    }

def ingest_combo(buckets: dict, target: str = "Київ") -> dict:
    clean = {}
    for t, n in (buckets or {}).items():
        t = str(t).upper()
        if t not in TYPE_UA:
            t = "UNKNOWN"
        n = int(n or 0)
        if n > 0:
            clean[t] = clean.get(t, 0) + n
    if not clean:
        return {"action": "IGNORE", "reason": "Немає кількості.", "message": ""}

    if len(clean) == 1:
        t, n = next(iter(clean.items()))
        return ingest_targets(t, n, target, is_new=True)

    data = load_attack()
    now = time.time()

    if data.get("active") and now - data.get("last_update", 0) > PAUSE_NEW_EVENT_SEC:
        data = empty_attack()

    if not data.get("active"):
        data = empty_attack()
        data["active"] = True
        data["event_id"] = f"ATTACK_KYIV_{int(now)}"
        data["target"] = target
        for t, n in clean.items():
            data["totals"][t] = data["totals"].get(t, 0) + n
        data["last_update"] = now
        data["updates_count"] = 0
        save_attack(data)
        return {
            "action": "PUBLISH",
            "event_id": data["event_id"],
            "message": format_combo(data["totals"], target),
            "reason": "Комбінована атака.",
            "totals": data["totals"],
        }

    lines = []
    for t, n in clean.items():
        already = data["totals"].get(t, 0) > 0
        data["totals"][t] = data["totals"].get(t, 0) + n
        emoji = EMOJI.get(t, "⚠️")
        if already:
            if n == 1:
                lines.append(f"{emoji} +1 {TYPE_UA_ONE[t]} {_direction(target)}.")
            else:
                lines.append(f"{emoji} +{n} {TYPE_UA[t]} {_direction(target)}.")
        else:
            lines.append(f"{emoji} Додатково {_count_phrase(n, t)} {_direction(target)}.")

    data["last_update"] = now
    data["updates_count"] = data.get("updates_count", 0) + 1
    save_attack(data)

    msg = (
        f"⚠️ <b>Оновлення щодо загрози</b> ⚠️\n\n"
        + "\n".join(lines)
        + "\n\n<b>ЧІТКО</b>"
    )

    return {
        "action": "UPDATE",
        "event_id": data["event_id"],
        "message": msg,
        "reason": "Комбіноване оновлення.",
        "totals": data["totals"],
    }

def close_attack():
    data = load_attack()
    data["active"] = False
    save_attack(data)
