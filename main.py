from news_engine import (
    get_top_news_for_brief,
    format_news_post,
    published_ids,
    save_published_ids,
    fetch_article_text_sync,
    select_for_publish,
    get_news_category,
    prepare_image_with_watermark,
    is_bad_source_image,
    ensure_punctuation,
    load_recent_titles,
    save_recent_titles,
    pick_cycle_news,
    apply_watermark,
)
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from dotenv import load_dotenv
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from aiogram.types import MessageEntity

def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2

def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def news_entities(text: str) -> list:
    from aiogram.types import MessageEntity

    ents = []
    first = text.split("\n", 1)[0]
    bolt = first.split(" ", 1)[0] if first else ""
    if bolt:
        ents.append(MessageEntity(
            type="custom_emoji",
            offset=0,
            length=u16(bolt),
            custom_emoji_id="5237977689968651276",
        ))
    title = first[len(bolt):].strip() if bolt else first.strip()
    t_at = first.find(title) if title else -1
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

pending_news = {}  # тимчасове сховище новин на апрув

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
CHANNEL_ID = os.getenv("CHANNEL_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

def is_english_post(news: dict, formatted: str) -> bool:
    t = " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        formatted or "",
    ]).lower()
    ru = (
        " баллист", " слышн", " мощн", " взрыв", " по киеву",
        " монитор", " калибр", " уже 17",
        " годами", " поддержива", " государственной",
        " древесина", " кубометров", " схемы с",
        " даниил ", " маландий",
    )
    if any(x in t for x in ru):
        return True
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 20:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters) > 0.45

async def publish_news_post(news: dict, formatted: str):
    await send_news_to_channel(news, formatted)
# ======================
# Отримання курсів НБУ
# ======================
def get_nbu_rates() -> dict:
    import requests
    from datetime import datetime, timedelta

    out = {
        "usd": None,
        "eur": None,
        "pln": None,
        "usd_delta": None,
        "eur_delta": None,
        "pln_delta": None,
    }
    try:
        today = requests.get(
            "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json",
            timeout=6,
        ).json()
        yday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        prev = requests.get(
            f"https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?date={yday}&json",
            timeout=6,
        ).json()
    except Exception as e:
        print(f"NBU error: {e}")
        return out

    def pick(rows, code):
        for row in rows:
            if row.get("cc") == code:
                return float(row.get("rate") or 0)
        return None

    out["usd"] = pick(today, "USD")
    out["eur"] = pick(today, "EUR")
    out["pln"] = pick(today, "PLN")
    pu = pick(prev, "USD")
    pe = pick(prev, "EUR")
    pp = pick(prev, "PLN")
    if out["usd"] and pu:
        out["usd_delta"] = round(out["usd"] - pu, 2)
    if out["eur"] and pe:
        out["eur_delta"] = round(out["eur"] - pe, 2)
    if out["pln"] and pp:
        out["pln_delta"] = round(out["pln"] - pp, 2)
    return out

def fmt_uah(n) -> str:
    if n is None:
        return "—"
    return f"{n:.2f}".replace(".", ",")


def fmt_delta(n) -> str:
    if n is None:
        return ""
    arrow = "↑" if n > 0 else ("↓" if n < 0 else "→")
    return f"{arrow} {abs(n):.2f}".replace(".", ",")

