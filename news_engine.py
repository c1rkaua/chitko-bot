import feedparser
import hashlib
from datetime import datetime, timezone
from dateutil import parser as date_parser
import re
import json
import os

PUBLISHED_FILE = "published_ids.json"

def load_published_ids():
    if os.path.exists(PUBLISHED_FILE):
        try:
            with open(PUBLISHED_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

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


def is_material_update(old_title: str, new_title: str) -> bool:
    """Чи є істотна нова інформація, а не перефраз."""
    markers = [
        "загибл", "поранен", "еваку", "підтверд", "офіційно",
        "збільш", "зменш", "завершен", "віднов", "ліквідован",
        "затриман", "оголошен", "набув чинност"
    ]
    new_l = new_title.lower()
    old_l = old_title.lower()
    new_has = any(m in new_l for m in markers)
    old_has = any(m in old_l for m in markers)
    return new_has and not old_has


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


def select_for_publish(news_list: list) -> list:
    if not news_list:
        return []

    candidates = []
    for n in news_list:
        score = n.get("final_score", 0)
        title = n.get("title_original", "")
        cat = get_news_category(title)
        n["category"] = cat

        # Спорт — ніколи в авто
        if cat == "sport":
            continue
        # Інше — від 55
        if cat == "other" and score < 55:
            continue
        # Загальний мінімум для авто-кандидатів
        if score < 55:
            continue

        candidates.append(n)

    if not candidates:
        return []

    candidates.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    # Поки що беремо топ-1 завжди, топ-2 якщо обидві >= 80
    selected = [candidates[0]]

    if len(candidates) > 1:
        second = candidates[1]
        if (
            second.get("final_score", 0) >= 80
            and candidates[0].get("category") != second.get("category")
        ):
            selected.append(second)

    return selected

def fetch_and_score_news(limit_per_source: int = 8) -> list:
    all_news = []

    for source_name, meta in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(meta["url"])

            for entry in feed.entries[:limit_per_source]:
                title = clean_text(entry.get("title", ""))
                if not title or len(title) < 15:
                    continue

                published = None
                if hasattr(entry, "published"):
                    try:
                        published = date_parser.parse(entry.published)
                    except Exception:
                        published = datetime.now(timezone.utc)
                else:
                    published = datetime.now(timezone.utc)

                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)

                summary = clean_text(
                    entry.get("summary", "") or entry.get("description", "")
                )
                link = entry.get("link", "")

                trust = float(meta.get("trust", 8))
                importance = calculate_importance(title, trust)
                confidence = calculate_confidence(trust, title)

                age_hours = max(
                    0.1,
                    (datetime.now(timezone.utc) - published).total_seconds() / 3600
                )
                freshness = max(0.55, 1.0 - (age_hours / 48.0) * 0.45)

                final_score = importance * (0.75 + 0.25 * (confidence / 100.0)) * freshness
                final_score = round(max(0.0, min(100.0, final_score)), 1)

                if final_score < 45:
                    news_class = "LOW"
                elif final_score < 60:
                    news_class = "DIGEST"
                elif final_score < 75:
                    news_class = "NORMAL"
                elif final_score < 90:
                    news_class = "HIGH"
                else:
                    news_class = "BREAKING"

                if news_class == "LOW":
                    continue

                news_item = {
                    "event_id": make_event_id(title),
                    "title_original": title,
                    "title_chitko": title,
                    "text_chitko": summary,
                    "summary": summary,
                    "source": source_name,
                    "source_url": link,
                    "source_trust": trust,
                    "published_at": published.isoformat(),
                    "importance_score": round(importance, 1),
                    "confidence_score": round(confidence, 1),
                    "freshness_score": round(freshness, 2),
                    "final_score": final_score,
                    "class": news_class,
                    "category": get_news_category(title),
                    "status": "pending",
                    "image_url": None,
                    "video_url": None,
                }

                if "media_content" in entry:
                    for media in entry.media_content:
                        media_type = media.get("type", "")
                        media_url = media.get("url")
                        if not media_url:
                            continue
                        if media_type.startswith("image") and not news_item["image_url"]:
                            news_item["image_url"] = media_url
                        elif media_type.startswith("video") and not news_item["video_url"]:
                            news_item["video_url"] = media_url

                if not news_item["image_url"] and hasattr(entry, "links"):
                    for link_item in entry.links:
                        ltype = link_item.get("type", "")
                        href = link_item.get("href")
                        if not href:
                            continue
                        if ltype.startswith("image") and not news_item["image_url"]:
                            news_item["image_url"] = href
                        elif ltype.startswith("video") and not news_item["video_url"]:
                            news_item["video_url"] = href

                if news_item.get("image_url") and is_bad_source_image(news_item["image_url"]):
                    news_item["image_url"] = None

                all_news.append(news_item)

        except Exception as e:
            print(f"Помилка при читанні {source_name}: {e}")
            continue

    all_news.sort(key=lambda x: x["final_score"], reverse=True)

    seen = set()
    unique_news = []
    for item in all_news:
        if item["event_id"] not in seen:
            seen.add(item["event_id"])
            unique_news.append(item)

    def is_similar(t1, t2):
        s1 = set(t1.lower().split())
        s2 = set(t2.lower().split())
        if not s1 or not s2:
            return False
        return len(s1 & s2) / len(s1 | s2) > 0.55

    final_news = []
    for item in unique_news:
        if item["event_id"] in published_ids:
            continue

        title = item.get("title_original", "")
        is_dup = False
        for existing in final_news:
            if is_similar(title, existing.get("title_original", "")):
                is_dup = True
                break

        if not is_dup:
            final_news.append(item)

    return final_news  


