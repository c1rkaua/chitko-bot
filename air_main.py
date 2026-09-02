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
from aiogram.types import Message, MessageEntity


def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


CE = {
    "siren": ("🚨", "5240038780349489613"),
    "repeat": ("🔁", "5238053487551490162"),
    "green": ("🟢", "5240321801514427483"),
    "warn": ("⚠️", "5238203141391951812"),
    "loud": ("⚠️", "5240501069154396615"),
    "day": ("✅", "5240025208252833961"),
    "night": ("🌙", "5240446544544572869"),
    "bolt": ("⚡️", "5237977689968651276"),
}


def pack_entities(text: str, kind: str) -> list:
    ents = []
    first = text.split("\n", 1)[0]
    end_line = u16(first)

    def add(ch, eid, start_from=0, stop=None):
        stop = len(text) if stop is None else stop
        pos = 0
        chunk = text
        while True:
            i = chunk.find(ch, pos)
            if i < 0 or i >= stop:
                break
            off = u16(text[:i])
            ents.append(MessageEntity(
                type="custom_emoji",
                offset=off,
                length=u16(ch),
                custom_emoji_id=eid,
            ))
            pos = i + len(ch)
            if start_from:
                break

    if kind == "start":
        add("🚨", CE["siren"][1], stop=end_line)
    elif kind == "repeat":
        add("🔁", CE["repeat"][1], stop=end_line)
        add("🚨", CE["siren"][1], stop=end_line)
    elif kind == "end":
        add("🟢", CE["green"][1], stop=end_line)
        add("✅", CE["day"][1])
        add("🌙", CE["night"][1])
    elif kind == "update":
        add("⚠️", CE["warn"][1], stop=end_line)
    elif kind == "course":
        add("⚠️", CE["warn"][1], stop=end_line)
    elif kind == "loud":
        add("⚠️", CE["loud"][1], stop=end_line)

    title = first
    for a, b in (("🚨 ", ""), (" 🚨", ""), ("🔁", ""), ("⚠️ ", ""), (" ⚠️", ""), ("🟢 ", ""), (" 🟢", "")):
        title = title.replace(a, b)
    title = title.strip()
    t_at = first.find(title)
    if t_at >= 0:
        ents.append(MessageEntity(
            type="bold",
            offset=u16(text[:t_at]),
            length=u16(title),
        ))
    foot = "ЧІТКО"
    f_at = text.rfind(foot)
    if f_at >= 0:
        ents.append(MessageEntity(
            type="bold",
            offset=u16(text[:f_at]),
            length=u16(foot),
        ))
    return ents

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
)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

COURSE_SOURCES = (
    "k_dvizh",
    "eradarrua",
    "kievreal1",
    "povitryanatrivogaaa",
)

WAVE = {
    "seen": set(),
    "pin_id": None,
    "kyiv": False,
    "ended_at": 0.0,
}

SKIP_LINE = (
    "підписатися", "подписаться", "присилайте", "присылайте",
    "надіслати новину", "карта загроз", "мапа загроз",
    "live map", "підтримай", "донат", "гривнєю",
    "дорозвідк", "очікуйте офіційну",
    "вижив", "сука оболон",
    "ннннн", "ссссуууу",
    "полтавщин", "чернігівщин", "нових на",
    "відбоїв не буде",
)

KIND_UA = {
    "UAV": ("БПЛА", "БПЛА", "БПЛА"),
    "BALLISTIC": ("балістика", "балістики", "балістик"),
    "CRUISE": ("крилата ракета", "крилаті ракети", "крилатих ракет"),
    "ZIRCON": ("Циркон", "Циркони", "Цирконів"),
    "KALIBR": ("Калібр", "Калібри", "Калібрів"),
}


def ua_kind(n: int, kind: str) -> str:
    one, few, many = KIND_UA.get(kind, ("ціль", "цілі", "цілей"))
    n = int(n or 1)
    if n % 100 in (11, 12, 13, 14):
        word = many
    elif n % 10 == 1:
        word = one
    elif n % 10 in (2, 3, 4):
        word = few
    else:
        word = many
    return f"{n}× {word}"

