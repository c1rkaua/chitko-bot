import feedparser
import hashlib
from datetime import datetime, timezone
from dateutil import parser as date_parser
import re
import json
import os

PUBLISHED_FILE = "published_ids.json"

TG_SOURCES = {
    "lachentyt": {"name": "Лачен пише", "trust": 9.8, "allow_national": True},
    "NovynaUKR": {"name": "НОВИНА", "trust": 9.7, "allow_national": True},
    "kyivoperat": {"name": "Київ Оперативний", "trust": 9.8, "allow_national": False},
    "k_dvizh": {"name": "Киевский Движ", "trust": 9.8, "allow_national": False},
    "ENOVUNA": {"name": "Є Новина", "trust": 9.6, "allow_national": True},
    "ragnarockkyiv": {"name": "Ragnarok Kyiv", "trust": 9.6, "allow_national": False},
    "kyiv_xy": {"name": "Kyiv XY", "trust": 9.5, "allow_national": False},
    "svoiua": {"name": "Свої", "trust": 9.5, "allow_national": True},
    "truexanewsua": {"name": "Труха Україна", "trust": 9.7, "allow_national": True},
    "obolon_info": {"name": "Оболонь INFO", "trust": 9.8, "allow_national": False},
    "insiderUKR": {"name": "Інсайдер UA", "trust": 9.6, "allow_national": True},
    "vanek_nikolaev": {"name": "Миколаївський Ванек", "trust": 9.7, "allow_national": True},
    "uniannet": {"name": "УНІАН", "trust": 9.4, "allow_national": True},
    "times_ukraina": {"name": "Times of Ukraine", "trust": 9.2, "allow_national": True},
}

CIVILIAN_KEYS = [
    "дтп", "аварі", "авария", "аварию", "зіткнен", "столкновен",
    "наїхав", "сбил", "перекинув", "перевернув",
    "тцк", "бусифік", "бусифик", "облав", "мобіліз", "мобилиз",
    "військкомат", "повістк", "резерв+",
    "пожеж", "пожар", "загорян", "горить", "дим ", "задимлен",
    "вибух", "взрыв", "вибух газу", "взрыв газа",
    "обвал", "завал", "затопи", "затоп", "підтоплен", "прорив труб",
    "поранен", "ранен", "загинул", "загибл", "погиб", "жертв",
    "еваку", "рятувальн", "дснс", "швидк", "швидка",
    "стрілянин", "стрельба", "затриман", "задержан",
    "пограбув", "крадіжк", "ограблен", "розбійн",
    "хабар", "взятк", "корупц", "коррупц",
    "світло", "отключен", "відключен", "блекаут", "графік відключ",
    "тариф", "пенсі", "пенси", "субсиді", "мінімалк",
    "газ", "опаленн", "тепло", "гаряч", "холодн вод",
    "водоканал", "без води", "без света", "без світл",
    "маршрутка", "автобус", "тролейбус", "троллейбус", "трамва",
    "метро", "фунікулер", "ескалатор", "станція",
    "київпастранс", "не курсує", "знято з маршрут", "затори",
    "перекрит", "перекрито рух", "пробка", "кільцев",
    "міст ", "мосту", "вокзал", "аеропорт", "жулян",
    "київ", "киев", "оболон", "подол", "поділ", "голосіїв", "дарниц",
    "троєщин", "троещин", "деснян", "погреб", "бровар",
    "бориспіл", "бориспол", "вишгород", "дврз", "позняк", "осокорк",
    "святошин", "нивк", "борщаг", "теремк", "печерськ", "солом",
    "ірпін", "гостомл", "вишнев", "чабан",
    "влучан", "уламк", "приліт", "прилет", "шахед", "бпла",
    "склад", "депо", "залізниц", "укрзаліз",
    "атб", "сільпо", "фора", "новус", "епіцентр", "розетка",
    "нова пошт", "нової пошт", "укрпошт", "відділен",
    "аптек", "лікарн", "больниц", "поліклінік", "операці",
    "школ", "садочок", "дитсад", "універстет", "гуртжит",
    "жк ", "осбб", "багатоповерх", "квартир", "під'їзд", "ліфт",
    "оренда", "іпотек", "комуналк",
    "банк", "банкомат", "картк", "приват", "монобанк", "ощад",
    "черг", "запис ", "паспорт", "закордонн", "цнап", "дія ",
    "корд", "розшук", "зникл", "евакуац", "евкуац",
    "безробіт", "зарплат", "штраф", "пдр", "фантом",
    "смаг", "злива", "бурев", "ожелед", "заморозк",
    "скажен", "безпритульн", "притулок",
    "ринок", "цін на", "яйц", "молоко", "хліб", "бензин", "дизель", "азс",
]

TRACKER_SKIP = [
    "на центр", "гучно на", "відбій", "отбой",
    "тривога йбн", "повітряна тривога", "air siren",
    "онлайн-карта", "карта ціл",
    "курсом на", "2 на бровари", "на бровари курсом",
    "полетів в область",
    "продаж дуплекс", "продаж квартир", "продаж таунхаус",
    "забудовник", "новобудов", "м²", "кв.м",
    "розтермінуван", "іпотека від",
    "polish hill", "польський хілл",
    "купити квартир", "власна територія та продумані",
    "офіційний сайт", "ph.kiev",
    "експерт попереджає", "щоденних каб",
    "aliexpress", "алиэкспресс", "аліекспрес",
    "arduino", "ардуіно",
    "пайк", "пайкою", "мікросхем", "резистор",
    "radio aliexpress", "канал про електронік",
    "розумного будинку", "розумного дому",
]

WAR_FILLER_KEYS = [
    "генштаб зведення", "за добу знешкоджено", "окупанти не полишають",
    "триває відсіч", "на купянському",
    "supercam", "суперкам",
    "захищаються від", "дронів-перехоплювач",
    "путін заявив", "путин заявил",
    "звільнення донбасу триває",
]

PUBLISHED_FILE = "published_ids.json"

LAST_TG_STATS = {
    "checked": 0,
    "skipped": 0,
    "kept": 0,
    "by_channel": {},
    "when": "",
}

