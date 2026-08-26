from news_engine import get_top_news_for_brief, format_news_post, published_ids, save_published_ids
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
    url = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
    
    rates = {}
    for item in data:
        if item["cc"] in ["USD", "EUR", "PLN"]:
            rates[item["cc"]] = round(item["rate"], 2)
    return rates

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
    
    # Курси і паливо (поки залишаємо як було)
    usd = "44,61"
    eur = "52,13"
    a95 = "80,50"
    dp = "91,80"
    gas = "43,20"
    
        # Реальні новини
    news_list = get_top_news_for_brief(4)
    
    news_text = ""
    for i, news in enumerate(news_list, 1):
        # Поки для бріфу залишаємо короткий варіант
        news_text += f"{i}. {news['title_chitko']}\n"
    
    if not news_text:
        news_text = "1. Новини оновлюються...\n"
    
    today = datetime.now().strftime("%d.%m.%Y")
    weekday = datetime.now().strftime("%A")
    
    # Українські дні тижня
    days = {
        "Monday": "понеділок",
        "Tuesday": "вівторок",
        "Wednesday": "середа",
        "Thursday": "четвер",
        "Friday": "п’ятниця",
        "Saturday": "субота",
        "Sunday": "неділя"
    }
    weekday_ua = days.get(weekday, weekday)
    
    text = f"""<b>ЧІТКО</b>
{today} • {weekday_ua}

Доброго ранку

<b>КУРСИ ВАЛЮТ</b>
USD  {usd} ₴
EUR  {eur} ₴

<b>ПАЛИВО</b>
A-95  {a95} ₴/л
ДП    {dp} ₴/л
ГАЗ   {gas} ₴/л

<b>ГОЛОВНЕ ЗА РАНОК</b>
{news_text}
ЧІТКО. КОРОТКО. ПО СУТІ."""
    
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
    
    await message.answer("Собираю новости...")
    
    news_list = get_top_news_for_brief(10)
    auto_published = 0
    
    # Розділяємо
    force = [n for n in news_list if n.get("final_score", 0) >= 90]
    important = [n for n in news_list if 75 <= n.get("final_score", 0) < 90]
    for_approval = [n for n in news_list if 50 <= n.get("final_score", 0) < 75]
    
    # Автопублікація: форс-мажор (до 2) + 1 важлива
    to_auto = force[:2]
    if important:
        to_auto.append(important[0])
    
    for news in to_auto:
        formatted = format_news_post(news)
        image_url = news.get("image_url")
        
        try:
            if image_url:
                await bot.send_photo(CHANNEL_ID, photo=image_url, caption=formatted, parse_mode="HTML")
            else:
                await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
        except:
            await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
        
        published_ids.add(news["event_id"])
        save_published_ids(published_ids)
        auto_published += 1
    
    # На апрув
    for news in (important[1:] + for_approval)[:6]:
        pending_news[news["event_id"]] = news
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ APPROVED", callback_data=f"approve_one_{news['event_id']}"),
            InlineKeyboardButton(text="❌ DECLINE", callback_data=f"skip_one_{news['event_id']}")
        ]])
        
        score = news.get("final_score", 0)
        preview = f"<b>Score: {score}</b>\n\n{format_news_post(news)}"
        await message.answer(preview, reply_markup=keyboard, parse_mode="HTML")
    
    await message.answer(f"Готово. Сам добавил: {auto_published}")
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

@dp.callback_query(F.data.startswith("approve_one_"))
async def approve_one(callback: CallbackQuery):
    event_id = callback.data.replace("approve_one_", "")
    news = pending_news.get(event_id)
    
    if not news:
        await callback.answer("Новина застаріла")
        return
    
    formatted = format_news_post(news)
    image_url = news.get("image_url")
    
    try:
        if image_url:
            await bot.send_photo(CHANNEL_ID, photo=image_url, caption=formatted, parse_mode="HTML")
        else:
            await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
    except:
        await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")

    published_ids.add(news["event_id"])
    save_published_ids(published_ids)
    
    if event_id in pending_news:
        del pending_news[event_id]
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Опубліковано ✅")


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
        f"Опубліковано: <b>{published_count}</b>\n"
        f"Зараз на апруві: <b>{pending_count}</b>\n\n"
        f"Поріг авто: 75+\n"
        f"Форс-мажор: 90+"
    )
    
    await message.answer(text, parse_mode="HTML")

# ======================
# Запуск
# ======================
async def scheduled_brief():
    text = await create_morning_brief()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ APPROVED", callback_data="approve_brief"),
            InlineKeyboardButton(text="❌ DECLINE", callback_data="skip_brief")
        ]
    ])
    await bot.send_message(ADMIN_GROUP_ID, text, reply_markup=keyboard, parse_mode="HTML")

async def scheduled_news():
    news_list = get_top_news_for_brief(10)
    
    force_majeure = [n for n in news_list if n.get("final_score", 0) >= 90]
    important = [n for n in news_list if 75 <= n.get("final_score", 0) < 90]
    
    to_publish = []
    to_publish.extend(force_majeure[:3])
    if important:
        to_publish.append(important[0])
    
    for news in to_publish:
        formatted = format_news_post(news)
        image_url = news.get("image_url")
        
        try:
            if image_url:
                await bot.send_photo(CHANNEL_ID, photo=image_url, caption=formatted, parse_mode="HTML")
            else:
                await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
        except:
            await bot.send_message(CHANNEL_ID, formatted, parse_mode="HTML")
        
        published_ids.add(news["event_id"])
        save_published_ids(published_ids)
    
    await bot.send_message(
        ADMIN_GROUP_ID,
        f"Перевірив новини.\nАвто: {len(to_publish)}\nЧас: {datetime.now().strftime('%H:%M')}"
    )
            
async def main():
    print("Я заработал")

    scheduler.add_job(scheduled_brief, CronTrigger(hour=7, minute=0))
    scheduler.add_job(scheduled_news, 'interval', minutes=30)
    scheduler.start()
    print("Я уже работаю")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