def parse_course_line(raw: str) -> dict | None:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    low = text.lower()
    if len(low) < 3:
        return None
    low = re.sub(r"підписатися.*", " ", low)
    low = re.sub(r"присылайте.*", " ", low)
    low = re.sub(r"надіслати новину.*", " ", low)
    low = re.sub(r"слідкувати в онлайн.*", " ", low)
    low = re.sub(r"єрадар\s*\|[^\n]*", " ", low)
    low = re.sub(r"повітряна тривога\|?", " ", low)
    low = re.sub(r"ракетна небезпека\|?", " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    if any(s in low for s in SKIP_LINE):
        return None
    if any(x in low for x in ("відбій", "отбой", "не фіксується", "відбоїв не буде")):
        return None

    districts = detect_districts(low) or detect_districts(text)
    if not districts:
        return None
    place = ", ".join(districts[:4])

    if "гучно" in low:
        return {"fp": f"loud|{place.lower()}", "place": place, "kind": "LOUD", "n": 1, "src": ""}

    kind = None
    if any(x in low for x in ("циркон", "zircon")):
        kind = "ZIRCON"
    elif any(x in low for x in ("калібр", "калибр", "kalibr")):
        kind = "KALIBR"
    elif any(x in low for x in ("кінжал", "кинжал", "іскандер", "искандер")):
        kind = "BALLISTIC"
    elif "баліст" in low:
        kind = "BALLISTIC"
    elif any(x in low for x in ("крилат", "х-101", "x-101")):
        kind = "CRUISE"
    elif any(x in low for x in (
        "бпла", "шахед", "дрон", "безпілот",
        "намотує", "кола", "реактив", "падає", "йде на",
        "летить", "полетів",
    )):
        kind = "UAV"
    else:
        kind = "UAV"

    n = 1
    m = re.search(r"(?:ще\s+)?([1-9]|1[0-2])\s*(?:x|х|×|реактив|шахед|бпла|дрон|ціл|ракет)", low)
    if m:
        n = int(m.group(1))

    fp = f"{place.lower()}|{kind}|{n}"
    return {"fp": fp, "place": place, "kind": kind, "n": n, "src": ""}

def format_course(item: dict) -> str:
    if item["kind"] == "LOUD":
        return (
            f"⚠️ Гучно ⚠️\n\n"
            f"{item['place']}.\n"
            f"Пройдіть в укриття.\n\n"
            f"ЧІТКО"
        )
    if item["kind"] == "CLEAR":
        return (
            f"⚠️ Курс ⚠️\n\n"
            f"Поки чисто над Києвом.\n"
            f"Загроза ще не знята.\n\n"
            f"ЧІТКО"
        )
    if item["kind"] == "LAUNCH":
        return (
            f"⚠️ Курс ⚠️\n\n"
            f"Ще пуски.\n"
            f"Пройдіть в укриття.\n\n"
            f"ЧІТКО"
        )
    line = ua_kind(item.get("n") or 1, item["kind"])
    return (
        f"⚠️ Курс ⚠️\n\n"
        f"{line} — {item['place']}.\n"
        f"Пройдіть в укриття.\n\n"
        f"ЧІТКО"
    )

def fetch_course_items() -> list:
    import requests

    headers = {"User-Agent": "Mozilla/5.0"}
    found = []
    seen_now = set()
    for username in ("k_dvizh", "eradarrua", "kievreal1"):
        try:
            html = requests.get(
                f"https://t.me/s/{username}",
                headers=headers,
                timeout=6,
            ).text
        except Exception as e:
            print(f"AIR course {username} {e}")
            continue
        chunks = re.split(r'class="tgme_widget_message_text', html)
        for chunk in chunks[1:10]:
            item = parse_course_line(chunk)
            if not item:
                continue
            if item["fp"] in seen_now:
                continue
            seen_now.add(item["fp"])
            item["src"] = username
            found.append(item)
            print(f"AIR take {item['fp']} via {username}")
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
    et = data.get("event_type") or ""

    if kyiv and not WAVE.get("kyiv"):
        WAVE["kyiv"] = True
        WAVE["ended_at"] = 0.0
        WAVE["seen"].clear()
        print("AIR wave on")
    if et.startswith("ALERT_START") or et.startswith("ALERT_REPEAT"):
        WAVE["kyiv"] = True
        WAVE["ended_at"] = 0.0
        WAVE["seen"].clear()
    elif et.startswith("ALERT_END"):
        WAVE["kyiv"] = False
        WAVE["ended_at"] = time.time()
        try:
            await bot.unpin_all_chat_messages(chat_id=CHANNEL_ID)
        except Exception:
            pass
        WAVE["pin_id"] = None
    elif not kyiv and WAVE.get("kyiv"):
        WAVE["kyiv"] = False
        WAVE["ended_at"] = time.time()

    if data.get("action") != "PUBLISH":
        return
    if not (
        et.startswith("ALERT_END")
        or et.startswith("ALERT_START")
        or et.startswith("ALERT_REPEAT")
    ):
        return

    text = format_air_post(data).strip()
    text = re.sub(r"</?tg-emoji[^>]*>", "", text)
    text = text.replace("<b>", "").replace("</b>", "")
    if len(text) < 20:
        return

    raw_title = data.get("title") or ""
    if "Повторна" in raw_title or et.startswith("ALERT_REPEAT"):
        kind = "repeat"
    elif et.startswith("ALERT_START"):
        kind = "start"
    elif et.startswith("ALERT_END"):
        kind = "end"
    else:
        kind = "update"
    ents = pack_entities(text, kind) if "pack_entities" in globals() else None
    try:
        kwargs = {"parse_mode": None}
        if ents:
            kwargs["entities"] = ents
        sent = await bot.send_message(CHANNEL_ID, text, **kwargs)
        if et.startswith("ALERT_END"):
            try:
                await bot.unpin_all_chat_messages(chat_id=CHANNEL_ID)
            except Exception:
                pass
        else:
            await pin_last(sent.message_id)
    except Exception as e:
        print(f"AIR send siren {e}")
        try:
            await bot.send_message(CHANNEL_ID, text, parse_mode=None)
        except Exception as e2:
            print(f"AIR send siren fallback {e2}")

async def scheduled_course():
    if WAVE.get("ended_at") and time.time() - WAVE["ended_at"] < 180:
        print("AIR course hold after all-clear")
        return
    if not WAVE.get("kyiv"):
        try:
            off = fetch_official_alerts()
            if off.get("kyiv"):
                WAVE["kyiv"] = True
                WAVE["ended_at"] = 0.0
                print("AIR wave on via official")
            else:
                print("AIR course idle")
                return
        except Exception as e:
            print(f"AIR official {e}")
            return

    items = fetch_course_items()
    if not items:
        print("AIR course empty")
        return
    for item in items:
        fp = item["fp"]
        if fp in WAVE["seen"]:
            print(f"AIR skip fp {fp}")
            continue
        WAVE["seen"].add(fp)
        text = format_course(item)
        text = re.sub(r"</?tg-emoji[^>]*>", "", text)
        text = re.sub(r"</?b>", "", text)
        kind = "loud" if item["kind"] == "LOUD" else "course"
        ents = pack_entities(text, kind)
        try:
            sent = await bot.send_message(
                CHANNEL_ID,
                text,
                parse_mode=None,
                entities=ents,
            )
            await pin_last(sent.message_id)
            print(f"AIR course {fp} via {item.get('src')}")
        except Exception as e:
            print(f"AIR send course {e}")
            
@dp.message()
async def catch_emoji_id(message: Message):
    if str(message.chat.id) != str(ADMIN_GROUP_ID):
        return
    if message.text and message.text.startswith("/"):
        return
    bits = []
    if message.sticker:
        bits.append(f"sticker file_id={message.sticker.file_id}")
        bits.append(f"custom_emoji_id={message.sticker.custom_emoji_id}")
    ents = list(message.entities or []) + list(message.caption_entities or [])
    for e in ents:
        cid = getattr(e, "custom_emoji_id", None)
        bits.append(f"{e.type} custom_emoji_id={cid} offset={e.offset}")
    if bits:
        await message.answer("\n".join(bits))

async def main():
    print("AIR bot up")
    scheduler.add_job(scheduled_siren, "interval", seconds=10, misfire_grace_time=30)
    scheduler.add_job(scheduled_course, "interval", seconds=8, misfire_grace_time=20)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
