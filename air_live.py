import os
import re
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from telethon import TelegramClient, events
from telethon.sessions import StringSession

NEWS_EMOJI_ID = "5237977689968651276"
CE_BOLT = "5237977689968651276"

COURSE_CHATS = ("eradarrua", "war_monitor", "k_dvizh", "kievreal1")

NEWS_CHATS = (
    "lachentyt",
    "NovynaUKR",
    "kyivoperat",
    "ENOVUNA",
    "ragnarockkyiv",
    "kyiv_xy",
    "svoiua",
    "truexanewsua",
    "obolon_info",
    "insiderUKR",
    "vanek_nikolaev",
    "uniannet",
    "times_ukraina",
    "k_dvizh",
)

NEWS_SKIP = (
    "підписатися", "подписаться", "присылайте", "присилайте",
    "прислать контент", "прислати контент",
    "надіслати новину", "надіслати контент",
    "надішли близьким", "надішліть близьким",
    "карта загроз", "мапа загроз",
    "#реклама", "реклама", "aliexpress", "ваканс",
    "insider ua", "инсайдер юа",
    "будь в курсі", "будь в курсе",
    "куди летить?", "куди летить",
    "vasylkiv_info",
    "підпишись", "подпишись",
    "тільки оперативна інформація",
    "котики",
    "без фіксації",
)

# Авто в канал — лише космос. Решта слабке.
COSMOS_KEYS = (
    "приліт", "прилет", "влучан", "уламк",
    "склад", "пожеж", "загоря", "горить",
    "загиб", "поран", "жертв",
    "тцк", "бусиф",
    "дтп", "аварі", "авария",
    "атб", "аврора", "нова пошт", "епіцентр", "сільпо", "новус",
    "метро", "стрілянин", "стрельба",
    "евакуац",
)

SEEN_NEWS = set()
NEWS_DAY = {"d": "", "n": 0}
DAY_CAP = 90


def _today():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d")
    return datetime.utcnow().strftime("%Y-%m-%d")


def build_client():
    api_id = int(os.getenv("TG_API_ID") or "0")
    api_hash = (os.getenv("TG_API_HASH") or "").strip()
    session = (os.getenv("TG_SESSION") or "").strip()
    if not api_id or not api_hash or not session:
        print("AIR live skip: no TG_SESSION")
        return None
    return TelegramClient(StringSession(session), api_id, api_hash)


def _chat_name(event) -> str:
    try:
        return event.chat.username or "?"
    except Exception:
        return "?"


def _is_cosmos(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in COSMOS_KEYS)


def _news_fp(text: str) -> str:
    words = re.findall(r"[а-яіїєґa-z0-9]+", text.lower())
    return " ".join(words[:18])


def strip_ads(text: str) -> str:
    text = re.sub(
        r"(?im)^.*(insider\s*ua|прислать контент|прислати контент|"
        r"надіслати новину|надіслати контент|киевский движ|"
        r"київський движ|підписатися|подписаться|"
        r"надішли близьким|vasylkiv_info).*$",
        "",
        text,
    )
    text = re.sub(r"(?i)insider\s*ua\s*\|?\s*", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def translate_uk(text: str) -> str:
    import requests
    text = strip_ads(text)
    key = (os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        print("NEWS live no translate key")
        return text
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    model = "grok-3"
    if os.getenv("OPENAI_API_KEY") and not os.getenv("XAI_API_KEY"):
        url = "https://api.openai.com/v1/chat/completions"
        model = "gpt-4o-mini"
    try:
        r = requests.post(
            url,
            headers=headers,
            json={
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ти редактор каналу ЧІТКО.\n"
                            "Перепиши пост українською своїми словами.\n"
                            "Цифри, імена, адреси, кількість жертв не змінюй і не вигадуй.\n"
                            "Викинь футери: INSIDER UA, Прислать контент, "
                            "Киевский Движ, Надіслати новину, підписатися, посилання t.me.\n"
                            "Не пиши «пишуть пабліки», «за даними».\n"
                            "Перший рядок — заголовок без емодзі.\n"
                            "Далі 5–10 речень. Не обрізай факт посередині речення.\n"
                            "Кожне речення закінчуй крапкою.\n"
                            "Лише українська. Верни тільки текст поста."
                        ),
                    },
                    {"role": "user", "content": text[:4000]},
                ],
            },
            timeout=25,
        )
        out = (r.json()["choices"][0]["message"]["content"] or "").strip()
        print("NEWS live rewrite ok" if out else "NEWS live rewrite empty")
        return strip_ads(out or text)
    except Exception as e:
        print(f"NEWS live translate {e}")
        return text

