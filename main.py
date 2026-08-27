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
        return float(s.replace(",", ".").replace(" ", ""))

    try:
        html = requests.get(
            "https://www.nefterynok.info/fuel-lpg",
            headers=headers,
            timeout=6,
        ).text
    except Exception as e:
        print(f"FUEL fetch error: {e}")
        return out

    m95 = re.search(
        r"Бензин А-95(?!\+)\s*(?:\*\*)?\s*(\d+[.,]\d{2})\s*грн",
        html,
        re.I,
    )
    mdp = re.search(
        r"Дизель(?:не пальне)?\s*(?:\*\*)?\s*(\d+[.,]\d{2})\s*грн",
        html,
        re.I,
    )
    mlpg = re.search(
        r"Автогаз(?:\s*\(LPG\))?\s*(?:\*\*)?\s*(\d+[.,]\d{2})\s*грн",
        html,
        re.I,
    )

    if m95:
        out["a95"] = to_float(m95.group(1))
    if mdp:
        out["dp"] = to_float(mdp.group(1))
    if mlpg:
        out["lpg"] = to_float(mlpg.group(1))

    print(f"FUEL parsed: {out}")
    return out
# ======================
# Формування бріфу
# ======================
def format_morning_brief_text(rates, fuel, headlines: list) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    days = [
        "понеділок",
        "вівторок",
        "середа",
        "четвер",
        "п’ятниця",
        "субота",
        "неділя",
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
        title = (h.get("title_chitko") or h.get("title_original") or "").strip()
        title = title.rstrip(".")
        lines.append(f"{i}. {title}")

    lines += ["", "<b>ЧІТКО. Коротко. По суті.</b>"]
    return "\n".join(lines)

def render_brief_card(rates: dict, fuel: dict, headlines: list, title_news: str = "ГОЛОВНЕ ЗА РАНОК") -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from PIL import Image, ImageDraw, ImageFont
    import os

    W, H = 1080, 1620
    BG = (0, 0, 0)
    GOLD = (201, 162, 39)
    WHITE = (255, 255, 255)
    GREEN = (46, 204, 113)
    RED = (231, 76, 60)
    GRAY = (180, 180, 180)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    def font(size, bold=False):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
        for p in paths:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()

    f_logo = font(92, True)
    f_sub = font(28, True)
    f_date = font(32)
    f_hello = font(52, True)
    f_sec = font(28, True)
    f_row = font(36)
    f_row_b = font(36, True)
    f_news_t = font(34, True)
    f_news = font(28)
    f_foot = font(24)

    def center(text, y, fnt, fill=WHITE):
        box = d.textbbox((0, 0), text, font=fnt)
        x = (W - (box[2] - box[0])) // 2
        d.text((x, y), text, font=fnt, fill=fill)

    def line(y):
        d.line((120, y, W - 120, y), fill=GOLD, width=2)

    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    days = ["понеділок", "вівторок", "середа", "четвер", "п’ятниця", "субота", "неділя"]
    date_s = f"{now.day} {['січня','лютого','березня','квітня','травня','червня','липня','серпня','вересня','жовтня','листопада','грудня'][now.month-1]} {now.year}"

    y = 70
    center("ЧІТКО", y, f_logo, WHITE)
    y = 175
    d.line((360, y, W - 360, y), fill=GOLD, width=3)
    center("ЧІТКО MORNING BRIEF", y + 20, f_sub, GOLD)
    center(date_s, y + 60, f_date, GRAY)
    center("Доброго ранку", y + 120, f_hello, WHITE)
    line(y + 200)

    y = 430
    center("КУРС ВАЛЮТ (НБУ)", y, f_sec, GOLD)
    y += 55

    def money_row(label, value, delta, yy):
        d.text((120, yy), label, font=f_row, fill=WHITE)
        val = fmt_uah(value) + " ₴"
        box = d.textbbox((0, 0), val, font=f_row_b)
        d.text((W - 280 - (box[2] - box[0]), yy), val, font=f_row_b, fill=GOLD)
        if delta is None:
            return
        color = GREEN if delta > 0 else (RED if delta < 0 else GRAY)
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        d.text((W - 160, yy), arrow, font=f_row_b, fill=color)

    money_row("USD/UAH", rates.get("usd"), rates.get("usd_delta"), y)
    money_row("EUR/UAH", rates.get("eur"), rates.get("eur_delta"), y + 55)
    money_row("PLN/UAH", rates.get("pln"), rates.get("pln_delta"), y + 110)

    y = 720
    line(y)
    center("ПАЛИВО (середні ціни по АЗС)", y + 25, f_sec, GOLD)
    y += 80
    money_row("A-95", fuel.get("a95"), None, y)
    money_row("ДП", fuel.get("dp"), None, y + 55)
    money_row("Автогаз", fuel.get("lpg"), None, y + 110)

    y = 1040
    line(y)
    center(title_news, y + 25, f_sec, GOLD)
    y += 90

    for i, h in enumerate(headlines[:3], 1):
        t = (h.get("title_chitko") or h.get("title_original") or "").strip()
        t = t.rstrip(".")
        if len(t) > 90:
            t = t[:87] + "…"
        d.ellipse((120, y + 6, 162, y + 48), outline=GOLD, width=2)
        tw = d.textbbox((0, 0), str(i), font=f_news_t)
        d.text((141 - (tw[2] - tw[0]) // 2, y + 10), str(i), font=f_news_t, fill=GOLD)
        d.text((185, y + 8), t, font=f_news, fill=WHITE)
        y += 90

    line(H - 110)
    center("ЧІТКО. КОРОТКО. ПО СУТІ.", H - 80, f_foot, GRAY)

    path = "/tmp/chitko_brief.jpg"
    img.save(path, "JPEG", quality=92)
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
        path = render_brief_card(rates, fuel, headlines)
        caption = format_morning_brief_text(rates, fuel, headlines)
        await message.answer_photo(
            photo=FSInputFile(path),
            caption=caption,
            parse_mode="HTML",
        )
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
    await message.answer("Збираю вечірній дайджест...")
    await scheduled_evening_digest()

@dp.message(Command("air"))
async def cmd_air(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return

    decision = process_air_cycle()
    current = decision.get("current", {})
    status = (
        f"Київ: {'тривога' if current.get('kyiv') else 'тихо'}\n"
        f"Область: {'тривога' if current.get('oblast') else 'тихо'}\n"
        f"Action: {decision.get('action')}\n"
        f"{decision.get('reason', '')}"
    )
    await message.answer(status)

    if decision.get("action") == "PUBLISH":
        await bot.send_message(
            CHANNEL_ID,
            format_air_post(decision),
            parse_mode="HTML"
        )

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
    news_list = get_top_news_for_brief(20)

    # Беремо сильні, але не обов'язково breaking
    items = []
    for n in news_list:
        score = n.get("final_score", 0)
        cat = n.get("category") or get_news_category(n.get("title_original", ""))
        if cat == "sport":
            continue
        if score < 50:
            continue
        items.append(n)

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