def normalize_title(text: str) -> str:
    import re
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    repl = {
        "унаслідок": "внаслідок",
        "в результате": "внаслідок",
        "дівчинк": "дитин",
        "дівчинц": "дитин",
        "хлопчик": "дитин",
        "хлопця": "дитин",
        "дитина": "дитин",
        "дитини": "дитин",
        "дітей": "дитин",
        "школяр": "дитин",
        "столичн": "київ",
        "столиці": "київ",
        "столиця": "київ",
        "м київ": "київ",
        "місті києв": "київ",
        "оболонськ": "оболон",
        "печерськ": "печерськ",
        "святошинськ": "святошин",
        "дарницьк": "дарниц",
        "деснянськ": "деснян",
        "голосіївськ": "голосіїв",
        "солом янськ": "солом",
        "подільськ": "поділ",
        "безпілотник": "бпла",
        "безпілотн": "бпла",
        "дрона": "бпла",
        "дронів": "бпла",
        "дрони": "бпла",
        "дрон ": "бпла ",
        "шахед": "бпла",
        "shahed": "бпла",
        "закупівл": "закуп",
        "закупок": "закуп",
        "тендер": "закуп",
        "прозорро": "закуп",
        "prozorro": "закуп",
        "автозаправ": "азс",
        "заправк": "азс",
        "заправн": "азс",
        "азс": "азс",
        "дтп": "дтп",
        "аварі": "дтп",
        "авария": "дтп",
        "зіткнен": "дтп",
        "столкновен": "дтп",
        "наїхав": "дтп",
        "збив пішохода": "дтп",
        "тцк": "тцк",
        "тцк та сп": "тцк",
        "бусифік": "тцк",
        "бусифікац": "тцк",
        "мобіліз": "тцк",
        "мобилиз": "тцк",
        "врученн повіст": "тцк",
        "повістки": "тцк",
        "пожеж": "пожеж",
        "пожар": "пожеж",
        "займання": "пожеж",
        "спалахн": "пожеж",
        "вибух газу": "вибух",
        "взрыв газа": "вибух",
        "детонац": "вибух",
        "приліт": "удар",
        "попадання": "удар",
        "влучан": "удар",
        "обстріл": "удар",
        "відключен": "світло",
        "отключен": "світло",
        "блекаут": "світло",
        "графік відключ": "світло",
        "електроенерг": "світло",
        "світло ": "світло ",
        "хабар": "корупц",
        "взятк": "корупц",
        "корупц": "корупц",
        "коррупц": "корупц",
        "набу": "корупц",
        "пансіонат": "пансіонат",
        "будинок престар": "пансіонат",
        "мила": "мила",
        "чиста вода": "водазавод",
        "бутильован": "водазавод",
        "питн": "водазавод",
        "завод": "завод",
        "підприємств": "завод",
        "бізнес": "завод",
        "мила": "мила",
        "милі": "мила",
        "припинив робот": "стоп",
        "зупинив робот": "стоп",
        "зупинила виробниц": "стоп",
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    text = re.sub(r"[^\wа-яіїєґ0-9]+", " ", text, flags=re.I)
    stop = {
        "в", "у", "на", "та", "і", "й", "по", "з", "із", "від", "для",
        "що", "як", "це", "після", "через", "було", "була", "були",
        "яка", "який", "які", "зазнав", "зазнала", "поранена", "поранену",
        "ризик", "ризики", "знову", "під", "загрозою", "загроза",
        "повідомляє", "повідомили", "змі", "рбк", "суспільне",
        "заявив", "заявила", "кажуть", "сталося", "сталась",
    }
    return " ".join(w for w in text.split() if w not in stop and len(w) > 1)

def story_tokens(text: str) -> set:
    norm = normalize_title(text)
    return {w for w in norm.split() if len(w) >= 4}


def is_same_story(a: str, b: str) -> bool:
    sa, sb = story_tokens(a), story_tokens(b)
    if not sa or not sb:
        return False
    inter = sa & sb
    if len(inter) >= 3:
        return True
    j = len(inter) / max(1, min(len(sa), len(sb)))
    if j >= 0.45 and len(inter) >= 2:
        return True
    return False


def news_fingerprint(news: dict) -> str:
    return " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        (news.get("text") or news.get("body") or "")[:280],
    ])


def is_breaking(news: dict) -> bool:
    score = float(news.get("final_score") or 0)
    blob = " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        news.get("text") or "",
        news.get("body") or "",
    ]).lower()
    if any(x in blob for x in (
        "вчора", "позавчора", "напередодні",
        "вшанувал", "пам'ять", "память", "меморіал",
        "забіг", "алея пам", "день пам", "поклали квіт",
        "непал", "китай", "інді", "пакистан",
        "голівуд", "оскар", "повін",
    )):
        return False
    keys = [
        "тривога в києві",
        "балістик по києв",
        "масована атака",
        "удар по києву",
        "приліт у києв",
    ]
    return score >= 88 and any(k in blob for k in keys)

HIT_PLACE = (
    "київ", "киев", "києв",
    "троєщин", "троещин", "деснян", "погреб", "бровар",
    "бориспіл", "бориспол", "бориспіль",
    "оболон", "почайн", "мінськ", "минск", "вигурів",
    "печерськ", "печерск", "поділ", "подол", "липк",
    "позняк", "осокорк", "дарниц", "березняк", "русанів",
    "святошин", "нивк", "борщаг", "білич", "белич", "академміст",
    "голосіїв", "голосеев", "теремк", "феофан", "деміїв", "демиев",
    "солом'ян", "солом’ян", "шуляв", "відрадн", "жулян", "карат",
    "куренів", "сирець", "сирец", "лук'ян", "лук’ян",
    "воскресен", "лісов", "червоний хутір", "дврз",
    "вишнев", "вишгород", "чайк", "гнідин", "петроп",
    "гостомл", "ірпін", "ірпен", "буч", "ворзел", "коцюбин",
    "чабан", "вишеньк", "обухів", "українк", "козин",
    "фастів", "васильк", "білогородк", "софіївськ",
    "одес", "харков", "харків", "дніпр", "львів", "запоріж",
    "миколаїв", "херсон", "вінниц", "черніг", "черкас",
    "полтав", "сум", "житом", "рівн", "луцьк", "терноп",
    "івано-фран", "ужгород", "кропивниц", "крив", "маріупол",
)

