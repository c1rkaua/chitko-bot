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
    "видихає",
    "київ чисто",
    "тимчасово видихає",
    "хмельниччин",
    "рівненщин",
    "чернігівщин",
    "вінниччин",
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

def parse_course_line(raw: str) -> list:
    text = re.sub(r"<[^>]+>", "\n", raw or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(
        r"(підписатися|подписаться|присылайте|присилайте|надіслати новину).*$",
        " ",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"єрадар\s*\|[^\n]*", " ", text, flags=re.I)
    text = re.sub(r"повітряна тривога\|?", " ", text, flags=re.I)
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.split("\n")]
    lines = [x for x in lines if 1 < len(x) < 180]
    if not lines:
        return []

    extra = (
        ("жулян", "Жуляни"),
        ("теремк", "Теремки"),
        ("боярк", "Боярка"),
        ("глевах", "Глеваха"),
        ("ходосів", "Ходосівка"),
        ("ходусів", "Ходосівка"),
        ("ясногород", "Ясногородка"),
        ("боров", "Борова"),
        ("калинівк", "Калинівка"),
        ("сквир", "Сквира"),
        ("обухов", "Обухів"),
        ("обухів", "Обухів"),
        ("крюківщин", "Крюківщина"),
        ("білогород", "Білогородка"),
        ("димер", "Димер"),
        ("лютіж", "Лютіж"),
        ("підгірц", "Підгірці"),
        ("ірпін", "Ірпінь"),
        ("гостомел", "Гостомель"),
    )

    def places_in(s: str) -> list:
        low = s.lower().replace("/", " ")
        found = detect_districts(low) or []
        for key, name in extra:
            if key in low and name not in found:
                found.append(name)
        out = []
        for p in found:
            if p not in out:
                out.append(p)
        return out[:3]

    def kind_of(s: str) -> str:
        low = s.lower()
        if "гучно" in low:
            return "LOUD"
        if any(x in low for x in ("циркон", "кінжал", "іскандер", "баліст")):
            return "BALLISTIC"
        if "реактив" in low:
            return "UAV"
        return "UAV"

    items = []
    seen = set()
    pat = re.compile(
        r"([1-9]|1[0-2])\s*[xх×]\s*(?:реактив\w*\s+)?"
        r"(?:від\s+[^,\n]+?\s+на\s+)?"
        r"([^,\n]+)",
        flags=re.I,
    )
    for line in lines:
        low = line.lower()
        if any(x in low for x in (
            "черкащин", "чернігівщин", "житомирщин",
            "вінниччин", "сумщин", "волин",
        )):
            continue
        if "київщина:" in low and len(line) < 18:
            continue
        if "інші без змін" in low:
            continue
        hits = list(pat.finditer(line))
        chunks = [m.group(2) for m in hits] if hits else [line]
        ns = [int(m.group(1)) for m in hits] if hits else []
        for i, chunk in enumerate(chunks):
            n = ns[i] if i < len(ns) else 1
            nm = re.search(r"\b([1-9]|1[0-2])\b", chunk.lower())
            if nm and not hits:
                n = int(nm.group(1))
            pls = places_in(chunk) or places_in(line)
            if not pls:
                continue
            kind = kind_of(line)
            for place in pls[:2]:
                fp = f"{place.lower()}|{kind}|{n}"
                if fp in seen:
                    continue
                seen.add(fp)
                items.append({
                    "fp": fp,
                    "place": place,
                    "kind": kind,
                    "n": n,
                    "src": "",
                })
    return items

    def places_in(s: str) -> list:
        low = s.lower()
        found = detect_districts(low) or detect_districts(s)
        for key, name in extra:
            if key in low and name not in found:
                found.append(name)
        out = []
        for p in found:
            if p not in out:
                out.append(p)
        return out[:3]

    def kind_of(s: str) -> str:
        low = s.lower()
        if "гучно" in low:
            return "LOUD"
        if any(x in low for x in ("циркон", "zircon")):
            return "ZIRCON"
        if any(x in low for x in ("кінжал", "кинжал", "іскандер", "баліст")):
            return "BALLISTIC"
        if any(x in low for x in ("калібр", "калибр")):
            return "KALIBR"
        if "реактив" in low:
            return "UAV"
        return "UAV"

    items = []
    seen = set()
    pat = re.compile(
        r"([1-9]|1[0-2])\s*[xх×]\s*(?:реактив\w*\s+)?"
        r"(?:від\s+[^,\n]+?\s+на\s+)?"
        r"([^,\n/]+)",
        flags=re.I,
    )
    for line in lines:
        low = line.lower()
        if "київщина" in low and ":" in line and len(line) < 18:
            continue
        if "інші без змін" in low:
            continue
        hits = list(pat.finditer(line))
        if hits:
            for m in hits:
                n = int(m.group(1))
                chunk = m.group(2)
                dest = re.split(r"\s+на\s+", chunk, maxsplit=1)
                piece = dest[-1]
                pls = places_in(piece) or places_in(line)
                if not pls:
                    continue
                kind = kind_of(line)
                for place in pls[:2]:
                    fp = f"{place.lower()}|{kind}|{n}"
                    if fp in seen:
                        continue
                    seen.add(fp)
                    items.append({
                        "fp": fp,
                        "place": place,
                        "kind": kind,
                        "n": n,
                        "src": "",
                    })
            continue
        pls = places_in(line)
        if not pls:
            continue
        if len(line) > 180:
            continue
        n = 1
        nm = re.search(r"\b([1-9]|1[0-2])\b", low)
        if nm:
            n = int(nm.group(1))
        kind = kind_of(line)
        for place in pls[:1]:
            fp = f"{place.lower()}|{kind}|{n}"
            if fp in seen:
                continue
            seen.add(fp)
            items.append({
                "fp": fp,
                "place": place,
                "kind": kind,
                "n": n,
                "src": "",
            })
    return items

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
    from datetime import datetime, timezone, timedelta

    headers = {"User-Agent": "Mozilla/5.0"}
    max_age = timedelta(minutes=5)
    now = datetime.now(timezone.utc)
    found = []
    seen_now = set()
    for username in ("war_monitor", "eradarrua", "k_dvizh", "kievreal1"):
        try:
            html = requests.get(
                f"https://t.me/s/{username}",
                headers=headers,
                timeout=8,
            ).text
        except Exception as e:
            print(f"AIR course {username} {e}")
            continue
        chunks = re.findall(
            r'class="tgme_widget_message[^"]*"(.*?)class="tgme_widget_message_footer',
            html,
            flags=re.I | re.S,
        )
        aged = 0
        parsed = 0
        for raw in chunks[:15]:
            dt_m = re.search(r'datetime="([^"]+)"', raw)
            if not dt_m:
                continue
            try:
                published = datetime.fromisoformat(dt_m.group(1).replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                age = now - published
                if age > max_age or age.total_seconds() < 0:
                    aged += 1
                    continue
            except Exception:
                continue
            for item in parse_course_line(raw):
                parsed += 1
                item["src"] = username
                if item["fp"] in seen_now:
                    continue
                seen_now.add(item["fp"])
                found.append(item)
                print(f"AIR parse {username} {item['fp']} age={int(age.total_seconds())}s")
        print(f"AIR scan {username} chunks={len(chunks)} aged={aged} parsed={parsed}")
    print(f"AIR course fetched {len(found)}")
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
        WAVE["seen"].clear()
        try:
            await bot.unpin_all_chat_messages(chat_id=CHANNEL_ID)
        except Exception:
            pass
        WAVE["pin_id"] = None
    elif not kyiv and WAVE.get("kyiv"):
        WAVE["kyiv"] = False
        WAVE["ended_at"] = time.time()
        WAVE["seen"].clear()

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
        elif et.startswith("ALERT_START") or et.startswith("ALERT_REPEAT"):
            await pin_last(sent.message_id)
    except Exception as e:
        print(f"AIR send siren {e}")
        try:
            await bot.send_message(CHANNEL_ID, text, parse_mode=None)
        except Exception as e2:
            print(f"AIR send siren fallback {e2}")

async def scheduled_course():
    if WAVE.get("ended_at") and time.time() - WAVE["ended_at"] < 90:
        print("AIR course hold after all-clear")
        return

    official_kyiv = False
    try:
        official_kyiv = bool((fetch_official_alerts() or {}).get("kyiv"))
    except Exception as e:
        print(f"AIR official {e}")

    if official_kyiv:
        WAVE["kyiv"] = True
        WAVE["ended_at"] = 0.0
    elif not WAVE.get("kyiv"):
        print("AIR course idle")
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
        text = text.replace("<b>", "").replace("</b>", "")
        kind = "loud" if item["kind"] == "LOUD" else "course"
        ents = pack_entities(text, kind) if "pack_entities" in globals() else None
        try:
            kwargs = {"parse_mode": None}
            if ents:
                kwargs["entities"] = ents
            await bot.send_message(CHANNEL_ID, text, **kwargs)
            print(f"AIR course {fp} via {item.get('src')}")
        except Exception as e:
            print(f"AIR send course {e}")

async def main():
    print("AIR bot up")
    scheduler.add_job(scheduled_siren, "interval", seconds=10, misfire_grace_time=30)
    scheduler.add_job(scheduled_course, "interval", seconds=8, misfire_grace_time=20)
    scheduler.start()
    from air_live import start_live
    asyncio.create_task(
        start_live(
            bot,
            CHANNEL_ID,
            parse_course_line,
            format_course,
            pack_entities if "pack_entities" in globals() else None,
            WAVE,
        )
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
