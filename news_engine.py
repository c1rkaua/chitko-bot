import feedparser
import hashlib
from datetime import datetime, timezone
from dateutil import parser as date_parser
import re
import json
import os

PUBLISHED_FILE = "published_ids.json"

TG_SOURCES = {
    "lachentyt": {"name": "Лачен пише", "trust": 6.5, "bias": "civilian"},
    "vanek_nikolaev": {"name": "Миколаївський Ванек", "trust": 6.5, "bias": "civilian"},
    "times_ukraina": {"name": "Times of Ukraine", "trust": 6.2, "bias": "civilian"},
    "truexanewsua": {"name": "Труха Україна", "trust": 6.5, "bias": "civilian"},
    "insiderUKR": {"name": "Інсайдер UA", "trust": 6.2, "bias": "civilian"},
}

CIVILIAN_KEYS = [
    "дтп", "аварі", "авария", "аварию", "тцк", "бусифік", "бусифик",
    "мобіліз", "мобилиз", "пожеж", "пожар", "вибух газу", "взрыв газа",
    "обвал", "затопи", "затоп", "чп", "чп ", "поранен", "ранен",
    "загинул", "погиб", "стрілянин", "стрельба", "затриман", "задержан",
    "хабар", "взятк", "корупц", "коррупц",
    "світло", "отключен", "відключен", "тариф", "пенсі", "пенси",
    "маршрутка", "автобус", "зіткнен", "столкновен",
]
WAR_FILLER_KEYS = [
    "генштаб зведення", "за добу знешкоджено", "окупанти не полишають",
    "триває відсіч", "на купянському",
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
        "дівчинк": "дитин",
        "хлопчик": "дитин",
        "дитина": "дитин",
        "дітей": "дитин",
        "столичн": "київ",
        "столиці": "київ",
        "оболонськ": "оболон",
        "безпілотник": "бпла",
        "безпілотн": "бпла",
        "дрона": "бпла",
        "дронів": "бпла",
        "дрон ": "бпла ",
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    text = re.sub(r"[^\wа-яіїєґ]+", " ", text, flags=re.I)
    stop = {
        "в", "у", "на", "та", "і", "й", "по", "з", "із", "від", "для",
        "що", "як", "це", "після", "через", "було", "була", "були",
        "яка", "який", "які", "зазнав", "зазнала", "поранена", "поранену",
    }
    return " ".join(w for w in text.split() if w not in stop and len(w) > 1)


def is_same_story(a: str, b: str) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na[:36] in nb or nb[:36] in na:
        return True
    sa, sb = set(na.split()), set(nb.split())
    if not sa or not sb:
        return False
    inter = sa & sb
    if len(inter) >= 4:
        return True
    keys = {"померл", "загибл", "бпла", "оболон", "київ", "дитин", "дворіч"}
    hit_a = {k for k in keys if any(k in w for w in sa)}
    hit_b = {k for k in keys if any(k in w for w in sb)}
    return len(hit_a & hit_b) >= 3

def is_breaking(news: dict) -> bool:
    score = float(news.get("final_score") or 0)
    blob = " ".join([
        news.get("title_chitko") or "",
        news.get("title") or "",
        news.get("text") or "",
        news.get("body") or "",
    ]).lower()
    keys = [
        "загибл", "померл", "вбито", "загинула",
        "удар по києв", "приліт", "попадання",
        "вибух у києв", "вибухи в києв",
        "дворіч", "дитин", "школяр",
        "масована атака", "балістик",
        "ДТП", 
    ]
    if score >= 88:
        return True
    return any(k in blob for k in keys)

def extract_tg_media(chunk: str) -> dict:
    import re

    video = None
    m = re.search(
        r'(?:src|href)=["\'](https://cdn4\.telesco\.pe/file/[^"\']+\.mp4)',
        chunk,
        re.I,
    )
    if m:
        video = m.group(1)
    if not video:
        m = re.search(r"(https://cdn4\.telesco\.pe/file/[^\"')\s]+\.mp4)", chunk)
        if m:
            video = m.group(1)

    if video:
        return {"photos": [], "video": video}

    photos = []
    seen = set()
    photo_blocks = re.split(r"tgme_widget_message_photo", chunk)
    for block in photo_blocks[1:]:
        if "userpic" in block[:200].lower():
            continue
        raw = re.findall(
            r"background-image:url\('?(https?://cdn4\.telesco\.pe/file/[^')\s]+)'?\)",
            block,
        )
        raw += re.findall(
            r"(https://cdn4\.telesco\.pe/file/[^\"')\s]+)",
            block,
        )
        for u in raw:
            if ".mp4" in u:
                continue
            if "emoji" in u or "userpic" in u:
                continue
            if u not in seen:
                seen.add(u)
                photos.append(u)
    return {"photos": photos[:4], "video": None}

def fetch_tg_channel_posts() -> list:
    global LAST_TG_STATS
    import hashlib
    import re
    import requests
    from datetime import datetime

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    out = []
    LAST_TG_STATS["checked"] = 0
    LAST_TG_STATS["skipped"] = 0
    LAST_TG_STATS["kept"] = 0
    LAST_TG_STATS["by_channel"] = {}
    LAST_TG_STATS["when"] = datetime.now().strftime("%H:%M")

    for username, meta in TG_SOURCES.items():
        kept = 0
        html = ""
        messages = []
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
            text_bits = re.findall(
                r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                raw,
                flags=re.I | re.S,
            )
            blob = " ".join(text_bits) if text_bits else raw
            text = re.sub(r"<br\s*/?>", "\n", blob, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 40:
                LAST_TG_STATS["skipped"] += 1
                continue
            low = text.lower()
            if any(k in low for k in WAR_FILLER_KEYS) or not any(k in low for k in CIVILIAN_KEYS):
                LAST_TG_STATS["skipped"] += 1
                continue

            media = extract_tg_media(raw)
            title = text.split(".")[0].strip()[:140]
            event_id = hashlib.md5(f"tg:{username}:{title[:80]}".encode()).hexdigest()
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
                "final_score": 62.0,
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
    import hashlib
    import feedparser

    feeds = [
        ("Суспільне", "https://suspilne.media/rss/", 8.5),
        ("УП", "https://www.pravda.com.ua/rss/", 8.8),
        ("Бабель", "https://babel.ua/rss", 8.6),
        ("hromadske", "https://hromadske.ua/feed", 8.4),
        ("Радіо Свобода", "https://www.radiosvoboda.org/api/zrqiteuuok", 8.7),
        ("Укрінформ", "https://www.ukrinform.ua/rss/block-lastnews", 8.0),
        ("ДСНС", "https://dsns.gov.ua/uk/news/rss", 9.0),
    ]

    published = set()
    try:
        published = set(load_published_ids() or [])
    except Exception:
        published = set()

    out = []
    seen = set()

    for source_name, url, trust in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"FEED {source_name}: {e}")
            continue

        for entry in (parsed.entries or [])[:12]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            summary = (entry.get("summary") or entry.get("description") or "").strip()
            if not title or not link:
                continue

            event_id = hashlib.md5(link.encode("utf-8")).hexdigest()
            if event_id in published or event_id in seen:
                continue
            seen.add(event_id)

            try:
                score = float(calculate_importance(title, trust))
            except Exception:
                score = 50.0

            image_url = None
            media = entry.get("media_content") or entry.get("media_thumbnail") or []
            if isinstance(media, list) and media:
                image_url = media[0].get("url")
            elif isinstance(media, dict):
                image_url = media.get("url")
            if not image_url:
                enc = entry.get("enclosures") or []
                if enc:
                    image_url = enc[0].get("href")

            try:
                if image_url and is_bad_source_image(image_url):
                    image_url = None
            except Exception:
                pass

            news = {
                "event_id": event_id,
                "title": title,
                "title_original": title,
                "title_chitko": title,
                "text": summary,
                "summary": summary,
                "body": summary,
                "link": link,
                "source": source_name,
                "source_name": source_name,
                "image_url": image_url,
                "final_score": score,
            }
            news = apply_editorial_caps(news)
            out.append(news)

    try:
        out.extend(fetch_tg_channel_posts())
    except Exception as e:
        print(f"TG fetch: {e}")

    out.sort(key=lambda x: x.get("final_score") or 0, reverse=True)
    print(f"FETCH scored={len(out)}")
    return out[:limit]

def get_top_news_for_brief(count: int = 4) -> list:
    news = fetch_and_score_news()
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

    print(f"DEDUP {len(news)} -> {len(unique)}")
    return unique[:count]

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
    if not url:
        return True
    u = url.lower()
    bad = [
        "suspilne.media",
        "suspilne.novyny",
        "corp.suspilne",
        "suspilne.cdn",
        "cdn4.suspilne",
    ]
    return any(b in u for b in bad)


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

    empty = {"title": title.strip(), "body": body.strip(), "meaning": ""}
    api_key = os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("LLM rewrite: key=NO")
        return empty

    use_xai = bool(os.getenv("XAI_API_KEY"))
    url = "https://api.x.ai/v1/chat/completions" if use_xai else "https://api.openai.com/v1/chat/completions"
    model = "grok-3-mini" if use_xai else "gpt-4o-mini"

    system = """Ти — редактор новин, який пише як реальна людина, а не як бот чи інформагентство.
Пояснюй новину просто, спокійно й природно, ніби розповідаєш її колезі в месенджері.
Не використовуй канцелярит, шаблонні фрази та «нейромережевий» стиль.
Спочатку дай короткий і зрозумілий заголовок, а далі 4–5 змістовних речень.
Не повторюй заголовок у першому реченні тексту.
Перше речення має одразу пояснити, що саме сталося.
Далі дай 2–3 найважливіші деталі без води та другорядної інформації.
Новину не обрізай настільки, щоб читач втрачав її суть або важливий контекст.
Завжди зберігай конкретні цифри, суми, дати, міста, райони та інші важливі деталі, якщо вони є в джерелі.
Якщо є джерело, природно посилайся на нього в тексті.
Ніколи не вигадуй імена, кількість загиблих чи постраждалих, типи ракет, координати, місця влучань або інші факти, яких немає у вихідній інформації.
Особливо уважно перевіряй, хто саме виконав дію, і ніколи не плутай Україну та Росію, українські й російські сили.
Якщо інформацію повідомляє лише одна сторона, чітко зазначай, хто саме це заявив.
Про трагедії, загиблих, обстріли та катастрофи пиши стримано, без жартів, іронії, шоку та зайвого драматизму.
Кожне речення обов’язково закінчуй крапкою, включно з останнім реченням тексту.
Після BODY сформуй MEANING — коротку відповідь на запитання читача «І що це означає?».
MEANING не повинен повторювати новину, а має просто пояснювати її значення, наслідки або чому це важливо.
Якщо корисного MEANING немає або новина сама по собі нічого не додає, напиши рівно: SKIP.
Якщо новина неважлива, порожня, клікбейтна або не дає читачеві жодної цінності — не публікуй її та також поверни: SKIP."""

    user = f"Заголовок джерела: {title}\n\nТекст джерела: {body[:1200]}\n\nКатегорія: {category or '-'}"

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
            return empty

        raw = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        print(f"LLM rewrite text: {raw[:180]}")

        def grab(tag):
            m = re.search(
                rf"{tag}:\s*(.+?)(?=\n(?:TITLE|BODY|MEANING):|\Z)",
                raw,
                flags=re.S | re.I,
            )
            return m.group(1).strip() if m else ""

        new_title = grab("TITLE") or title.strip()
        new_body = grab("BODY") or body.strip()
        meaning = grab("MEANING")
        if not meaning or meaning.upper().startswith("SKIP"):
            meaning = ""
        elif not meaning.startswith("Що це означає"):
            meaning = "Що це означає: " + meaning

        new_title = new_title.split("\n")[0].strip(" .")
        return {"title": new_title, "body": new_body, "meaning": meaning}
    except Exception as e:
        print(f"LLM rewrite exception: {e}")
        return empty

def format_news_post(news: dict) -> str:
    import re

    title = (news.get("title_chitko") or news.get("title_original") or news.get("title") or "").strip()
    body = (news.get("body_chitko") or news.get("text_chitko") or news.get("text") or news.get("summary") or "").strip()
    if len(title) < 8:
        return ""

    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"Підписатися на Times of Ukraine.*$", "", body, flags=re.I).strip()

    tnorm = re.sub(r"\W+", " ", title.lower()).strip()
    bnorm = re.sub(r"\W+", " ", body.lower()).strip()
    if tnorm and bnorm.startswith(tnorm):
        body = body[len(title):].lstrip(" .—–-")
        body = re.sub(r"^\W+", "", body).strip()

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", body) if p.strip()]
    if not parts:
        body_block = ""
    elif len(parts) <= 3:
        body_block = " ".join(parts)
    else:
        mid = max(2, (len(parts) + 1) // 2)
        body_block = " ".join(parts[:mid]) + "\n\n" + " ".join(parts[mid:])

    lines = [f"<b>⚡️ {title}</b>"]
    if body_block:
        lines += ["", body_block]
    lines += ["", "<b>ЧІТКО</b>"]
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

    if "suspilne" in source or "суспільне" in source:
        if news.get("bucket") == "war_filler":
            score = min(score, 45)
        elif news.get("bucket") == "other":
            score = min(score, 68)

    if filler_geo and news.get("bucket") != "civilian":
        score = min(score, 48)
        news["bucket"] = "war_filler"

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
