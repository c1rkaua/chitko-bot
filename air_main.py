import asyncio
import os
import re
import time

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from air_engine import process_air_cycle, format_air_post, fetch_official_alerts
from air_monitor import detect_districts

AIR_BOT_TOKEN = os.getenv("AIR_BOT_TOKEN") or os.getenv("BOT_TOKEN")

def _chat(val):
    val = (val or "").strip()
    if not val:
        raise RuntimeError("missing chat id")
    if val.startswith("@"):
        return val
    return int(val)

CHANNEL_ID = _chat(os.getenv("CHANNEL_ID"))
ADMIN_GROUP_ID = _chat(os.getenv("ADMIN_GROUP_ID"))

bot = Bot(
    token=AIR_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

COURSE_SOURCES = (
    "k_dvizh",
    "kievreal1",
    "eradarrua",
)

WAVE = {
    "seen": set(),
    "pin_id": None,
    "kyiv": False,
}

SKIP_LINE = (
    "підписатися", "присылайте", "реклам", "купим",
    "надіслати новину", "онлайн-карта", "повітряна тривога",
    "оголошена", "відбій", "отбой", "підтримай",
)


def parse_course_line(raw: str) -> dict | None:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    low = text.lower()
    if len(low) < 4:
        return None
    if any(s in low for s in SKIP_LINE):
        return None
    districts = detect_districts(text)
    kind = "UAV"
    if any(x in low for x in ("баліст", "кінжал", "іскандер", "циркон")):
        kind = "BALLISTIC"
    elif any(x in low for x in ("крилат", "х-101", "x-101", "ракет")):
        kind = "CRUISE"
    elif any(x in low for x in ("бпла", "шахед", "дрон", "безпілот")):
        kind = "UAV"
    elif not districts:
        return None
    n = 1
    m = re.search(r"(\d+)\s*[xх×]?\s*(?:бпла|шахед|дрон|ракет|баліст)?", low)
    if m:
        n = max(1, int(m.group(1)))
    place = districts[0] if districts else "Київ"
    fp = f"{place.lower()}|{kind}|{n}"
    return {"fp": fp, "place": place, "kind": kind, "n": n, "raw": text[:160]}


def format_course(item: dict) -> str:
    kind_ua = {
        "UAV": "БПЛА",
        "BALLISTIC": "балістика",
        "CRUISE": "крилата ракета",
    }.get(item["kind"], "ціль")
    return (
        f"⚠️ <b>Курс</b> ⚠️\n\n"
        f"{item['n']}× {kind_ua} — {item['place']}.\n"
        f"Пройдіть в укриття.\n\n"
        f"<b>ЧІТКО</b>"
    )


def fetch_course_items() -> list:
    import requests

    headers = {"User-Agent": "Mozilla/5.0"}
    found = []
    seen_now = set()
    for username in COURSE_SOURCES:
        try:
            html = requests.get(
                f"https://t.me/s/{username}",
                headers=headers,
                timeout=8,
            ).text
        except Exception as e:
            print(f"AIR course {username} {e}")
            continue
        chunks = re.split(r'class="tgme_widget_message_text', html)
        for chunk in chunks[1:8]:
            item = parse_course_line(chunk)
            if not item:
                continue
            if item["fp"] in seen_now:
                continue
            seen_now.add(item["fp"])
            item["src"] = username
            found.append(item)
    return found


async def pin_last(msg_id):
    if not msg_id:
        return
    try:
        await bot.unpin_all_chat_messages(chat_id=CHANNEL_ID)
        await bot.pin_chat_message(
            chat_id=CHANNEL_ID,
            message_id=msg_id,
            disable_notification=True,
        )
        WAVE["pin_id"] = msg_id
    except Exception as e:
        print(f"AIR pin {e}")


async def scheduled_siren():
    try:
        data = process_air_cycle()
    except Exception as e:
        print(f"AIR cycle {e}")
        return
    if not isinstance(data, dict):
        return

    kyiv = bool((data.get("current") or {}).get("kyiv"))
    was = WAVE["kyiv"]
    WAVE["kyiv"] = kyiv

    if was and not kyiv:
        WAVE["seen"].clear()
        try:
            await bot.unpin_all_chat_messages(chat_id=CHANNEL_ID)
        except Exception:
            pass
        WAVE["pin_id"] = None

    if data.get("action") != "PUBLISH":
        return
    et = data.get("event_type") or ""
    if et.startswith("ALERT_END") or kyiv or et.startswith("ALERT_START"):
        text = format_air_post(data).strip()
        if len(text) < 20:
            return
        try:
            sent = await bot.send_message(CHANNEL_ID, text)
            if et.startswith("ALERT_END"):
                try:
                    await bot.unpin_all_chat_messages(chat_id=CHANNEL_ID)
                except Exception:
                    pass
            else:
                await pin_last(sent.message_id)
        except Exception as e:
            print(f"AIR send siren {e}")


async def scheduled_course():
    official = fetch_official_alerts() or {}
    if not official.get("kyiv"):
        return
    items = fetch_course_items()
    for item in items:
        fp = item["fp"]
        if fp in WAVE["seen"]:
            print(f"AIR skip fp {fp} via {item.get('src')}")
            continue
        WAVE["seen"].add(fp)
        text = format_course(item)
        try:
            sent = await bot.send_message(CHANNEL_ID, text)
            await pin_last(sent.message_id)
            print(f"AIR course {fp} via {item.get('src')}")
        except Exception as e:
            print(f"AIR send course {e}")


async def main():
    print("AIR bot up")
    scheduler.add_job(scheduled_siren, "interval", seconds=15)
    scheduler.add_job(scheduled_course, "interval", seconds=20)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