HIT_EVENT = (
    "склад", "пожеж", "пожар", "горить", "загорян", "спалах",
    "приліт", "влучан", "уламк", "атак", "удар", "вибух", "взрыв",
    "загибл", "загинул", "загинув", "загинула", "загинули",
    "вбит", "загибл", "жертв", "поранен", "постраждал",
    "еваку", "рятувальн", "дснс", "завал", "заблокован",
    "зруйнов", "разруш", "багатоповерх", "п’ятиповерх", "п'ятиповерх",
    "житлов", "під'їзд", "подъезд", "квартир",
    "депо", "залізниц", "железн",
    "дтп", "аварі", "авария", "зіткнен", "наїхав", "збив",
    "перекинув", "перевернув", "згорів",
    "перекрит", "перекрил", "обмежен рух", "перекрито рух",
    "не курсує", "не курсуют", "зупинен рух", "не ходит",
    "не ходить", "знято з маршрут", "зламав", "злетів з рейок",
    "зійшов з рейок", "задимлен", "задимлення", "затопил",
    "підтоплен", "прорив", "аварія на мереж", "без світл",
    "без воды", "без води", "без тепла", "без газу", "без газа",
    "відключен", "обстріл", "шахед", "бпла",
    "тцк", "бусифік", "облав",
)

HIT_BIZ = (
    "азс", "заправк", "банк", "відділен", "банкомат",
    "тц ", "трц", "торговельн", "супермаркет", "гіпермаркет",
    "аптек", "пошт", "логіст", "термінал", "склад",
    "атб", "сільпо", "фора", "novus", "varus", "metro cash",
    "auchan", "ашан", "розетка", "rozetka", "comfy", "фокстрот",
    "алло", "епіцентр", "леруа", "окко", "wog", "socar", "shell",
    "приват", "ощад", "монобанк", "нова пошт", "нової пошт",
    "укрпошт", "укрзаліз", "залізниц", "депо", "вокзал",
    "станція метро", "метро ", "метрополітен", "вестибюл",
    "переход метро", "ескалатор",
    "маршруток", "маршрутки", "маршрутка", "автобус",
    "тролейбус", "троллейбус", "трамва", "фунікулер", "фуникулер",
    "київпастранс", "киевпастранс", "автостанц", "автовокзал",
    "зупинка", "остановка", "кінцева",
    "міст ", "мосту", "моста ", "шляхопровід", "розв'язк", "развязк",
    "набережн", "проспект", "кільцев",
    "аеропорт", "аэропорт", "жулян", "бориспільськ",
    "лікарн", "больниц", "поліклінік", "швидк", "швидка",
    "школ", "садочок", "дитсад", "універстет", "універсітет",
    "гуртожит", "жк ", "осбб",
    "ринок", "базар", "церкв", "храм",
    "тец", "котельн", "водоканал", "укренерго", "дтек", "київенерго",
    "київводоканал", "газмереж",
)


def is_hit_story(news: dict) -> bool:
    t = " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        news.get("text") or "",
        news.get("body") or "",
    ]).lower()
    if not any(x in t for x in HIT_EVENT):
        return False
    return any(x in t for x in HIT_BIZ) or any(x in t for x in HIT_PLACE)

def is_hit_story(news: dict) -> bool:
    t = " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        news.get("text") or "",
        news.get("body") or "",
    ]).lower()
    if not any(x in t for x in HIT_EVENT):
        return False
    return any(x in t for x in HIT_BIZ) or any(x in t for x in HIT_PLACE)

def extract_tg_media(chunk: str) -> dict:
    import re

    videos = []
    seen_v = set()
    patterns = (
        r'https://cdn\d+\.telesco\.pe/file/[^"\'\s>]+\.mp4[^"\'\s>]*',
        r'https://cdn\d+\.telegram-cdn\.org/file/[^"\'\s>]+\.mp4[^"\'\s>]*',
        r'src="(https://cdn\d+\.(?:telesco\.pe|telegram-cdn\.org)/file/[^"]+)"',
        r'video_player[^>]+src="([^"]+)"',
    )
    for pat in patterns:
        for u in re.findall(pat, chunk or "", re.I):
            if u.startswith("http") is False:
                continue
            ul = u.lower()
            if "userpic" in ul or "emoji" in ul or u in seen_v:
                continue
            if ".mp4" not in ul and "video" not in ul:
                continue
            seen_v.add(u)
            videos.append(u)

    photos = []
    seen_p = set()
    parts = re.split(r"tgme_widget_message_photo", chunk or "")
    for block in parts[1:]:
        head = block[:300].lower()
        if "userpic" in head or "emoji" in head:
            continue
        raw = re.findall(
            r"background-image:url\('?(https?://cdn\d+\.(?:telesco\.pe|telegram-cdn\.org)/file/[^')\s]+)'?\)",
            block,
        )
        for u in raw:
            ul = u.lower()
            if ".mp4" in ul or "emoji" in ul or "userpic" in ul:
                continue
            if u not in seen_p:
                seen_p.add(u)
                photos.append(u)

    print(f"TG media v={len(videos)} p={len(photos)}")
    return {
        "photos": photos[:10],
        "videos": videos[:4],
        "video": videos[0] if videos else None,
    }

