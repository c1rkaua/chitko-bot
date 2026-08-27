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
from air_engine import process_air_cycle, format_air_post
from air_attack import ingest_targets, close_attack, format_summary, load_attack
from air_monitor import poll_new_targets
from aiogram.types import FSInputFile

pending_news = {}  # тимчасове сховище новин на апрув

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
CHANNEL_ID = os.getenv("CHANNEL_ID")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Kyiv"))
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

    return outdef format_evening_digest_text
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
    for i, h in enumerate(headlines[:3], 1):
        title = (h.get("title_chitko") or h.get("title_original") or "").strip().rstrip(".")
        if title:
            lines.append(f"{i}. {title}")

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

@dp.message(Command("digest"))
async def cmd_digest(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    try:
        await message.answer("Збираю дайджест...")
        text = await create_evening_digest()
        cover = os.path.join(os.path.dirname(__file__), "assets", "cover_digest.jpg")
        if os.path.exists(cover):
            await message.answer_photo(
                photo=FSInputFile(cover),
                caption=text,
                parse_mode="HTML",
            )
        else:
            await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Дайджест упав: {e}")
        print(f"DIGEST error: {e}")

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
        rates = {"usd": None, "eur": None, "pln": None,
                 "usd_delta": None, "eur_delta": None, "pln_delta": None}
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
    return format_morning_brief_text(rates, fuel, headlines)

async def create_evening_digest():
    rates = get_nbu_rates()
    fuel = get_fuel_prices()
    try:
        headlines = get_top_news_for_brief(8)
    except Exception:
        headlines = []
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
    if message.chat.id != ADMIN_GROUP_ID:
        return

    await message.answer("Збираю новини...")

    news_list = get_top_news_for_brief(12)
    to_auto = select_for_publish(news_list)
    auto_published = 0

    for news in to_auto:
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
        recent.append(news.get("title_original", ""))
        save_recent_titles(recent)

        auto_published += 1

    auto_ids = {n["event_id"] for n in to_auto}
    for_approval = [
        n for n in news_list
        if n["event_id"] not in auto_ids and n.get("final_score", 0) >= 45
    ][:6]

    for news in for_approval:
        pending_news[news["event_id"]] = news

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ APPROVED",
                callback_data=f"approve_one_{news['event_id']}"
            ),
            InlineKeyboardButton(
                text="❌ DECLINE",
                callback_data=f"skip_one_{news['event_id']}"
            )
        ]])

        score = news.get("final_score", 0)
        cat = news.get("category", get_news_category(news.get("title_original", "")))
        conf = news.get("confidence_score", 0)
        preview = (
            f"<b>Score: {score}</b> | conf {conf} | {cat}\n\n"
            f"{format_news_post(news)}"
        )
        await message.answer(preview, reply_markup=keyboard, parse_mode="HTML")

    await message.answer(
        f"Готово.\nАвто: {auto_published}\nНа апрув: {len(for_approval)}"
    )