# ======================
# Отримання цін на паливо (тимчасово)
# ======================
def get_fuel_prices() -> dict:
    import re
    import requests

    out = {"a95": None, "dp": None, "lpg": None}
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ChitkoBot"}

    def to_float(s):
        return float(str(s).replace(",", ".").replace(" ", ""))

    def ok(key, val):
        if val is None:
            return False
        ranges = {"a95": (60, 110), "dp": (60, 130), "lpg": (30, 70)}
        lo, hi = ranges[key]
        return lo <= val <= hi

    def grab(html, label):
        m = re.search(
            label + r".{0,180}?(\d{2}[.,]\d{2})",
            html,
            re.I | re.S,
        )
        return to_float(m.group(1)) if m else None

    # 1. Мінфін — середні по країні
    try:
        html = requests.get(
            "https://index.minfin.com.ua/ua/markets/fuel/",
            headers=headers,
            timeout=8,
        ).text
        a95 = grab(html, r"Бензин А-95(?!\s*преміум)")
        dp = grab(html, r"Дизельне палив")
        lpg = grab(html, r"Газ авто")
        if ok("a95", a95):
            out["a95"] = a95
        if ok("dp", dp):
            out["dp"] = dp
        if ok("lpg", lpg):
            out["lpg"] = lpg
        print(f"FUEL minfin: {out}")
    except Exception as e:
        print(f"FUEL minfin error: {e}")

    # 2. НафтоРинок — запас
    if not (out["a95"] and out["dp"] and out["lpg"]):
        try:
            html = requests.get(
                "https://www.nefterynok.info/fuel-lpg",
                headers=headers,
                timeout=8,
            ).text
            if not out["a95"]:
                m = re.search(r"Бензин А-95\s*\|\s*\*\*(\d+[.,]\d{2})\s*грн", html, re.I)
                if m and ok("a95", to_float(m.group(1))):
                    out["a95"] = to_float(m.group(1))
            if not out["dp"]:
                m = re.search(r"Дизельне пальне\s*\|\s*\*\*(\d+[.,]\d{2})\s*грн", html, re.I)
                if m and ok("dp", to_float(m.group(1))):
                    out["dp"] = to_float(m.group(1))
            if not out["lpg"]:
                m = re.search(r"Автогаз \(LPG\)\s*\|\s*\*\*(\d+[.,]\d{2})\s*грн", html, re.I)
                if m and ok("lpg", to_float(m.group(1))):
                    out["lpg"] = to_float(m.group(1))
            print(f"FUEL nefterynok: {out}")
        except Exception as e:
            print(f"FUEL nefterynok error: {e}")

    return out
# ======================
# Формування бріфу
# ======================
def format_morning_brief_text(rates, fuel, headlines: list) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    days = [
        "понеділок", "вівторок", "середа", "четвер",
        "п’ятниця", "субота", "неділя",
    ]
    date_line = f"{now.strftime('%d.%m.%Y')} • {days[now.weekday()]}"

    lines = [
        "<b>ЧІТКО</b>",
        date_line,
        "",
        "<b>КУРС НБУ</b>",
        f"USD    {fmt_uah(rates.get('usd'))} ₴    {fmt_delta(rates.get('usd_delta'))}",
        f"EUR    {fmt_uah(rates.get('eur'))} ₴    {fmt_delta(rates.get('eur_delta'))}",
        "",
        "<b>ПАЛИВО</b>",
        f"А-95    {fmt_uah(fuel.get('a95'))} ₴/л",
        f"ДП      {fmt_uah(fuel.get('dp'))} ₴/л",
        f"Газ     {fmt_uah(fuel.get('lpg'))} ₴/л",
        "",
        "<b>ГОЛОВНЕ ЗА НІЧ</b>",
    ]
    n = 1
    for h in headlines:
        title = (h.get("title_chitko") or h.get("title_original") or "").strip().rstrip(".")
        if not title:
            continue
        if is_english_post(h, title):
            continue
        lines.append(f"{n}. {title}")
        n += 1
        if n > 3:
            break

    lines += ["", "<b>ЧІТКО. Коротко. По суті.</b>"]
    return "\n".join(lines)

def format_evening_digest_text(rates, fuel, headlines: list) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    days = [
        "понеділок", "вівторок", "середа", "четвер",
        "п’ятниця", "субота", "неділя",
    ]
    date_line = f"{now.strftime('%d.%m.%Y')} • {days[now.weekday()]}"

    lines = [
        "<b>ЧІТКО</b>",
        date_line,
        "",
        "<b>КУРС НБУ</b>",
        f"USD    {fmt_uah(rates.get('usd'))} ₴    {fmt_delta(rates.get('usd_delta'))}",
        f"EUR    {fmt_uah(rates.get('eur'))} ₴    {fmt_delta(rates.get('eur_delta'))}",
        "",
        "<b>ПАЛИВО</b>",
        f"А-95    {fmt_uah(fuel.get('a95'))} ₴/л",
        f"ДП      {fmt_uah(fuel.get('dp'))} ₴/л",
        f"Газ     {fmt_uah(fuel.get('lpg'))} ₴/л",
        "",
        "<b>ГОЛОВНЕ ЗА ДЕНЬ</b>",
    ]
    for i, h in enumerate(headlines[:5], 1):
        title = (h.get("title_chitko") or h.get("title_original") or "").strip().rstrip(".")
        if title:
            lines.append(f"{i}. {title}")

    lines += ["", "<b>ЧІТКО. Коротко. По суті.</b>"]
    return "\n".join(lines)

