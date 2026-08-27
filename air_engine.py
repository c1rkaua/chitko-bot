import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

STATE_FILE = "air_state.json"


def _now_kyiv():
    return datetime.now(ZoneInfo("Europe/Kyiv"))


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {
            "kyiv_alert": False,
            "oblast_alert": False,
            "last_post_at": 0,
            "last_event": "",
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "kyiv_alert": False,
            "oblast_alert": False,
            "last_post_at": 0,
            "last_event": "",
        }


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


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

    if kyiv_was or obl_was:
        if not kyiv_now and not obl_now:
            return {
                "action": "PUBLISH",
                "event_type": "ALERT_END",
                "priority": 80,
                "confidence": 100,
                "title": "🟢 Відбій повітряної тривоги",
                "text": (
                    "Відбій повітряної тривоги в Києві та Київській області.\n\n"
                    "Будьте обережні після відбою."
                ),
                "reason": "Офіційний відбій для Києва та області.",
            }

    if kyiv_now and not kyiv_was:
        if obl_now:
            text = (
                "Оголошено повітряну тривогу в Києві та Київській області.\n\n"
                "Пройдіть в укриття."
            )
        else:
            text = (
                "Оголошено повітряну тривогу в Києві.\n\n"
                "Пройдіть в укриття."
            )
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_START",
            "priority": 95,
            "confidence": 100,
            "title": "🚨 Повітряна тривога",
            "text": text,
            "reason": "Офіційна тривога в Києві.",
        }

    if obl_now and not obl_was and not kyiv_now:
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_START",
            "priority": 85,
            "confidence": 100,
            "title": "🚨 Повітряна тривога",
            "text": (
                "Оголошено повітряну тривогу в Київській області.\n\n"
                "Стежимо за ситуацією в столиці."
            ),
            "reason": "Офіційна тривога в Київській області.",
        }

    if kyiv_now and not kyiv_was and obl_was:
        return {
            "action": "PUBLISH",
            "event_type": "ALERT_UPDATE",
            "priority": 95,
            "confidence": 100,
            "title": "⚠️ Оновлення щодо повітряної загрози",
            "text": (
                "Повітряну тривогу оголошено також у Києві.\n\n"
                "Пройдіть в укриття."
            ),
            "reason": "Тривога поширилась на місто Київ.",
        }

    return {
        "action": "IGNORE",
        "reason": "Статус не змінився.",
    }


def format_air_post(decision: dict) -> str:
    title = decision.get("title", "").strip()
    text = decision.get("text", "").strip()
    return f"<b>{title}</b>\n\n{text}\n\n<b>ЧІТКО</b>"


def process_air_cycle() -> dict:
    state = load_state()
    current = fetch_official_alerts()
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

    state["kyiv_alert"] = current.get("kyiv", False)
    state["oblast_alert"] = current.get("oblast", False)
    save_state(state)

    decision["current"] = current
    return decision
