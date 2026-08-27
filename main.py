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
async def get_nbu_rates():
    try:
        import aiohttp
        url = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "—", "—"
                data = await resp.json()

        usd = next((x for x in data if x.get("cc") == "USD"), None)
        eur = next((x for x in data if x.get("cc") == "EUR"), None)

        usd_rate = f"{usd['rate']:.2f}".replace(".", ",") if usd else "—"
        eur_rate = f"{eur['rate']:.2f}".replace(".", ",") if eur else "—"

        return usd_rate, eur_rate
    except Exception:
        return "—", "—"

# ======================
# Отримання цін на паливо (тимчасово)
# ======================
async def get_fuel_prices():
    return {
        "A-95": 80.50,
        "DP": 91.80,
        "GAS": 43.20
    }
# ======================
# Формування бріфу
# ======================

async def create_morning_brief():
    from datetime import datetime
    import pytz
    
    # Курси і паливо (поки заглушки)
    usd = await get_nbu_rates()
    eur = await get_nbu_rates()
    a95 = "58,40"
    dp = "56,10"
    gas = "34,20"
    
    news_list = get_top_news_for_brief(4)
    
    news_lines = []
    for i, news in enumerate(news_list, 1):
        title = news.get("title_chitko", news.get("title_original", "")).strip()
        news_lines.append(f"{i}. {title}")
    
    news_text = "\n".join(news_lines) if news_lines else "1. Новини оновлюються..."
    
    now = datetime.now(pytz.timezone("Europe/Kyiv"))
    today = now.strftime("%d.%m.%Y")
    
    days = {
        "Monday": "понеділок",
        "Tuesday": "вівторок",
        "Wednesday": "середа",
        "Thursday": "четвер",
        "Friday": "п’ятниця",
        "Saturday": "субота",
        "Sunday": "неділя"
    }
    weekday_ua = days.get(now.strftime("%A"), "")
    
    text = (
        f"<b>ЧІТКО • Ранковий бріф</b>\n"
        f"{today} • {weekday_ua}\n\n"
        f"<b>КУРС НБУ</b>\n"
        f"$ {usd}\n"
        f"€ {eur}\n\n"
        f"<b>ПАЛИВО</b>\n"
        f"А-95 — {a95} ₴\n"
        f"ДП — {dp} ₴\n"
        f"Газ — {gas} ₴\n\n"
        f"<b>ГОЛОВНЕ ЗА НІЧ</b>\n"
        f"{news_text}\n\n"
        f"<b>ЧІТКО. Коротко. По суті.</b>"
    )
    
    return text
    
# ======================
# Команда /brief
# ======================
@dp.message(Command("brief"))
async def cmd_brief(message: Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    
    text = await create_morning_brief()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ APPROVED", callback_data="approve_brief"),
            InlineKeyboardButton(text="❌ DECLINE", callback_data="skip_brief")
        ]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

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
    except Exception as e:
        print(f"AIR send error: {e}")
            
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
        scheduled_evening_digest,
        CronTrigger(hour=22, minute=0, timezone="Europe/Kyiv")
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