def _headline_key(title: str) -> str:
    t = (title or "").lower()
    if "санду" in t or "кишин" in t or "молдов" in t:
        return "moldova_sandu"
    if "патріот" in t or "patriot" in t:
        return "patriot"
    if "140 дрон" in t or "повітряні сили" in t or "пс:" in t:
        return "ps_drones"
    if "києв" in t and ("вибух" in t or "дрон" in t):
        return "kyiv_strike"
    words = [w for w in t.replace("«", " ").replace("»", " ").split() if len(w) > 4]
    return " ".join(sorted(words)[:6])


def pick_brief_headlines(items: list, limit: int = 3) -> list:
    seen = set()
    out = []
    ranked = sorted(items or [], key=lambda x: x.get("final_score") or 0, reverse=True)
    for h in ranked:
        title = (h.get("title_chitko") or h.get("title_original") or "").strip()
        if not title:
            continue
        key = _headline_key(title)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
        if len(out) >= limit:
            break
    return out

def render_brief_card(rates: dict, fuel: dict, headlines: list, title_news: str = "ГОЛОВНЕ ЗА РАНОК") -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from PIL import Image, ImageDraw, ImageFont
    import os

    W, H = 1080, 1920
    BG = (0, 0, 0)
    GOLD = (201, 162, 39)
    WHITE = (255, 255, 255)
    GREEN = (46, 204, 113)
    RED = (231, 76, 60)
    GRAY = (170, 170, 170)
    LEFT, RIGHT = 90, 990

    img = Image.new("RGB", (W, H), BG)

    cover_path = os.path.join(os.path.dirname(__file__), "assets", "cover_ranok.jpg")
    if os.path.exists(cover_path):
        cover = Image.open(cover_path).convert("RGB")
        cw, ch = cover.size
        new_h = int(W * ch / cw)
        cover = cover.resize((W, new_h))
        # беремо середню смугу з логотипом
        top = max(0, (new_h - 420) // 2)
        band = cover.crop((0, top, W, top + 420))
        img.paste(band, (0, 0))
        y0 = 440
    else:
        y0 = 80

    d = ImageDraw.Draw(img)

    def font(size, bold=False):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
        for p in paths:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()

    f_date = font(28)
    f_sec = font(26, True)
    f_label = font(34)
    f_val = font(34, True)
    f_news = font(30)
    f_foot = font(24)
    f_num = font(28, True)

    def tw(text, fnt):
        b = d.textbbox((0, 0), text, font=fnt)
        return b[2] - b[0], b[3] - b[1]

    def center(text, y, fnt, fill=WHITE):
        w, _ = tw(text, fnt)
        d.text(((W - w) // 2, y), text, font=fnt, fill=fill)

    def wrap(text, fnt, max_w):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if tw(test, fnt)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:3]

    def gold_line(y):
        d.line((LEFT + 40, y, RIGHT - 40, y), fill=GOLD, width=2)

    months = [
        "січня", "лютого", "березня", "квітня", "травня", "червня",
        "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
    ]
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    date_s = f"{now.day} {months[now.month - 1]} {now.year}"

    y = y0
    center(date_s, y, f_date, GRAY)
    gold_line(y + 50)

    y += 90
    center("КУРС ВАЛЮТ (НБУ)", y, f_sec, GOLD)
    y += 55

    def row(label, value, delta, yy):
        d.text((LEFT, yy), label, font=f_label, fill=WHITE)
        val = fmt_uah(value) + " ₴"
        vw, _ = tw(val, f_val)
        arrow_x = RIGHT - 20
        d.text((arrow_x - 70 - vw, yy), val, font=f_val, fill=GOLD)
        if delta is None:
            return
        color = GREEN if delta > 0 else (RED if delta < 0 else GRAY)
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        d.text((arrow_x - 24, yy), arrow, font=f_val, fill=color)

    row("USD / UAH", rates.get("usd"), rates.get("usd_delta"), y)
    row("EUR / UAH", rates.get("eur"), rates.get("eur_delta"), y + 58)
    row("PLN / UAH", rates.get("pln"), rates.get("pln_delta"), y + 116)

    y += 200
    gold_line(y)
    center("ПАЛИВО (середні ціни по АЗС)", y + 28, f_sec, GOLD)
    y += 90
    row("A-95", fuel.get("a95"), None, y)
    row("ДП", fuel.get("dp"), None, y + 58)
    row("Автогаз", fuel.get("lpg"), None, y + 116)

    y += 210
    gold_line(y)
    center(title_news, y + 28, f_sec, GOLD)
    y += 95

    for i, h in enumerate(headlines[:3], 1):
        t = (h.get("title_chitko") or h.get("title_original") or "").strip().rstrip(".")
        d.ellipse((LEFT, y + 2, LEFT + 44, y + 46), outline=GOLD, width=2)
        nw, _ = tw(str(i), f_num)
        d.text((LEFT + 22 - nw // 2, y + 6), str(i), font=f_num, fill=GOLD)
        lines = wrap(t, f_news, RIGHT - (LEFT + 70))
        ly = y
        for line in lines:
            d.text((LEFT + 64, ly + 6), line, font=f_news, fill=WHITE)
            ly += 38
        y = ly + 28

    gold_line(H - 120)
    center("ЧІТКО. КОРОТКО. ПО СУТІ.", H - 85, f_foot, GRAY)

    path = "/tmp/chitko_brief.jpg"
    img.save(path, "JPEG", quality=93)
    return path

async def create_morning_brief():
    try:
        rates = get_nbu_rates()
    except Exception as e:
        print(f"BRIEF rates: {e}")
        rates = {
            "usd": None, "eur": None, "pln": None,
            "usd_delta": None, "eur_delta": None, "pln_delta": None,
        }
    try:
        fuel = get_fuel_prices()
    except Exception as e:
        print(f"BRIEF fuel: {e}")
        fuel = {"a95": None, "dp": None, "lpg": None}
    try:
        headlines = get_top_news_for_brief(5)
    except Exception as e:
        print(f"BRIEF news: {e}")
        headlines = []
    headlines = pick_brief_headlines(headlines, 3)
    return format_morning_brief_text(rates, fuel, headlines)


async def create_evening_digest():
    try:
        rates = get_nbu_rates()
    except Exception as e:
        print(f"DIGEST rates: {e}")
        rates = {
            "usd": None, "eur": None, "pln": None,
            "usd_delta": None, "eur_delta": None, "pln_delta": None,
        }
    try:
        fuel = get_fuel_prices()
    except Exception as e:
        print(f"DIGEST fuel: {e}")
        fuel = {"a95": None, "dp": None, "lpg": None}
    try:
        headlines = get_top_news_for_brief(8)
    except Exception as e:
        print(f"DIGEST news: {e}")
        headlines = []
    headlines = pick_brief_headlines(headlines, 5)
    return format_evening_digest_text(rates, fuel, headlines)

async def scheduled_digest():
    text = await create_evening_digest()
    cover = os.path.join(os.path.dirname(__file__), "assets", "cover_digest.jpg")
    if os.path.exists(cover):
        await bot.send_photo(
            CHANNEL_ID,
            photo=FSInputFile(cover),
            caption=text,
            parse_mode="HTML",
        )
    else:
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
    
# ======================
# Команда /brief
# ======================
@dp.message(Command("brief"))
async def cmd_brief(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    try:
        await message.answer("Збираю бриф...")
        rates = get_nbu_rates()
        fuel = get_fuel_prices()
        try:
            headlines = get_top_news_for_brief(5)
        except Exception:
            headlines = []
        text = format_morning_brief_text(rates, fuel, headlines)
        cover = os.path.join(os.path.dirname(__file__), "assets", "cover_ranok.jpg")
        if os.path.exists(cover):
            await message.answer_photo(
                photo=FSInputFile(cover),
                caption=text,
                parse_mode="HTML",
            )
        else:
            await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Бриф упав: {e}")
        print(f"BRIEF error: {e}")

@dp.message(Command("news"))
async def cmd_news(message: Message):
    print(f"CMD news chat={message.chat.id} admin={ADMIN_GROUP_ID}")
    if str(message.chat.id) != str(ADMIN_GROUP_ID):
        await message.answer(
            f"Не той чат.\nЦей id: {message.chat.id}\nУ бота: {ADMIN_GROUP_ID}"
        )
        return
    await message.answer("Збираю новини...")
    await scheduled_news()
    await message.answer("Цикл /news завершено.")

@dp.message(Command("digest"))
async def cmd_digest(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    await message.answer("Збираю вечірній дайджест...")
    await scheduled_evening_digest()

# ======================
# Обробка кнопок
# ======================
@dp.callback_query(F.data == "approve_brief")
async def approve_brief(callback: CallbackQuery):
    text = callback.message.text or callback.message.caption or ""
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")

    news_list = get_top_news_for_brief(3)
    for news in news_list:
        formatted = format_news_post(news)
        await publish_news_post(news, formatted)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Бриф опубліковано")

@dp.callback_query(lambda c: c.data and c.data.startswith("approve_one_"))
async def approve_one(callback: CallbackQuery):
    event_id = callback.data.replace("approve_one_", "")
    news = pending_news.get(event_id)

    if not news:
        await callback.answer("Стара новина", show_alert=True)
        return

    if news.get("final_score", 0) >= 90 and news.get("source_url"):
        try:
            full_text = fetch_article_text_sync(news["source_url"])
            if full_text and len(full_text) > 120:
                news["text_chitko"] = full_text
        except Exception:
            pass

    formatted = format_news_post(news)
    await send_news_to_channel(news, formatted)

    published_ids.add(news["event_id"])
    save_published_ids(published_ids)

    recent = load_recent_titles()
    recent.append(news.get("title_chitko") or news.get("title_original") or news.get("title") or "")
    save_recent_titles(recent)

    pending_news.pop(event_id, None)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Опубликовано")


@dp.callback_query(F.data.startswith("skip_one_"))
async def skip_one(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Пропущено")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    
    published_count = len(published_ids)
    pending_count = len(pending_news)
    
    text = (
        f"<b>Статистика ЧІТКО</b>\n\n"
        f"Опубликовано: <b>{published_count}</b>\n"
        f"Сейчас на апруве: <b>{pending_count}</b>\n\n"
        f"Порог авто: 75+\n"
        f"Форс-мажор: 90+"
    )
    
    await message.answer(text, parse_mode="HTML")

# ======================
# Запуск
# ======================

def _mark_path(kind: str) -> str:
    return os.path.join(os.path.dirname(__file__), f"sent_{kind}.txt")


def already_sent_today(kind: str) -> bool:
    from zoneinfo import ZoneInfo
    path = _mark_path(kind)
    day = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d")
    try:
        return open(path, "r").read().strip() == day
    except Exception:
        return False


def mark_sent_today(kind: str) -> None:
    from zoneinfo import ZoneInfo
    day = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d")
    with open(_mark_path(kind), "w") as f:
        f.write(day)


async def scheduled_brief():
    if already_sent_today("brief"):
        print("BRIEF already today")
        return
    text = await create_morning_brief()
    cover = os.path.join(os.path.dirname(__file__), "assets", "cover_ranok.jpg")
    try:
        if os.path.exists(cover):
            await bot.send_photo(
                CHANNEL_ID,
                photo=FSInputFile(cover),
                caption=text,
                parse_mode="HTML",
            )
        else:
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        mark_sent_today("brief")
        await bot.send_message(ADMIN_GROUP_ID, "Ранковий бріф опубліковано в канал.")
    except Exception as e:
        print(f"BRIEF send {e}")
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        mark_sent_today("brief")


async def scheduled_evening_digest():
    if already_sent_today("digest"):
        print("DIGEST already today")
        return
    text = await create_evening_digest()
    cover = os.path.join(os.path.dirname(__file__), "assets", "cover_digest.jpg")
    try:
        if os.path.exists(cover):
            await bot.send_photo(
                CHANNEL_ID,
                photo=FSInputFile(cover),
                caption=text,
                parse_mode="HTML",
            )
        else:
            await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        mark_sent_today("digest")
        await bot.send_message(ADMIN_GROUP_ID, "Вечірній дайджест опубліковано в канал.")
    except Exception as e:
        print(f"DIGEST send {e}")

def is_english_post(news: dict, formatted: str) -> bool:
    blob = " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        formatted or "",
    ])
    low = blob.lower()
    ru = (
        "баллист", "слышн", "мощн", "взрыв", "по киеву",
        "монитор", "калибр", "уже 17",
    )
    if any(x in low for x in ru):
        return True
    letters = [c for c in blob if c.isalpha()]
    if len(letters) < 20:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters) > 0.45

async def send_news_to_channel(news: dict, formatted: str):
    import os
    import tempfile
    import requests
    from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo

    title = (news.get("title_chitko") or news.get("title") or "").strip()
    if len(title) < 8 or not formatted or "⚡️" not in formatted:
        print("SEND skip")
        return
    if is_english_post(news, formatted):
        print("SEND skip english")
        return

    ents = news_entities(formatted)

    def download(url: str, suffix=".jpg"):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200 or len(r.content) < 2000:
                return None
            fd, path = tempfile.mkstemp(suffix=suffix)
            os.write(fd, r.content)
            os.close(fd)
            return path
        except Exception as e:
            print(f"DL fail {e}")
            return None

    def watermark_file(path: str) -> str:
        try:
            fd, out = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            result = apply_watermark(path, out)
            return result or path
        except Exception as e:
            print(f"WM file fail {e}")
            return path

    photos = [u for u in (news.get("media_urls") or []) if u]
    if not photos and news.get("image_url") and not is_bad_source_image(news.get("image_url")):
        photos = [news["image_url"]]
    videos = list(news.get("video_urls") or [])
    if news.get("video_url") and news["video_url"] not in videos:
        videos.insert(0, news["video_url"])
    paths = []

    try:
        vfiles = []
        for url in videos[:4]:
            p = download(url, suffix=".mp4")
            if p:
                paths.append(p)
                vfiles.append(p)

        pfiles = []
        for url in photos[:10]:
            path = download(url)
            if not path:
                continue
            paths.append(path)
            marked = watermark_file(path)
            if marked != path:
                paths.append(marked)
            pfiles.append(marked)

        if len(vfiles) == 1 and not pfiles:
            await bot.send_video(
                CHANNEL_ID,
                video=FSInputFile(vfiles[0]),
                caption=formatted,
                caption_entities=ents,
            )
            print("SEND video")
            return

        if len(vfiles) >= 2 and not pfiles:
            media = [
                InputMediaVideo(
                    media=FSInputFile(vfiles[0]),
                    caption=formatted,
                    caption_entities=ents,
                )
            ]
            for vf in vfiles[1:4]:
                media.append(InputMediaVideo(media=FSInputFile(vf)))
            await bot.send_media_group(CHANNEL_ID, media=media)
            print("SEND videos")
            return

        if vfiles and pfiles:
            media = [
                InputMediaVideo(
                    media=FSInputFile(vfiles[0]),
                    caption=formatted,
                    caption_entities=ents,
                )
            ]
            for pf in pfiles[:3]:
                media.append(InputMediaPhoto(media=FSInputFile(pf)))
            await bot.send_media_group(CHANNEL_ID, media=media)
            print("SEND mix")
            return

        if len(pfiles) >= 2:
            media = [
                InputMediaPhoto(
                    media=FSInputFile(pfiles[0]),
                    caption=formatted,
                    caption_entities=ents,
                )
            ]
            for pf in pfiles[1:10]:
                media.append(InputMediaPhoto(media=FSInputFile(pf)))
            await bot.send_media_group(CHANNEL_ID, media=media)
            print("SEND album")
            return

        if len(pfiles) == 1:
            await bot.send_photo(
                CHANNEL_ID,
                photo=FSInputFile(pfiles[0]),
                caption=formatted,
                caption_entities=ents,
            )
            print("SEND photo")
            return

        await bot.send_message(CHANNEL_ID, formatted, entities=ents)
        print("SEND text")
    except Exception as e:
        print(f"SEND fail {e}")
        try:
            await bot.send_message(CHANNEL_ID, formatted, entities=ents)
            print("SEND text fallback")
        except Exception as e2:
            print(f"SEND text fail {e2}")
    finally:
        for p in paths:
            try:
                os.remove(p)
            except Exception:
                pass

def pick_cycle_news(items: list) -> list:
    items = sorted(items or [], key=lambda x: x.get("final_score") or 0, reverse=True)
    civilian, war, politics, other, world = [], [], [], [], []

    world_keys = (
        "непал", "китай", "інді", "пакистан", "африц",
        "голівуд", "оскар", "євробачен",
    )
    soft_keys = (
        "прибуток", "фінкомпан", "котируван", "акці ",
        "рейтинг банків",
    )

    for n in items:
        bucket = n.get("bucket") or ""
        score = float(n.get("final_score") or 0)
        if score < 50:
            continue
        if bucket == "war_filler":
            continue
        blob = " ".join([
            n.get("title_chitko") or "",
            n.get("title") or "",
            n.get("text") or "",
        ]).lower()
        if bucket == "civilian":
            civilian.append(n)
        elif bucket == "hard_war":
            war.append(n)
        elif bucket in ("politics", "law"):
            politics.append(n)
        elif any(k in blob for k in world_keys + soft_keys):
            world.append(n)
        else:
            other.append(n)

    out = []
    out.extend(civilian[:2])
    if war:
        out.append(war[0])
    if politics and len(out) < 3:
        out.append(politics[0])
    if other and len(out) < 3:
        out.append(other[0])
    if world and len(out) < 2:
        out.append(world[0])

    print(
        f"PICK civil={len(civilian[:2])} war={1 if war else 0} "
        f"pol={1 if politics and politics[0] in out else 0} "
        f"other={sum(1 for x in out if x in other)} world={sum(1 for x in out if x in world)}"
    )
    return out[:3]


NEWS_LOCK = {"on": False}
LAST_AUTO_NEWS = {"at": 0.0}
LAST_PUB_TITLES = []
LAST_AUTO_FILE = "last_auto.json"

def load_last_auto() -> float:
    import json
    import os
    try:
        if os.path.exists(LAST_AUTO_FILE):
            with open(LAST_AUTO_FILE, "r", encoding="utf-8") as f:
                return float((json.load(f) or {}).get("at") or 0)
    except Exception:
        pass
    return 0.0

def save_last_auto(ts: float) -> None:
    import json
    try:
        with open(LAST_AUTO_FILE, "w", encoding="utf-8") as f:
            json.dump({"at": ts}, f)
    except Exception as e:
        print(f"SAVE last_auto {e}")

def seed_titles_from_channel() -> list:
    import re
    import requests

    out = []
    try:
        html = requests.get(
            "https://t.me/s/chitko_ua",
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        ).text
    except Exception as e:
        print(f"SEED channel fail {e}")
        return out
    chunks = re.split(r'class="tgme_widget_message_text', html)
    for chunk in chunks[1:25]:
        raw = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        if len(raw) < 20:
            continue
        title = raw.split(".")[0].strip()[:140]
        if title and title not in out:
            out.append(title)
    print(f"SEED channel {len(out)}")
    return out

def cluster_unique(items: list) -> list:
    from news_engine import is_same_story, load_recent_titles, news_fingerprint, is_hit_story

    seen = list(LAST_PUB_TITLES)
    try:
        seen.extend(load_recent_titles() or [])
    except Exception:
        pass
    out = []
    for n in items:
        fp = news_fingerprint(n)
        if len(fp) < 12:
            continue
        if any(is_same_story(fp, old) for old in seen):
            print(f"CLUSTER skip: {fp[:80]}")
            continue
        seen.append(fp)
        out.append(n)
    return out


NEWS_LOCK = {"on": False}

async def scheduled_news():
    import time
    from news_engine import (
        is_breaking,
        is_same_story,
        prepare_chitko_news,
        news_fingerprint,
        is_hit_story,
        fetch_and_score_news,
        WAR_FILLER_KEYS,
        TRACKER_SKIP,
    )

    if NEWS_LOCK.get("on"):
        print("NEWS lock skip")
        return
    NEWS_LOCK["on"] = True
    try:
        raw = fetch_and_score_news(40)
        now = time.time()
        sent = 0

        filtered = []
        for item in raw or []:
            title = (item.get("title") or item.get("title_chitko") or "").strip()
            blob = " ".join([
                title,
                item.get("text") or "",
                item.get("body") or "",
            ]).lower()
            if any(k in blob for k in WAR_FILLER_KEYS):
                print(f"SKIP filler {title[:60]}")
                continue
            if any(k in blob for k in TRACKER_SKIP):
                print(f"SKIP tracker {title[:60]}")
                continue
            filtered.append(item)

        unique = cluster_unique(filtered)
        hits = [n for n in unique if is_hit_story(n)]
        mix = [n for n in unique if n not in hits]
        queue = hits + mix
        last_auto = float(LAST_AUTO_NEWS.get("at") or 0)

        for item in queue:
            if sent >= 2:
                break
            title = (item.get("title_chitko") or item.get("title") or "").strip()
            if len(title) < 8:
                continue

            hit = is_hit_story(item)
            if (not hit) and last_auto and now - last_auto < 12 * 60:
                print("HOLD mix")
                continue

            fp_now = news_fingerprint(item)
            if any(is_same_story(fp_now, old) for old in LAST_PUB_TITLES[-40:]):
                print(f"DUP skip {fp_now[:80]}")
                continue

            try:
                item = prepare_chitko_news(item)
            except Exception as e:
                print(f"REWRITE fail {e}")
            formatted = format_news_post(item)
            if not formatted or "⚡️" not in formatted:
                continue

            fp_fmt = news_fingerprint(item)
            if any(is_same_story(fp_fmt, old) for old in LAST_PUB_TITLES[-40:]):
                print(f"DUP skip after rewrite {fp_fmt[:80]}")
                continue

            await send_news_to_channel(item, formatted)
            LAST_PUB_TITLES.append(fp_fmt)
            if len(LAST_PUB_TITLES) > 80:
                del LAST_PUB_TITLES[:-80]
            LAST_AUTO_NEWS["at"] = now
            save_last_auto(now)
            sent += 1
            print(f"AUTO {'HIT' if hit else 'MIX'} {title[:80]}")

        print(f"NEWS cycle sent={sent} raw={len(raw or [])} uniq={len(unique)}")
    except Exception as e:
        print(f"NEWS cycle fail {e}")
    finally:
        NEWS_LOCK["on"] = False

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
    print("Я заработал")
    try:
        from news_engine import load_recent_titles
        loaded = load_recent_titles() or []
        LAST_PUB_TITLES.clear()
        LAST_PUB_TITLES.extend(loaded[-80:])
        for title in seed_titles_from_channel():
            if title not in LAST_PUB_TITLES:
                LAST_PUB_TITLES.append(title)
        print(f"SEED titles {len(LAST_PUB_TITLES)}")
    except Exception as e:
        print(f"SEED titles fail {e}")

    LAST_AUTO_NEWS["at"] = load_last_auto() or 0.0
    print(f"SEED last_auto {int(LAST_AUTO_NEWS['at'])}")

    scheduler.add_job(
        scheduled_brief,
        CronTrigger(hour=7, minute=0, timezone="Europe/Kyiv"),
        misfire_grace_time=10800,
        id="brief",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_brief,
        CronTrigger(hour=7, minute=15, timezone="Europe/Kyiv"),
        id="brief_retry",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_news,
        "interval",
        minutes=2,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        scheduled_evening_digest,
        CronTrigger(hour=22, minute=0, timezone="Europe/Kyiv"),
        misfire_grace_time=10800,
        id="digest",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_evening_digest,
        CronTrigger(hour=22, minute=15, timezone="Europe/Kyiv"),
        id="digest_retry",
        replace_existing=True,
    )

    scheduler.start()
    print("Планувальник запущено")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