def get_top_news_for_brief(count: int = 4) -> list:
    news = fetch_and_score_news()
    return news[:count]

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

def format_news_post(news: dict) -> str:
    title = news.get("title_chitko", news.get("title_original", "")).strip()
    text = news.get("text_chitko", news.get("summary", "")).strip()

    text = text.replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")

    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 30]

    junk_parts = [
        "суспільне веде онлайн",
        "онлайн щодо",
        "читайте також",
        "підписуйтесь",
        "більше новин",
        "слідкуйте за оновленнями",
        "1645 день",
        "день війни",
    ]
    clean_sentences = []
    for s in sentences:
        low = s.lower()
        if any(j in low for j in junk_parts):
            continue
        clean_sentences.append(s)
    sentences = clean_sentences

    title_lower = title.lower()
    if any(w in title_lower for w in ["ракет", "дрон", "удар", "обстріл", "вибух", "балістик", "шахед"]):
        emoji = "⚡️"
    elif any(w in title_lower for w in ["тцк", "мобілізац", "повістк", "бусифікац", "рейд"]):
        emoji = "⚠️"
    elif any(w in title_lower for w in ["загибл", "поранен", "загинув", "загинула"]):
        emoji = "🕯"
    elif any(w in title_lower for w in ["енерго", "відключен", "світло", "блекаут"]):
        emoji = "🔌"
    else:
        emoji = "▪️"

    if len(sentences) >= 3:
        body = (
            ensure_punctuation(sentences[0]) + "\n\n" +
            ensure_punctuation(sentences[1]) + "\n\n" +
            ensure_punctuation(sentences[2])
        )
    elif len(sentences) == 2:
        body = ensure_punctuation(sentences[0]) + "\n\n" + ensure_punctuation(sentences[1])
    elif len(sentences) == 1:
        body = ensure_punctuation(sentences[0])
    else:
        body = "Деталі уточнюються."

    category = news.get("category") or get_news_category(title)
    meaning = build_what_it_means(title, category)

    if meaning:
        post = f"{emoji} <b>{title}</b>\n\n{body}\n\n{meaning}\n\n<b>ЧІТКО</b>"
    else:
        post = f"{emoji} <b>{title}</b>\n\n{body}\n\n<b>ЧІТКО</b>"

    if len(post) > 1000:
        cut = post[:960]
        last_dot = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        if last_dot > 200:
            post = cut[:last_dot + 1] + "\n\n<b>ЧІТКО</b>"
        else:
            post = cut.rsplit(" ", 1)[0] + "…\n\n<b>ЧІТКО</b>"

    return post

    # Емодзі
    title_lower = title.lower()
    if any(w in title_lower for w in ["ракет", "дрон", "удар", "обстріл", "вибух", "балістик", "шахед"]):
        emoji = "⚡️"
    elif any(w in title_lower for w in ["тцк", "мобілізац", "повістк", "бусифікац", "рейд"]):
        emoji = "⚠️"
    elif any(w in title_lower for w in ["загибл", "поранен", "загинув", "загинула"]):
        emoji = "🕯"


if __name__ == "__main__":
    top = get_top_news_for_brief(5)
    print(f"\nЗнайдено {len(top)} якісних новин:\n")
    for i, n in enumerate(top, 1):
        print(f"{i}. [{n['class']}] {n['final_score']} | {n['source']}")
        print(f"   {n['title_chitko']}\n")