async def start_live(bot, channel_id, parse_course_line, format_course, pack_entities, wave):
    client = build_client()
    if client is None:
        return

    @client.on(events.NewMessage(chats=list(COURSE_CHATS)))
    async def on_course(event):
        text_in = event.raw_text or ""
        print(f"AIR live {_chat_name(event)}: {text_in[:80]!r}")
        try:
            items = parse_course_line(text_in)
        except Exception as e:
            print(f"AIR live parse {e}")
            return
        if not items:
            return
        if not wave.get("kyiv"):
            print("AIR live skip no siren")
            return
        for item in items:
            fp = item.get("fp") or ""
            if fp in wave["seen"]:
                print(f"AIR live skip {fp}")
                continue
            wave["seen"].add(fp)
            text = format_course(item)
            text = re.sub(r"</?tg-emoji[^>]*>", "", text)
            text = text.replace("<b>", "").replace("</b>", "")
            kind = "loud" if item.get("kind") == "LOUD" else "course"
            ents = pack_entities(text, kind) if pack_entities else None
            try:
                kwargs = {"parse_mode": None}
                if ents:
                    kwargs["entities"] = ents
                await bot.send_message(channel_id, text, **kwargs)
                print(f"AIR live sent {fp}")
            except Exception as e:
                print(f"AIR live send {e}")
                continue
            try:
                from air_main import course_geo
                xy = course_geo(item)
                if xy:
                    await bot.send_location(channel_id, latitude=xy[0], longitude=xy[1])
                    print(f"AIR live geo {item.get('place')} {xy}")
                else:
                    print(f"AIR live geo miss {item.get('place')}")
            except Exception as e:
                print(f"AIR live geo {e}")

    @client.on(events.NewMessage(chats=list(NEWS_CHATS)))
    async def on_news(event):
        text_in = strip_ads((event.raw_text or "").strip())
        if len(text_in) < 40:
            return
        low = text_in.lower()
        if any(s in low for s in NEWS_SKIP):
            print(f"NEWS live skip ad {_chat_name(event)}")
            return
        if "t.me/" in low or "https://" in low:
            print(f"NEWS live skip link {_chat_name(event)}")
            return
        cosmos = _is_cosmos(text_in)
        if wave.get("kyiv") and not cosmos:
            print(f"NEWS live silence {_chat_name(event)}")
            return
        if not cosmos:
            print(f"NEWS live weak {_chat_name(event)}")
            return

        day = _today()
        if NEWS_DAY["d"] != day:
            NEWS_DAY["d"] = day
            NEWS_DAY["n"] = 0
        if NEWS_DAY["n"] >= DAY_CAP:
            print("NEWS live day cap 90")
            return

        fp = _news_fp(text_in)
        if not fp or fp in SEEN_NEWS:
            print("NEWS live dup")
            return
        SEEN_NEWS.add(fp)
        if len(SEEN_NEWS) > 400:
            SEEN_NEWS.clear()

        uk = translate_uk(text_in)
        lines = [x.strip() for x in uk.split("\n") if x.strip()]
        if not lines:
            return
        title = re.sub(r"^[⚡️⚡❗!]+", "", lines[0]).strip()[:180]
        body = "\n\n".join(lines[1:])[:2200]
        post = f"⚡️ {title}"
        if body:
            post += "\n\n" + body
        post += "\n\nЧІТКО"

        from aiogram.types import MessageEntity, BufferedInputFile
        ents = pack_entities(post, "news") if pack_entities else None
        if not ents:
            ents = [
                MessageEntity(
                    type="custom_emoji",
                    offset=0,
                    length=2,
                    custom_emoji_id=NEWS_EMOJI_ID,
                )
            ]

        media_bytes = None
        media_name = "live.bin"
        media_kind = None
        try:
            msg = event.message
            if msg.photo:
                media_bytes = await msg.download_media(bytes)
                media_name, media_kind = "live.jpg", "photo"
            elif msg.video:
                media_bytes = await msg.download_media(bytes)
                media_name, media_kind = "live.mp4", "video"
            elif getattr(msg, "document", None) and (msg.file.mime_type or "").startswith(("image/", "video/")):
                media_bytes = await msg.download_media(bytes)
                media_name = msg.file.name or "live.bin"
                media_kind = "video" if "video" in (msg.file.mime_type or "") else "photo"
        except Exception as e:
            print(f"NEWS live media {e}")

        cap = post[:1024]
        try:
            if media_kind == "photo" and media_bytes:
                await bot.send_photo(
                    channel_id,
                    BufferedInputFile(media_bytes, media_name),
                    caption=cap,
                    parse_mode=None,
                    caption_entities=ents,
                )
            elif media_kind == "video" and media_bytes:
                await bot.send_video(
                    channel_id,
                    BufferedInputFile(media_bytes, media_name),
                    caption=cap,
                    parse_mode=None,
                    caption_entities=ents,
                )
            else:
                await bot.send_message(
                    channel_id,
                    post[:4000],
                    parse_mode=None,
                    entities=ents,
                )
            NEWS_DAY["n"] += 1
            print(f"NEWS live sent {_chat_name(event)} {media_kind or 'text'} {title[:40]} day={NEWS_DAY['n']}")
        except Exception as e:
            print(f"NEWS live send {e}")

    await client.start()
    print("AIR live telethon up")
    print("NEWS live chats on")
    await client.run_until_disconnected()
