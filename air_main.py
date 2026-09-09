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

    def add(ch, eid, stop=None):
        stop = len(text) if stop is None else stop
        variants = [ch]
        if ch == "⚠️":
            variants = ["⚠️", "⚠"]
        if ch == "⚡️":
            variants = ["⚡️", "⚡"]
        for token in variants:
            pos = 0
            while True:
                i = text.find(token, pos)
                if i < 0 or i >= stop:
                    break
                ents.append(MessageEntity(
                    type="custom_emoji",
                    offset=u16(text[:i]),
                    length=u16(token),
                    custom_emoji_id=eid,
                ))
                pos = i + len(token)

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
    elif kind == "news":
        add("⚡️", CE["bolt"][1], stop=end_line)

    title = first
    for a in ("🚨 ", " 🚨", "🔁", "⚠️ ", "⚠ ", " ⚠️", " ⚠", "🟢 ", " 🟢", "⚡️ ", "⚡ "):
        title = title.replace(a, "")
    title = title.strip()
    t_at = first.find(title)
    if t_at >= 0 and title:
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
    "KINZHAL": ("Кинджал", "Кинджали", "Кинджалів"),
    "ISKANDER": ("Іскандер", "Іскандери", "Іскандерів"),
    "KALIBR": ("Калібр", "Калібри", "Калібрів"),
    "X101": ("Х-101", "Х-101", "Х-101"),
}

PLACE_GEO = {
    "київ": (50.4501, 30.5234),
    "оболонь": (50.5010, 30.4980),
    "мінський": (50.5220, 30.4450),
    "виноградар": (50.5100, 30.4300),
    "почайна": (50.4860, 30.4980),
    "куренівка": (50.4865, 30.4680),
    "пріорка": (50.5000, 30.4550),
    "поділ": (50.4680, 30.5160),
    "лук'янівка": (50.4620, 30.4810),
    "шулявка": (50.4540, 30.4540),
    "нивки": (50.4580, 30.4090),
    "святошин": (50.4570, 30.3650),
    "академмістечко": (50.4650, 30.3550),
    "борщагівка": (50.4250, 30.3850),
    "солом'янка": (50.4300, 30.4880),
    "вокзальна": (50.4400, 30.4890),
    "деміївка": (50.4040, 30.5160),
    "голосіїв": (50.3830, 30.5080),
    "теремки": (50.3670, 30.4540),
    "феофанія": (50.3430, 30.4850),
    "печерськ": (50.4270, 30.5380),
    "олімпійська": (50.4330, 30.5160),
    "березняки": (50.4300, 30.6100),
    "русанівські сади": (50.4500, 30.5880),
    "дарниця": (50.4470, 30.6230),
    "дврз": (50.4450, 30.6500),
    "лівий берег": (50.4500, 30.6000),
    "правий берег": (50.4500, 30.5000),
    "троєщина": (50.5120, 30.6080),
    "воскресенка": (50.4850, 30.5960),
    "радужний": (50.5000, 30.6200),
    "осокорки": (50.3950, 30.6150),
    "позняки": (50.4120, 30.6330),
    "харківський масив": (50.4170, 30.6400),
    "видубичі": (50.4000, 30.5600),
    "жуляни": (50.4010, 30.4510),
    "караваєві дачі": (50.4370, 30.4400),
    "відрадний": (50.4300, 30.4300),
    "біличі": (50.4650, 30.3350),
    "пуща-водиця": (50.5400, 30.3550),
    "тець-5": (50.3950, 30.5650),
    "тец-5": (50.3950, 30.5650),
    "бровари": (50.5110, 30.7900),
    "бориспіль": (50.3520, 30.9560),
    "погреби": (50.5550, 30.6330),
    "вишгород": (50.5840, 30.4900),
    "ірпінь": (50.5210, 30.2500),
    "буча": (50.5480, 30.2210),
    "гостомель": (50.5850, 30.2650),
    "вишневе": (50.3870, 30.3700),
    "боярка": (50.3230, 30.2970),
    "глеваха": (50.3100, 30.3230),
    "васильків": (50.1780, 30.3170),
    "обухів": (50.1100, 30.6280),
    "українка": (50.1430, 30.7370),
    "козин": (50.2250, 30.6500),
    "чабани": (50.3400, 30.4220),
    "ходосівка": (50.2770, 30.5180),
    "білогородка": (50.3940, 30.2270),
    "макарів": (50.4640, 29.8150),
    "фастів": (50.0780, 29.9180),
    "кагарлик": (49.8620, 30.8280),
    "бородянка": (50.6440, 29.9200),
    "димер": (50.7860, 30.3020),
    "лютіж": (50.6830, 30.3930),
    "щасливе": (50.3700, 30.7900),
    "гнідин": (50.3300, 30.7300),
    "водосховище": (50.5800, 30.5100),
    "південний міст": (50.3950, 30.5680),
    "міст патона": (50.4270, 30.5650),
    "північний міст": (50.4900, 30.5360),
}


def course_geo(item: dict):
    place = (item.get("place") or "").split("→")[-1].strip().lower()
    if not place:
        return None
    if place in PLACE_GEO:
        return PLACE_GEO[place]
    for key, xy in PLACE_GEO.items():
        if key in place or place in key:
            return xy
    return None

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