def fetch_tg_channel_posts() -> list:
    global LAST_TG_STATS
    import hashlib
    import re
    import requests
    from datetime import datetime, timezone, timedelta

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    max_age = timedelta(hours=1)
    now = datetime.now(timezone.utc)
    out = []
    LAST_TG_STATS["checked"] = 0
    LAST_TG_STATS["skipped"] = 0
    LAST_TG_STATS["kept"] = 0
    LAST_TG_STATS["by_channel"] = {}
    LAST_TG_STATS["when"] = datetime.now().strftime("%H:%M")

    extra_skip = (
        "підписатися", "подписаться", "присылайте", "присилайте",
        "надіслати новину", "карта загроз", "мапа загроз",
        "live map", "онлайн-карта", "обстановка_kyiv",
        "гучно на центр", "поки чисто", "ще пуски",
    )

    order = [
        "lachentyt",
        "NovynaUKR",
        "kyivoperat",
        "k_dvizh",
        "ENOVUNA",
        "ragnarockkyiv",
        "kyiv_xy",
        "svoiua",
        "truexanewsua",
        "obolon_info",
        "insiderUKR",
    ]
    rest = [u for u in TG_SOURCES if u not in order]
    names = [u for u in order if u in TG_SOURCES] + rest

    for username in names:
        meta = TG_SOURCES[username]
        kept = 0
        html = ""
        try:
            html = requests.get(f"https://t.me/s/{username}", headers=headers, timeout=10).text
            if "tgme_widget_message" not in html:
                html = requests.get(
                    f"https://r.jina.ai/http://t.me/s/{username}",
                    headers=headers,
                    timeout=15,
                ).text
        except Exception as e:
            print(f"TG {username}: {e}")
            LAST_TG_STATS["by_channel"][username] = {"html": 0, "chunks": 0, "kept": 0}
            continue

        messages = re.findall(
            r'class="tgme_widget_message[^"]*"(.*?)class="tgme_widget_message_footer',
            html,
            flags=re.I | re.S,
        )
        LAST_TG_STATS["checked"] += len(messages)
        print(f"TG {username}: html={len(html)} chunks={len(messages)}")

        for raw in messages[:8]:
            dt_m = re.search(r'datetime="([^"]+)"', raw)
            if dt_m:
                try:
                    published = datetime.fromisoformat(dt_m.group(1).replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    age = now - published
                    if age > max_age or age.total_seconds() < -120:
                        LAST_TG_STATS["skipped"] += 1
                        print(f"TG old skip {username} {dt_m.group(1)}")
                        continue
                except Exception:
                    pass

            text_bits = re.findall(
                r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                raw,
                flags=re.I | re.S,
            )
            blob = " ".join(text_bits) if text_bits else raw
            text = re.sub(r"<br\s*/?>", "\n", blob, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            text = re.sub(r"підписатися.*", "", text, flags=re.I)
            text = re.sub(r"присылайте.*", "", text, flags=re.I)
            text = text.strip()
            if len(text) < 25:
                LAST_TG_STATS["skipped"] += 1
                continue
            low = text.lower()
            if any(k in low for k in TRACKER_SKIP):
                LAST_TG_STATS["skipped"] += 1
                continue
            if any(k in low for k in WAR_FILLER_KEYS):
                LAST_TG_STATS["skipped"] += 1
                continue
            if any(k in low for k in extra_skip):
                LAST_TG_STATS["skipped"] += 1
                continue
            if username == "k_dvizh" and any(k in low for k in ("летить", "курс на", "шахед на")):
                if not any(k in low for k in ("влучан", "пожеж", "склад", "приліт", "руйнув", "загиб")):
                    LAST_TG_STATS["skipped"] += 1
                    continue
            local = any(k in low for k in CIVILIAN_KEYS)
            if not local and not meta.get("allow_national"):
                LAST_TG_STATS["skipped"] += 1
                continue

            media = extract_tg_media(raw)
            title = text.split(".")[0].strip()[:140]
            event_id = hashlib.md5(f"tg:{username}:{title[:80]}".encode()).hexdigest()
            trust = float(meta.get("trust") or 8.6)
            try:
                score = float(calculate_importance(title, trust))
            except Exception:
                score = 70.0
            if is_hit_story({"title": title, "text": text}):
                score = max(score, 92)
            news = {
                "event_id": event_id,
                "title": title,
                "title_original": title,
                "title_chitko": title,
                "text": text[:800],
                "summary": text[:800],
                "body": text[:800],
                "link": f"https://t.me/{username}",
                "source": meta.get("name") or username,
                "source_name": meta.get("name") or username,
                "image_url": media["photos"][0] if media["photos"] else None,
                "media_urls": media["photos"],
                "video_url": media["video"],
                "video_urls": media.get("videos") or [],
                "final_score": score,
            }
            news = apply_editorial_caps(news)
            out.append(news)
            kept += 1
            LAST_TG_STATS["kept"] += 1

        LAST_TG_STATS["by_channel"][username] = {
            "html": len(html),
            "chunks": len(messages),
            "kept": kept,
        }
        print(f"TG {username}: kept {kept}")

    return out

def load_published_ids():
    if os.path.exists(PUBLISHED_FILE):
        try:
            with open(PUBLISHED_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

RECENT_TITLES_FILE = "recent_titles.json"


def load_recent_titles() -> list:
    if not os.path.exists(RECENT_TITLES_FILE):
        return []
    try:
        with open(RECENT_TITLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_recent_titles(titles: list):
    titles = titles[-200:]
    with open(RECENT_TITLES_FILE, "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False)


def is_material_update(old_title: str, new_title: str) -> bool:
    markers = [
        "загибл", "поранен", "еваку", "підтверд", "офіційно",
        "збільш", "зменш", "завершен", "віднов", "ліквідован",
        "затриман", "оголошен", "набув чинност", "постражда"
    ]
    new_l = new_title.lower()
    old_l = old_title.lower()
    new_has = any(m in new_l for m in markers)
    old_has = any(m in old_l for m in markers)
    return new_has and not old_has

def save_published_ids(ids):
    with open(PUBLISHED_FILE, "w") as f:
        json.dump(list(ids)[-400:], f)

published_ids = load_published_ids()
def is_similar_title(title1: str, title2: str) -> bool:
    t1 = set(title1.lower().split())
    t2 = set(title2.lower().split())
    if not t1 or not t2:
        return False
    intersection = len(t1 & t2)
    union = len(t1 | t2)
    return (intersection / union) > 0.6

# ====================== ДЖЕРЕЛА ======================
RSS_SOURCES = {
    "Suspilne": {
        "url": "https://suspilne.media/rss/all.rss",
        "trust": 9.8,
        "class": "A"
    },
    "Ukrainska Pravda": {
        "url": "https://www.pravda.com.ua/rss/",
        "trust": 9.6,
        "class": "A"
    },
    "Babel": {
        "url": "https://babel.ua/rss",
        "trust": 9.4,
        "class": "A-"
    },
    "Hromadske": {
        "url": "https://hromadske.ua/rss",
        "trust": 9.3,
        "class": "A-"
    },
    "Radio Svoboda": {
        "url": "https://www.radiosvoboda.org/api/z-pqoilerttqi",
        "trust": 9.5,
        "class": "A"
    },
    "Ukrinform": {
        "url": "https://www.ukrinform.ua/rss/news",
        "trust": 9.0,
        "class": "B+"
    }
}

# ====================== ДОПОМІЖНІ ФУНКЦІЇ ======================

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_event_id(title: str) -> str:
    base = re.sub(r"[^a-zA-Zа-яА-Я0-9 ]", "", title.lower())
    base = "_".join(base.split()[:8])
    return hashlib.md5(base.encode()).hexdigest()[:12]


def calculate_freshness(published_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    
    delta_minutes = (now - published_at).total_seconds() / 60

    if delta_minutes <= 5:
        return 1.0
    elif delta_minutes <= 15:
        return 0.95
    elif delta_minutes <= 30:
        return 0.85
    elif delta_minutes <= 60:
        return 0.70
    elif delta_minutes <= 180:
        return 0.50
    else:
        return 0.30


def calculate_importance(title: str, source_trust: float = 8.0) -> float:
    t = title.lower()
    score = 35.0  # база

    # --- P1: війна / безпека ---
    if any(w in t for w in ["масован", "ракетн", "балістик", "шахед", "комбінован"]):
        score += 45
    elif any(w in t for w in ["ракет", "дрон", "бпла", "удар", "обстріл", "вибух", "ппо", "тривог"]):
        score += 35
    elif any(w in t for w in ["еваку", "постражда", "загибл", "поранен"]):
        score += 28

    # --- P1: ТЦК / мобілізація ---
    if any(w in t for w in ["тцк", "мобілізац", "повістк", "бусифікац", "відстроч", "бронюван", "влк", "резерв+"]):
        score += 40

    # --- P1: економіка / енергетика ---
    if any(w in t for w in ["блекаут", "відключен світл", "аварійн відключ"]):
        score += 38
    elif any(w in t for w in ["нбу", "обліков ставка", "курс дол", "курс євро", "тариф", "подат", "бюджет"]):
        score += 30
    elif any(w in t for w in ["енерго", "відключен", "світло", "електро"]):
        score += 22

    # --- P2: влада / рішення ---
    if any(w in t for w in ["кабмін", "верховн рад", "закон набув", "указ президент", "підписав закон"]):
        score += 20
    elif any(w in t for w in ["президент", "зеленськ", "шмигаль", "рада ухвали"]):
        score += 12

    # --- Штрафи: локальне / неважливе ---
    if any(w in t for w in ["собак", "кіт", "улюблен", "ветклін", "йоркшир"]):
        score -= 45
    if any(w in t for w in ["серіал", "актор", "співак", "концерт", "тікток"]):
        score -= 40
    if any(w in t for w in ["спорт", "футбол", "матч", "гол", "чемпіонат", "шахтар", "динамо", "тендіс", "us open"]):
        score -= 50

    # Локальні ДТП / дрібні ЧП без масових жертв
    if any(w in t for w in ["дтп", "аварія", "п’ян", "п'ян", "водій"]) and not any(
        w in t for w in ["масов", "автобус", "потяг", "багато загиб"]
    ):
        score -= 25

    # Дуже локальне
    if any(w in t for w in ["громад", "селі ", "у селі", "районн"]):
        score -= 12

    # Бонус за довіру джерела
    score += min(8.0, source_trust)

    return max(5.0, min(99.0, score))


def calculate_confidence(source_trust: float, source_class: str) -> int:
    if source_class == "A+":
        return 98
    elif source_class == "A":
        return 92
    elif source_class == "A-":
        return 86
    elif source_class == "B+":
        return 78
    else:
        return 60


def classify_news(final_score: float) -> str:
    if final_score >= 80:
        return "BREAKING"
    elif final_score >= 65:
        return "IMPORTANT"
    elif final_score >= 50:
        return "NORMAL"
    else:
        return "LOW"

def fetch_article_text_sync(url: str) -> str:
    try:
        import requests
        from bs4 import BeautifulSoup
        
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return ""
        
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        
        paragraphs = []
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 60:
                paragraphs.append(t)
            if len(paragraphs) >= 4:
                break
        
        return " ".join(paragraphs[:4])
    except Exception:
        return ""

def calculate_confidence(source_trust: float, title: str) -> float:
    t = title.lower()
    conf = min(100.0, source_trust * 10)

    # Чутки / непідтверджене
    if any(w in t for w in ["за даними джерел", "якщо вірити", "повідомляють джерела", "нібито"]):
        conf -= 35
    if any(w in t for w in ["може", "планує", "розглядає", "збирається"]):
        conf -= 15
    if any(w in t for w in ["офіційно", "генштаб", "нбу", "кабмін", "президент", "постанова"]):
        conf += 10

    return max(20.0, min(100.0, conf))


# ====================== ОСНОВНА ФУНКЦІЯ ======================
def get_news_category(title: str) -> str:
    t = title.lower()

    if any(w in t for w in [
        "тцк", "мобілізац", "повістк", "бусифікац", "рейд",
        "схопил", "незаконн", "відстроч", "бронюван", "влк", "резерв+"
    ]):
        return "tck"

    if any(w in t for w in [
        "ракет", "дрон", "удар", "обстріл", "вибух", "шахед", "балістик",
        "каб", "еваку", "фронт", "зсу", "ппо", "тривог", "бпла"
    ]):
        return "war"

    if any(w in t for w in [
        "енерго", "відключен", "блекаут", "світло", "електро",
        "нбу", "курс", "долар", "євро", "цін", "бюджет", "інфляц",
        "тариф", "подат", "пенсі", "виплат"
    ]):
        return "economy"

    if any(w in t for w in [
        "президент", "кабмін", "рада", "закон", "уряд", "зеленськ", "указ"
    ]):
        return "politics"

    if any(w in t for w in [
        "спорт", "матч", "чемпіонат", "гол", "тендіс", "футбол",
        "us open", "олімп", "світолін", "кіно", "концерт", "шоу"
    ]):
        return "sport"

    return "other"


def ensure_punctuation(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[-1] not in ".!?…:":
        text += "."
    return text

def select_for_publish(news_list: list, max_auto: int = 2) -> list:
    """
    90–100 breaking: макс 1–2
    80–89: зазвичай 1
    65–79: лише якщо сильніших мало
    <65: не беремо, якщо є хоч щось вище
    """
    if not news_list:
        return []

    clean = []
    for n in news_list:
        score = float(n.get("final_score") or n.get("score") or 0)
        cat = (n.get("category") or "").lower()
        title = (n.get("title_original") or n.get("title_chitko") or "").lower()
        if cat == "sport":
            continue
        if any(w in title for w in ["захаров", "песков", "soloviev", "соловйов"]):
            score = min(score, 62)
            n["final_score"] = score
        n["_score"] = score
        clean.append(n)

    clean.sort(key=lambda x: x.get("_score", 0), reverse=True)

    breaking = [n for n in clean if n["_score"] >= 90]
    high = [n for n in clean if 80 <= n["_score"] < 90]
    mid = [n for n in clean if 65 <= n["_score"] < 80]
    low = [n for n in clean if 50 <= n["_score"] < 65]

    picked = []
    picked.extend(breaking[:2])

    if len(picked) < max_auto:
        picked.extend(high[:1])

    if len(picked) == 0:
        picked.extend(mid[:1])
    elif len(picked) < max_auto and not breaking:
        picked.extend(mid[:1])

    if len(picked) == 0 and low:
        # тиха година — максимум 1
        picked.append(low[0])

    return picked[:max_auto]

def fetch_and_score_news(limit: int = 40) -> list:
    out = []
    try:
        out = fetch_tg_channel_posts()
    except Exception as e:
        print(f"TG fetch: {e}")
        out = []
    out.sort(key=lambda x: x.get("final_score") or 0, reverse=True)
    print(f"FETCH tg_only scored={len(out)}")
    return out[:limit]

def get_top_news_for_brief(count: int = 12) -> list:
    news = fetch_and_score_news(40)
    try:
        recent = load_recent_titles() or []
    except Exception:
        recent = []

    unique = []
    seen_now = []
    for item in news:
        title = item.get("title_chitko") or item.get("title") or ""
        if any(is_same_story(title, old) for old in recent + seen_now):
            print(f"DEDUP skip: {title[:80]}")
            continue
        seen_now.append(title)
        unique.append(item)

    hits = [x for x in unique if is_hit_story(x)]
    rest = [x for x in unique if x not in hits]
    ordered = hits + rest
    print(f"DEDUP {len(news)} -> {len(ordered)} hits={len(hits)}")
    return ordered[: max(count, 12)]

# ====================== ТЕСТ ======================

def apply_watermark(image_path: str, output_path: str) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont

        base = Image.open(image_path).convert("RGBA")
        width, height = base.size

        text = "ЧІТКО"
        font_size = max(36, width // 12)

        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                size=font_size
            )
        except Exception:
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                    size=font_size
                )
            except Exception:
                font = ImageFont.load_default()

        text_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_img)

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        only_text = Image.new("RGBA", (tw + 20, th + 20), (0, 0, 0, 0))
        td = ImageDraw.Draw(only_text)

        # Тінь + текст (помітніше)
        td.text((12, 12), text, font=font, fill=(0, 0, 0, 110))
        td.text((10, 10), text, font=font, fill=(255, 255, 255, 160))

        rotated = only_text.rotate(28, expand=True, resample=Image.BICUBIC)
        rw, rh = rotated.size
        x = (width - rw) // 2
        y = (height - rh) // 2

        text_img.paste(rotated, (x, y), rotated)
        result = Image.alpha_composite(base, text_img).convert("RGB")
        result.save(output_path, "JPEG", quality=92)
        return output_path
    except Exception as e:
        print(f"Watermark error: {e}")
        return image_path

def is_bad_source_image(url: str) -> bool:
    u = (url or "").lower()
    if not u:
        return True
    bad = (
        "suspilne.media",
        "cdn.suspilne",
        "userpic",
        "emoji",
        "/img/emoji",
        "profile_pic",
        "telesco.pe/file/userpic",
    )
    return any(x in u for x in bad)

def prepare_image_with_watermark(image_url: str):
    print(f"WM: start {str(image_url)[:100]}")
    try:
        import requests
        import tempfile
        import os

        resp = requests.get(image_url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        print(f"WM: download status {resp.status_code}")
        if resp.status_code != 200:
            return None

        tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp_in.write(resp.content)
        tmp_in.close()
        print(f"WM: saved input {tmp_in.name}")

        tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp_out.close()

        result = apply_watermark(tmp_in.name, tmp_out.name)
        print(f"WM: watermark done {result}")

        try:
            os.unlink(tmp_in.name)
        except Exception:
            pass

        return result
    except Exception as e:
        print(f"WM: error {e}")
        return None

def build_what_it_means(title: str, category: str) -> str:
    t = title.lower()

    if category == "tck":
        return "Що це означає: змінюються правила для військовозобов'язаних. Перевірте актуальний статус у Резерв+ або офіційні роз'яснення."

    if category == "economy":
        if any(w in t for w in ["курс", "долар", "євро", "нбу"]):
            return "Що це означає: курс НБУ — орієнтир для банків і цін. На готівковому ринку цифри можуть відрізнятися."
        if any(w in t for w in ["тариф", "світло", "електро", "газ"]):
            return "Що це означає: зміна може вплинути на рахунки населення. Дата набуття чинності — ключова."
        if any(w in t for w in ["подат", "бюджет", "виплат", "пенсі"]):
            return "Що це означає: рішення стосується грошей громадян. Важливо, коли саме воно починає діяти."
        return "Що це означає: економічне рішення може вплинути на ціни, виплати або умови для бізнесу."

    if category == "politics":
        if any(w in t for w in ["закон", "ухвали", "набув чинност", "підписав"]):
            return "Що це означає: після набуття чинності змінюються обов'язкові правила. Важлива дата старту."
        return ""

    return ""

def build_live_meaning(title: str, body: str, category: str = "") -> str:
    import os
    import requests

    api_key = os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    print(f"LLM meaning: key={'yes' if api_key else 'NO'}")
    if not api_key:
        return ""

    use_xai = bool(os.getenv("XAI_API_KEY"))
    if use_xai:
        url = "https://api.x.ai/v1/chat/completions"
        model = "grok-3-mini"
    else:
        url = "https://api.openai.com/v1/chat/completions"
        model = "gpt-4o-mini"

    system = """Ти — головний оперативний редактор українського Telegram-каналу ЧІТКО.

Ти не бот, не агрегатор і не ChatGPT, який красиво переказує новину.
Ти людина в стрічці: швидко зрозумів подію і одним-двома реченнями сказав знайомому, навіщо це йому.

Твоя єдина відповідь зараз — блок під готовим постом.
Не пиши весь пост. Не пиши заголовок. Не пиши футер.

ФОРМАТ
Рівно 3 або 4 речення українською. Ніколи не повторювати назву заголовка статті.
Перше речення починається так: Що це означає:
Без списків, без емодзі, без «Готовий варіант», без пояснення своєї роботи.

НАВІЩО ЦЕЙ БЛОК
Людина вже прочитала факт. Ти відповідаєш на тихе «і що?».
Додай сенс, якого немає в заголовку і в тексті.
Обери ОДИН кут:
- кого це чіпає завтра вранці;
- що зміниться в грошах, правилах, безпеці;
- що це сигнал, а не сама подія;
- чого не треба плутати (особливо Росія ≠ Україна);
- чи можна взагалі прогортати.

Як нормальної відповіді немає — напиши рівно: SKIP

ГОЛОС
Спокійний, впевнений, сучасний.
Можна легка іронія, якщо тема це витримує.
Нуль істерики. Нуль пафосу. Нуль моралі.
Пиши так, ніби за 20 секунд набрав повідомлення другові — грамотно, без канцеляриту.

МОЖНА іноді (не механічно):
Простіше кажучи…
Тобто фактично…
Тут є нюанс.
Якщо коротко —

НЕ МОЖНА ніколи:
Варто зазначити. Слід зазначити. На даний момент. У сучасних реаліях.
Це може мати значний вплив. Важливо розуміти. Таким чином.
Ситуація напружена. Стежимо за розвитком. Будьмо обережні.
Для звичайної людини це означає ризик поранень / втрати житла.
ШОК. ЖАХ. Ви тільки подивіться.

ЗАБОРОНЕНО
Переказувати заголовок іншими словами.
Повторювати цифри, міста, імена, якщо без них можна сказати думку.
Вигадувати факти, цифри, закони, наслідки, яких немає у вхідному тексті.
Плутати мобілізацію РФ з повістками в Україні.
Медичні та юридичні інструкції.
Заклики підписатись і репостнути.
Показувати внутрішню кухню: бали, категорії, «я проаналізував джерела».

ТЕМИ
Удар по місту: не пояснюй, що вибух небезпечний. Скажи, що війна знову в житло, або що це сигнал для всієї країни — якщо це чесно випливає з тексту.
ТЦК / закон: що зміниться для людини з документами. Без паніки.
Кабмін / декларації / податки: хто виграє і що буде з прозорістю або гаманцем.
Курс / тариф / виплати: дата і кишеня, не лекція.
Росія: чи це взагалі про життя українця, чи лише фон війни.
Дрібниця без наслідків для читача — SKIP.

ПЕРЕВІРКА ПЕРЕД ВІДПРАВКОЮ
Чи це не повтор факту?
Чи звучить як людина, а не пресреліз?
Чи можна сказати коротше?
Якби розповідав другу вголос — сказав би саме так?

ПРИКЛАДИ ТОНУ (копіюй спосіб, не зміст)
Що це означає: війна знову зайшла не на позиції, а в підїзди. Для решти країни це не «ще один звіт», а нагадування, якою була ніч на сході.
Що це означає: частину людей біля оборони хочуть сховати від публічних декларацій. Менше світла — зручніше тим, хто ділить бюджет.
Що це означає: це плани мобілізації всередині Росії. До українських повісток цей текст не має відношення.
Що це означає: держава знову рухає правила, а більшість дізнається вже постфактум.

ЗОЛОТЕ ПРАВИЛО
Не питай «як переказати новину».
Питай «що тут змінилось для людини і чи варто взагалі це промовляти»."""

    user = f"Заголовок: {title}\n\nТекст: {body[:900]}\n\nКатегорія: {category or '-'}"

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.4,
                "max_tokens": 180,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=15,
        )
        print(f"LLM meaning HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(f"LLM meaning body: {resp.text[:300]}")
            return ""

        text = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        print(f"LLM meaning text: {text[:160]}")
        if not text or text.upper().startswith("SKIP"):
            return ""
        if not text.startswith("Що це означає"):
            text = "Що це означає: " + text
        parts = [p.strip() for p in text.replace("!", ".").split(".") if p.strip()]
        text = ". ".join(parts[:2]).strip()
        if text and not text.endswith("."):
            text += "."
        return text
    except Exception as e:
        print(f"LLM meaning exception: {e}")
        return ""

def rewrite_chitko_post(title: str, body: str, category: str = "") -> dict:
    import os
    import requests
    import re

    fail = {"title": "", "body": "", "meaning": "", "ok": False}
    api_key = os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("LLM rewrite: key=NO")
        return fail

    use_xai = bool(os.getenv("XAI_API_KEY"))
    url = "https://api.x.ai/v1/chat/completions" if use_xai else "https://api.openai.com/v1/chat/completions"
    model = "grok-3-mini" if use_xai else "gpt-4o-mini"

    system = """Ти — редактор новин, який пише як реальна людина, а не як бот.
Відповідь СТРОГО у форматі:

TITLE: короткий заголовок
BODY: 4-5 речень. Кожне з крапкою.
MEANING: одне речення або SKIP

Не повторюй заголовок у першому реченні BODY.
Не вигадуй факти, типи ракет, кількість загиблих.
Не плутай Україну і Росію.
Трагедії — стримано, без жартів."""

    user = (
        f"Заголовок джерела: {title}\n\n"
        f"Текст джерела: {body[:1200]}\n\n"
        f"Категорія: {category or '-'}"
    )

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.35,
                "max_tokens": 450,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=20,
        )
        print(f"LLM rewrite HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(f"LLM rewrite body: {resp.text[:300]}")
            return fail

        raw = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        print(f"LLM rewrite text: {raw[:180]}")
        if raw.strip().upper().startswith("SKIP"):
            return fail

        def grab(tag):
            m = re.search(
                rf"{tag}:\s*(.+?)(?=\n(?:TITLE|BODY|MEANING):|\Z)",
                raw,
                flags=re.S | re.I,
            )
            return m.group(1).strip() if m else ""

        new_title = grab("TITLE")
        new_body = grab("BODY")
        meaning = grab("MEANING")

        if not new_title or not new_body:
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            lines = [
                ln for ln in lines
                if not ln.upper().startswith(("TITLE", "BODY", "MEANING", "MEA", "SKIP"))
            ]
            if lines:
                new_title = new_title or lines[0][:140]
                new_body = new_body or " ".join(lines[1:] if len(lines) > 1 else lines)

        if not meaning or meaning.upper().startswith("SKIP"):
            meaning = ""

        new_title = (new_title or "").split("\n")[0].strip(" .")
        new_body = (new_body or "").strip()
        if not new_title or not new_body:
            return fail
        return {"title": new_title, "body": new_body, "meaning": meaning, "ok": True}
    except Exception as e:
        print(f"LLM rewrite exception: {e}")
        return fail

def prepare_chitko_news(news: dict):
    title = (news.get("title_chitko") or news.get("title") or "").strip()
    body = (news.get("text") or news.get("summary") or news.get("body") or "").strip()
    rew = rewrite_chitko_post(title, body, news.get("bucket") or "")
    new_title = (rew.get("title") or "").strip()
    new_body = (rew.get("body") or "").strip()
    blob = f"{new_title}\n{new_body}".upper()
    if rew.get("ok") is False:
        print(f"REWRITE skip: {title[:80]}")
        return None
    if not new_title or not new_body or blob.strip().startswith("SKIP"):
        print(f"REWRITE skip: {title[:80]}")
        return None
    news["title_chitko"] = new_title
    news["title"] = new_title
    news["text"] = new_body
    news["body"] = new_body
    news["rewritten"] = True
    print(f"REWRITE ok: {new_title[:80]}")
    return news

def format_news_post(news: dict) -> str:
    import re

    title = (news.get("title_chitko") or news.get("title_original") or news.get("title") or "").strip()
    body = (news.get("body_chitko") or news.get("text_chitko") or news.get("text") or news.get("summary") or "").strip()
    if len(title) < 8:
        return ""

    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    junk = (
        r"(Підписатися на Times of Ukraine|"
        r"ПОДПИСАТЬСЯ|"
        r"Підписатися|"
        r"Присылайте контент|"
        r"присилайте контент|"
        r"@Obstanovka_kyiv_bot|"
        r"Надіслати новину|"
        r"карта загроз|"
        r"Live map).*$"
    )
    body = re.sub(junk, "", body, flags=re.I).strip()
    title = re.sub(junk, "", title, flags=re.I).strip()

    tnorm = re.sub(r"\W+", " ", title.lower()).strip()
    bnorm = re.sub(r"\W+", " ", body.lower()).strip()
    if tnorm and bnorm.startswith(tnorm):
        body = body[len(title):].lstrip(" .—–-")
        body = re.sub(r"^\W+", "", body).strip()

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", body) if p.strip()]
    parts = [p for p in parts if not re.search(r"підписат|подписат|присылай|присилай", p, re.I)]
    if not parts:
        body_block = ""
    elif len(parts) <= 3:
        body_block = " ".join(parts)
    else:
        mid = max(2, (len(parts) + 1) // 2)
        body_block = " ".join(parts[:mid]) + "\n\n" + " ".join(parts[mid:])

    if any(k in title.lower() for k in ("продаж", "дуплекс", "м²", "іпотек", "забудовник")):
        return ""

    lines = [f"⚡️ {title}"]
    if body_block:
        lines += ["", body_block]
    lines += ["", "ЧІТКО"]
    return "\n".join(lines)

def apply_editorial_caps(news: dict) -> dict:
    title = news.get("title_chitko") or news.get("title_original") or news.get("title") or ""
    text = news.get("text") or news.get("summary") or news.get("body") or ""
    source = (news.get("source") or news.get("source_name") or "").lower()
    t = f"{title} {text}".lower()
    score = float(news.get("final_score") or 0)

    civilian = any(k in t for k in CIVILIAN_KEYS)
    war_filler = any(k in t for k in WAR_FILLER_KEYS)
    air_war = any(x in t for x in [
        "шахед", "дрон", "балістик", "крилат", "ракет", "каб ", "ппо",
        "shahed", "бпла",
    ])
    hard_war = any(x in t for x in [
        "по києву", "по харков", "по одесі", "по запоріж", "по сумах",
        "масована атака", "балістик",
    ]) and any(x in t for x in [
        "поранен", "загинул", "влучан", "удар по", "приліт", "ранен", "погиб",
    ])
    filler_geo = any(x in t for x in [
        "санду", "кишинів", "молдов", "захаров", "вірмен", "patriot",
        "брянськ", "брянск", "ленінград", "ленинград", "кіриш", "кириш",
        "ростов", "бєлгород", "белгород", "oryol", "rostov", "yeisk",
        "leningrad", "орел", "єйськ", "ейськ", "башкортостан",
        "архангельськ", "bashkort", "arkhangelsk",
    ])

    if civilian:
        score = min(100, score + 14)
        news["bucket"] = "civilian"
    elif hard_war:
        score = min(100, score + 8)
        news["bucket"] = "hard_war"
    elif war_filler or (air_war and not civilian):
        score = min(score, 49)
        news["bucket"] = "war_filler"
    else:
        news["bucket"] = "other"

    hit_now = any(x in t for x in (
        "склад", "пожеж", "пожар", "горить", "загорян",
        "приліт", "влучан", "атб", "нової пошт",
    )) and any(x in t for x in (
        "київ", "киев", "троєщин", "деснян", "погреб",
        "бровар", "бориспіл", "одес",
    ))
    if hit_now:
        score = min(100, max(score, 86))
        news["bucket"] = "civilian"

    tg_names = (
        "київ оперативний", "новина", "уніан", "оболонь", "движ",
        "труха", "лачен", "times", "інсайдер", "ванек",
        "kyivoperat", "novynaukr", "uniannet", "obolon",
        "k_dvizh", "truexa", "lachen", "insider", "vanek",
        "тсн", "tsn", "nv", "бабель", "babel", "hromadske", "дснс", "dsns",
    )
    if any(x in source for x in tg_names):
        score = min(100, score + 12)
        news["from_tg"] = True

    if "suspilne" in source or "суспільне" in source:
        score = min(score, 49)
        if news.get("bucket") in ("war_filler", "other"):
            score = min(score, 42)

    if filler_geo and news.get("bucket") != "civilian":
        score = min(score, 40)
        news["bucket"] = "war_filler"

    hook = any(x in t for x in (
        "україн", "київ", "києв", "зсу", "ппо", "санкці",
        "зерн", "мобіліз", "збро", "нато",
    ))
    think = any(x in t for x in (
        "експерти вважають", "психологічн", "наратив",
    ))
    worldish = any(x in t for x in (
        "іран", "йордан", "ларак", "ормуз", "канада",
        "тариф", "трамп",
    ))
    hour = 12
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo("Europe/Kyiv")).hour
    except Exception:
        pass
    if think:
        score = min(score, 47)
        news["bucket"] = "war_filler"
    if worldish and not hook and news.get("bucket") != "civilian":
        if hour < 6 or hour >= 23:
            score = min(score, 46)
            news["bucket"] = "other"

    news["final_score"] = score
    return news

def pick_cycle_news(items: list) -> list:
    items = items or []

    def take(buckets, n, min_score=0):
        rows = [
            x for x in items
            if x.get("bucket") in buckets and (x.get("final_score") or 0) >= min_score
        ]
        rows.sort(key=lambda x: x.get("final_score") or 0, reverse=True)
        return rows[:n]

    slot_a = take(("civilian",), 2, 55)
    slot_b = take(("hard_war", "war_filler"), 1, 40)
    slot_c = take(("other",), 1, 65) if len(slot_a) < 2 else []

    out = slot_a + slot_b + slot_c
    print(
        f"PICK A={len(slot_a)} B={len(slot_b)} C={len(slot_c)} out={len(out)}"
    )
    return out[:3]


if __name__ == "__main__":
    top = get_top_news_for_brief(5)
    print(f"\nЗнайдено {len(top)} якісних новин:\n")
    for i, n in enumerate(top, 1):
        print(f"{i}. [{n['class']}] {n['final_score']} | {n['source']}")
        print(f"   {n['title_chitko']}\n")
