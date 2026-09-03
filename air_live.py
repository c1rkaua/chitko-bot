import os
import re

from telethon import TelegramClient, events
from telethon.sessions import StringSession

COURSE_CHATS = ("eradarrua", "war_monitor", "k_dvizh", "kievreal1")


def build_client():
    api_id = int(os.getenv("TG_API_ID") or "0")
    api_hash = (os.getenv("TG_API_HASH") or "").strip()
    session = (os.getenv("TG_SESSION") or "").strip()
    if not api_id or not api_hash or not session:
        print("AIR live skip: no TG_SESSION")
        return None
    return TelegramClient(StringSession(session), api_id, api_hash)


async def start_live(bot, channel_id, parse_course_line, format_course, pack_entities, wave):
    client = build_client()
    if client is None:
        return

    @client.on(events.NewMessage(chats=list(COURSE_CHATS)))
    async def on_course(event):
        text_in = event.raw_text or ""
        chat = ""
        try:
            chat = event.chat.username or ""
        except Exception:
            chat = "?"
        print(f"AIR live {chat}: {text_in[:80]!r}")
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

    await client.start()
    print("AIR live telethon up")
    await client.run_until_disconnected()
