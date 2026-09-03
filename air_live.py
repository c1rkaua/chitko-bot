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
    "пожеж", "загиб", "поран", "тцк", "бусиф",
    "дтп", "аварі", "вибух", "атб", "аврора",
    "нова пошт", "епіцентр",
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
        title = text_in.split("\n")[0][:120]
        body = "\n".join(text_in.split("\n")[1:]).strip()
        post = f"⚡️ {title}"
        if body:
            post += "\n\n" + body[:700]
        post += "\n\nЧІТКО"
        try:
            await bot.send_message(channel_id, post)
            print(f"NEWS live sent {_chat_name(event)} {title[:50]}")
        except Exception as e:
            print(f"NEWS live send {e}")

    await client.start()
    print("AIR live telethon up")
    print("NEWS live chats on")
    await client.run_until_disconnected()