KIND_UA = {
    "UAV": ("БПЛА", "БПЛА", "БПЛА"),
    "BALLISTIC": ("балістика", "балістики", "балістик"),
    "CRUISE": ("крилата ракета", "крилаті ракети", "крилатих ракет"),
    "ZIRCON": ("Циркон", "Циркони", "Цирконів"),
    "KINZHAL": ("Кинджал", "Кинджали", "Кинджалів"),
    "ISKANDER": ("Іскандер", "Іскандери", "Іскандерів"),
    "KALIBR": ("Калібр", "Калібри", "Калібрів"),
    "X101": ("Х-101", "Х-101", "Х-101"),
}

RED_KINDS = {"BALLISTIC", "CRUISE", "ZIRCON", "KINZHAL", "ISKANDER", "KALIBR", "X101"}


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
    blob = re.sub(r"\s+", " ", text).strip()
    low_all = blob.lower()
    if not blob:
        return []
    if any(s in low_all for s in SKIP_LINE):
        return []
    if any(x in low_all for x in (
        "котики", "без фіксації", "не летить",
        "полтавщин", "дніпропетров", "кіровоград",
        "миколаїв", "кривого рогу",
    )):
        return []

    extra = (
        ("жулян", "Жуляни"),
        ("теремк", "Теремки"),
        ("боярк", "Боярка"),
        ("глевах", "Глеваха"),
        ("ходосів", "Ходосівка"),
        ("обухів", "Обухів"),
        ("білогород", "Білогородка"),
        ("димер", "Димер"),
        ("лютіж", "Лютіж"),
        ("ірпін", "Ірпінь"),
        ("гостомел", "Гостомель"),
        ("васильк", "Васильків"),
        ("бровар", "Бровари"),
        ("водосховищ", "водосховище"),
        ("чабан", "Чабани"),
        ("фастів", "Фастів"),
        ("українк", "Українка"),
        ("бородянк", "Бородянка"),
        ("осокорк", "Осокорки"),
        ("дарниц", "Дарниця"),
        ("дврз", "ДВРЗ"),
        ("русанівськ", "Русанівські сади"),
        ("віта литов", "Віта-Литовська"),
        ("наливайк", "Наливайківка"),
        ("миронівк", "Миронівка"),
        ("кагарлик", "Кагарлик"),
        ("крушинк", "Крушинка"),
        ("макарів", "Макарів"),
        ("щаслив", "Щасливе"),
        ("гнідин", "Гнідин"),
        ("правий берег", "правий берег"),
        ("лівий берег", "лівий берег"),
        ("печерськ", "Печерськ"),
        ("деміїв", "Деміївка"),
    )

    def places_in(s: str) -> list:
        low = s.lower().replace("/", " ").replace("→", " ").replace("-", " ")
        found = detect_districts(low) or []
        for key, name in extra:
            if key in low and name not in found:
                found.append(name)
        out = []
        for p in found:
            if p not in out:
                out.append(p)
        return out[:5]

    def kind_of(s: str) -> str:
        low = s.lower()
        if "гучно" in low:
            return "LOUD"
        if any(x in low for x in ("циркон", "zircon", "3м22")):
            return "ZIRCON"
        if any(x in low for x in ("кінжал", "кинжал")):
            return "KINZHAL"
        if any(x in low for x in ("іскандер", "искандер")):
            return "ISKANDER"
        if any(x in low for x in ("калібр", "калибр")):
            return "KALIBR"
        if any(x in low for x in ("х-101", "x-101")):
            return "X101"
        if any(x in low for x in (
            "баліст", "баллист", "приготувал", "крилат",
            " кр ", "кр на", "червон", "🔴",
        )):
            return "BALLISTIC"
        return "UAV"

    kind = kind_of(blob)
    places = places_in(blob)
    n = 1
    nm = re.search(r"\b([1-9]|1[0-2])\s*[xх×]?", low_all)
    if nm:
        n = int(nm.group(1))
    if not places:
        if kind in RED_KINDS:
            places = ["Київ"]
        else:
            return []
    route = " → ".join(places)
    fp = f"{kind}|{route.lower()}|{n}"
    return [{
        "fp": fp,
        "place": route,
        "kind": kind,
        "n": n,
        "level": "red" if kind in RED_KINDS else "yellow",
        "src": "",
    }]


def format_course(item: dict) -> str:
    if item["kind"] == "LOUD":
        return (
            f"⚠️ Гучно ⚠️\n\n"
            f"{item['place']}.\n"
            f"Пройдіть в укриття.\n\n"
            f"ЧІТКО"
        )
    level = item.get("level") or ("red" if item["kind"] in RED_KINDS else "yellow")
    mark = "🔴" if level == "red" else "🟡"
    line = ua_kind(item.get("n") or 1, item["kind"])
    return (
        f"⚠️ Курс ⚠️\n\n"
        f"{mark} {line} — {item['place']}.\n"
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

async def main():
    print("AIR bot up")
    scheduler.add_job(scheduled_siren, "interval", seconds=10, misfire_grace_time=30)
    scheduler.add_job(scheduled_course, "interval", seconds=8, misfire_grace_time=20)
    scheduler.start()

    async def _run_live():
        try:
            from air_live import start_live
            await start_live(
                bot,
                CHANNEL_ID,
                parse_course_line,
                format_course,
                pack_entities if "pack_entities" in globals() else None,
                WAVE,
            )
        except Exception as e:
            print(f"AIR live task FAIL {type(e).__name__}: {e}")

    asyncio.create_task(_run_live())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