@dp.message(Command("digest"))
async def cmd_digest(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    try:
        await message.answer("Збираю дайджест...")
        text = await create_evening_digest()
        cover = os.path.join(os.path.dirname(__file__), "assets", "cover_digest.jpg")
        if os.path.exists(cover):
            await message.answer_photo(
                photo=FSInputFile(cover),
                caption=text,
                parse_mode="HTML",
            )
        else:
            await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Дайджест упав: {e}")
        print(f"DIGEST error: {e}")
   

@dp.message(Command("digest"))
async def cmd_digest(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    await message.answer("Збираю вечірній дайджест...")
    await scheduled_evening_digest()

@dp.message(Command("air"))
async def cmd_air(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    try:
        from air_engine import process_air_cycle
        result = process_air_cycle()
        if not isinstance(result, dict):
            await message.answer(str(result))
            return
        kyiv = result.get("kyiv")
        oblast = result.get("oblast")
        if kyiv is None and isinstance(result.get("current"), dict):
            kyiv = result["current"].get("kyiv")
            oblast = result["current"].get("oblast")
        await message.answer(
            f"Київ: {'тривога' if kyiv else 'тихо'}\n"
            f"Область: {'тривога' if oblast else 'тихо'}\n"
            f"Action: {result.get('action')}\n"
            f"{(result.get('text') or 'Статус не змінився.')}"
        )
    except Exception as e:
        await message.answer(f"/air упав: {type(e).__name__}: {e}")
        print(f"AIR cmd error: {e}")

@dp.message(Command("threat"))
async def cmd_threat(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Формат:\n/threat BALLISTIC 2 Київ\n"
            "Типи: BALLISTIC CRUISE UAV AERO HYPER UNKNOWN"
        )
        return

    t = parts[1].upper()
    try:
        n = int(parts[2])
    except Exception:
        await message.answer("Третя частина — число нових цілей.")
        return

    target = "Київ"
    if len(parts) >= 4:
        raw = parts[3].lower()
        if "київщин" in raw or "област" in raw:
            target = "Київщина"

    result = ingest_targets(t, n, target, is_new=True)
    await message.answer(
        f"{result.get('action')}\n{result.get('reason')}"
    )
    if result.get("action") in ("PUBLISH", "UPDATE") and result.get("message"):
        await bot.send_message(
            CHANNEL_ID,
            result["message"],
            parse_mode="HTML"
        )

# ======================
# Обробка кнопок
# ======================
@dp.callback_query(F.data == "approve_brief")
async def approve_brief(callback: CallbackQuery):
    # Спочатку публікуємо бріф
    text = callback.message.text
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
    
    # Потім окремі новини
    news_list = get_top_news_for_brief(3)
    
    for news in news_list:
        formatted = format_news_post(news)
        image_url = news.get("image_url")
        
        try:
            if image_url:
                await bot.send_photo(
                    CHANNEL_ID,
                    photo=image_url,
                    caption=formatted,
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
        except Exception:
            await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Добавил на канал ✅")

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
    recent.append(news.get("title_original", ""))
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

async def scheduled_brief():
    text = await create_morning_brief()
    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
    await bot.send_message(
        ADMIN_GROUP_ID,
        "Ранковий бріф опубліковано в канал."
    )

async def scheduled_evening_digest():
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

    items = items[:5]
    if not items:
        await bot.send_message(
            ADMIN_GROUP_ID,
            "Вечірній дайджест: немає достатньо якісних новин."
        )
        return

    lines = []
    for i, n in enumerate(items, 1):
        title = n.get("title_chitko") or n.get("title_original", "")
        title = ensure_punctuation(title.strip())
        lines.append(f"{i}. {title}")

    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
    except Exception:
        now = datetime.now()

    date_str = now.strftime("%d.%m.%Y")

    text = (
        f"<b>ГОЛОВНЕ ЗА ДЕНЬ</b>\n"
        f"{date_str}\n\n"
        + "\n\n".join(lines)
        + "\n\n<b>ЧІТКО. Коротко. По суті.</b>"
    )

    await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
    await bot.send_message(
        ADMIN_GROUP_ID,
        "Вечірній дайджест опубліковано в канал."
    )

async def send_news_to_channel(news: dict, formatted: str):
    import os
    from aiogram.types import FSInputFile

    video_url = news.get("video_url")
    image_url = news.get("image_url")
    score = news.get("final_score", 0)

    # Не беремо брендовані фото Суспільне тощо
    if image_url and is_bad_source_image(image_url):
        image_url = None

    terminova_path = os.path.join(os.path.dirname(__file__), "assets", "terminova.jpg")
    has_terminova = os.path.isfile(terminova_path)

    try:
        if video_url:
            await bot.send_video(
                CHANNEL_ID,
                video=video_url,
                caption=formatted,
                parse_mode="HTML"
            )
            return

        # Breaking без нормального фото → картка ТЕРМІНОВА
        if score >= 90 and not image_url and has_terminova:
            photo = FSInputFile(terminova_path)
            await bot.send_photo(
                CHANNEL_ID,
                photo=photo,
                caption=formatted,
                parse_mode="HTML"
            )
            return

        if image_url:
            local_path = prepare_image_with_watermark(image_url)
            if local_path:
                photo = FSInputFile(local_path)
                await bot.send_photo(
                    CHANNEL_ID,
                    photo=photo,
                    caption=formatted,
                    parse_mode="HTML"
                )
                try:
                    os.unlink(local_path)
                except Exception:
                    pass
                return

            # Якщо download 403 — без фото
            await bot.send_message(
                CHANNEL_ID,
                formatted,
                parse_mode="HTML"
            )
            return

        await bot.send_message(
            CHANNEL_ID,
            formatted,
            parse_mode="HTML"
        )
    except Exception:
        await bot.send_message(
            CHANNEL_ID,
            formatted,
            parse_mode="HTML"
        )

async def scheduled_news():
    news_list = get_top_news_for_brief(12)
    to_publish = select_for_publish(news_list)

    for news in to_publish:
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
        recent.append(news.get("title_original", ""))
        save_recent_titles(recent)

    await bot.send_message(
        ADMIN_GROUP_ID,
        f"Проверил новости.\n"
        f"Кандидаты: {len(news_list)}\n"
        f"Авто: {len(to_publish)}\n"
        f"Время: {datetime.now().strftime('%H:%M')}"
    )

async def scheduled_air():
    decision = process_air_cycle()
    if decision.get("action") != "PUBLISH":
        return

    text = format_air_post(decision)
    try:
        await bot.send_message(CHANNEL_ID, text, parse_mode="HTML")
        await bot.send_message(
            ADMIN_GROUP_ID,
            f"Тривога опублікована.\n{decision.get('reason', '')}"
        )
        if decision.get("event_type") == "ALERT_END":
            close_attack()
    except Exception as e:
        print(f"AIR send error: {e}")

async def scheduled_threats():
    try:
        results = poll_new_targets()
    except Exception as e:
        print(f"THREAT poll error: {e}")
        return

    for result in results:
        if result.get("action") not in ("PUBLISH", "UPDATE"):
            continue
        msg = result.get("message")
        if not msg:
            continue
        try:
            await bot.send_message(CHANNEL_ID, msg, parse_mode="HTML")
            await bot.send_message(
                ADMIN_GROUP_ID,
                f"Атака авто: {result.get('action')} / {result.get('reason')}"
            )
        except Exception as e:
            print(f"THREAT send error: {e}")

            
async def main():
    print("Я заработал")

    scheduler.add_job(
        scheduled_brief,
        CronTrigger(hour=7, minute=0, timezone="Europe/Kyiv")
    )
    scheduler.add_job(
        scheduled_news,
        "interval",
        minutes=30
    )
    scheduler.add_job(
        scheduled_evening_digest,
        CronTrigger(hour=22, minute=0, timezone="Europe/Kyiv")
    )

    scheduler.add_job(
        scheduled_air,
        "interval",
        seconds=20
    )
    scheduler.add_job(
        scheduled_air,
        "interval",
        seconds=20
    )

    scheduler.start()
    print("Планувальник запущено")

    await dp.start_polling(bot)
    


if __name__ == "__main__":
    asyncio.run(main())
