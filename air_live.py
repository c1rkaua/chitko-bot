import os
import re

from telethon import TelegramClient, events
from telethon.sessions import StringSession

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
    "надіслати новину", "карта загроз", "мапа загроз",
    "#реклама", "реклама", "aliexpress", "ваканс",
)

HIT_KEYS = (
    "приліт", "прилет", "влучан", "уламк", "склад",
    "пожеж", "загоря", "горить", "вибух",
    "загиб", "поран", "жертв",
    "тцк", "бусиф", "мобіліз", "мобилиз",
    "дтп", "аварі", "авария",
    "атб", "аврора", "нова пошт", "епіцентр", "сільпо", "новус",
    "метро", "маршрутка", "тролейбус", "трамвай",
    "перекрит", "перекрили",
    "світло", "відключен", "отключен", "блекаут",
    "обстріл", "шахед", "бпла по",
    "корруп", "корупц", "хабар",
    "затопи", "затоплен", "обвал",
    "стрілянин", "стрельба",
    "евакуац",
)

SEEN_NEWS = set()


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


def _is_hit(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in HIT_KEYS)


def _news_fp(text: str) -> str:
    words = re.findall(r"[а-яіїєґa-z0-9]+", text.lower())
    return " ".join(words[:12])

def translate_uk(text: str) -> str:
    import requests
    low = text.lower()
    if not re.search(r"[ыэъё]|ться\b|это\b|что\b|после\b|объект", low):
        return text
    key = (os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        print("NEWS live no translate key")
        return text
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if os.getenv("OPENAI_API_KEY") and not os.getenv("XAI_API_KEY"):
        url = "https://api.openai.com/v1/chat/completions"
    try:
        r = requests.post(
            url,
            headers=headers,
            json={
                "model": "grok-3" if "x.ai" in url else "gpt-4o-mini",
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Переклади українською, стиль ЧІТКО. "
                            "Коротко, по суті. Без російської. "
                            "Не вигадуй фактів. Верни лише текст поста."
                        ),
                    },
                    {"role": "user", "content": text[:1500]},
                ],
            },
            timeout=12,
        )
        data = r.json()
        out = data["choices"][0]["message"]["content"].strip()
        return out or text
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
            place_key = (item.get("place") or "").lower()
            fp = item["fp"]
            if place_key in wave["seen"] or fp in wave["seen"]:
                print(f"AIR live skip {fp}")
                continue
            wave["seen"].add(place_key)
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

    @client.on(events.NewMessage(chats=list(NEWS_CHATS)))
    async def on_news(event):
        text_in = (event.raw_text or "").strip()
        if len(text_in) < 25:
            return
        low = text_in.lower()
        if any(s in low for s in NEWS_SKIP):
            print(f"NEWS live skip ad {_chat_name(event)}")
            return
        if wave.get("kyiv") and not _is_hit(text_in):
            print(f"NEWS live silence {_chat_name(event)}")
            return
        if not _is_hit(text_in):
            print(f"NEWS live weak {_chat_name(event)}")
            return
        fp = _news_fp(text_in)
        if not fp or fp in SEEN_NEWS:
            print("NEWS live dup")
            return
        SEEN_NEWS.add(fp)
        if len(SEEN_NEWS) > 200:
            SEEN_NEWS.clear()

        uk = translate_uk(text_in)
        lines = [x.strip() for x in uk.split("\n") if x.strip()]
        if not lines:
            return
        title = re.sub(r"^[⚡️⚡❗!]+", "", lines[0]).strip()[:120]
        body = "\n\n".join(lines[1:])[:700]
        post = f"⚡️ {title}"
        if body:
            post += "\n\n" + body
        post += "\n\nЧІТКО"

        from aiogram.types import MessageEntity, BufferedInputFile
        ents = None
        if pack_entities:
            ents = pack_entities(post, "news")
        if not ents:
            ents = [
                MessageEntity(
                    type="custom_emoji",
                    offset=0,
                    length=2,
                    custom_emoji_id="5237977689968651276",
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
                    post,
                    parse_mode=None,
                    entities=ents,
                )
            print(f"NEWS live sent {_chat_name(event)} {media_kind or 'text'} {title[:40]}")
        except Exception as e:
            print(f"NEWS live send {e}")
            await bot.send_message(channel_id, post)

    await client.start()
    print("AIR live telethon up")
    print("NEWS live chats on")
    await client.run_until_disconnected()
