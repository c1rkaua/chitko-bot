def format_air_post(decision: dict) -> str:
    title = decision.get("title", "").strip()
    text = decision.get("text", "").strip()
    return f"<b>{title}</b>\n\n{text}\n\n<b>ЧІТКО</b>"


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
    }cd ~/Desktop/chitko_bot
git add air_engine.py main.py
git commit -m "Air alerts for Kyiv and Kyiv oblast"
git push
ч
