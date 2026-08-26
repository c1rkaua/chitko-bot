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


def calculate_importance(title: str, source_trust: float) -> int:
    title_lower = title.lower()
    score = 48  # базовий бал

    # 1. Форс-мажор
    force = ["ракет", "балістик", "дрон", "удар", "обстріл", "вибух", "шахед", "масован", "искандер", "циркон"]
    for w in force:
        if w in title_lower:
            score += 28
            break

    # 2. ТЦК / мобілізація
    tck = ["тцк", "мобілізац", "повістк", "бусифікац", "рейд", "схопил", "незаконн"]
    for w in tck:
        if w in title_lower:
            score += 22
            break

    # 3. Жертви
    victims = ["загибл", "поранен", "загинув", "загинула", "вбито", "еваку", "ДТП"]
    for w in victims:
        if w in title_lower:
            score += 20
            break

    # 4. Енергетика
    energy = ["енерго", "відключен", "блекаут", "світло", "електро"]
    for w in energy:
        if w in title_lower:
            score += 18
            break

    # 5. Фронт / ЗСУ
    war = ["фронт", "зсу", "генштаб", "повітряні сили", "ппо", "наступ", "бої"]
    for w in war:
        if w in title_lower:
            score += 16
            break

    # 6. Влада
    power = ["президент", "зеленськ", "кабмін", "рада", "закон", "указ"]
    for w in power:
        if w in title_lower:
            score += 15
            break

    # 7. Економіка
    economy = ["нбу", "курс", "долар", "євро", "цін", "бюджет"]
    for w in economy:
        if w in title_lower:
            score += 12
            break

    # Бонус від джерела
    score += int(source_trust * 6)

    return max(0, min(100, score))


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
        # Інше — тільки дуже сильне
        if cat == "other" and score < 85:
            continue
        # Загальний мінімум
        if score < 78:
            continue

        candidates.append(n)

    if not candidates:
        return []

    candidates.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    selected = [candidates[0]]

    # Друга новина — тільки якщо обидві дуже сильні і різні категорії
    if len(candidates) > 1:
        second = candidates[1]
        if (
            candidates[0].get("final_score", 0) >= 90
            and second.get("final_score", 0) >= 90
            and candidates[0].get("category") != second.get("category")
        ):
            selected.append(second)

    return selected

    candidates.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    top = candidates[0]
    selected = [top]

    # Друга тільки якщо обидві дуже сильні і різні теми
    if len(candidates) > 1:
        second = candidates[1]
        if (
            top.get("final_score", 0) >= 90
            and second.get("final_score", 0) >= 90
            and top.get("category") != second.get("category")
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

                # Дата
                published = None
                if hasattr(entry, "published"):
                    try:
                        published = date_parser.parse(entry.published)
                    except Exception:
                        published = datetime.now(timezone.utc)
                else:
                    published = datetime.now(timezone.utc)

                # Текст
                summary = clean_text(
                    entry.get("summary", "") or entry.get("description", "")
                )

                # Посилання
                link = entry.get("link", "")

                # Скоринг
                importance = calculate_importance(title, meta["trust"])
                confidence = min(1.0, meta["trust"] / 10)
                
                age_hours = max(
                    0.1,
                    (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600
                )
                freshness = max(0.5, 1.0 - (age_hours / 48))
                
                final_score = importance * confidence * freshness
                news_class = classify_news(final_score)

                if news_class == "LOW":
                    continue

                news_item = {
                    "event_id": make_event_id(title),
                    "title_original": title,
                    "title_chitko": title,
                    "text_chitko": summary,
                    "source": source_name,
                    "source_url": link,
                    "source_trust": meta["trust"],
                    "published_at": published.isoformat(),
                    "importance_score": importance,
                    "confidence_score": confidence,
                    "freshness_score": round(freshness, 2),
                    "final_score": round(final_score, 1),
                    "class": news_class,
                    "status": "pending",
                    "image_url": None,
                    "video_url": None,
                }

                # Медіа
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

                all_news.append(news_item)

        except Exception as e:
            print(f"Помилка при читанні {source_name}: {e}")
            continue

    # Сортування
    all_news.sort(key=lambda x: x["final_score"], reverse=True)

    # Дедуп по event_id
    seen = set()
    unique_news = []
    for item in all_news:
        if item["event_id"] not in seen:
            seen.add(item["event_id"])
            unique_news.append(item)

    # Антидубль + схожі заголовки
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

        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        text = "ЧІТКО"
        font_size = max(32, width // 18)

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

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        x = width - tw - 24
        y = height - th - 24

        # Підложка для читабельності
        pad = 10
        draw.rectangle(
            [x - pad, y - pad, x + tw + pad, y + th + pad],
            fill=(0, 0, 0, 110)
        )

        draw.text((x, y), text, font=font, fill=(255, 255, 255, 230))

        result = Image.alpha_composite(base, overlay).convert("RGB")
        result.save(output_path, "JPEG", quality=92)
        return output_path
    except Exception as e:
        print(f"Watermark error: {e}")
        return image_path

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

def format_news_post(news: dict) -> str:
    title = news.get("title_chitko", news.get("title_original", "")).strip()
    text = news.get("text_chitko", news.get("summary", "")).strip()

    # Базове очищення
    text = text.replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")

    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 30]

    # Прибираємо сміттєві речення
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

    # Емодзі
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

    # Тіло з обов'язковими крапками
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

    post = f"{emoji} <b>{title}</b>\n\n{body}\n\n<b>ЧІТКО</b>"

    # Ліміт підпису Telegram
    if len(post) > 1000:
        cut = post[:960]
        last_dot = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        if last_dot > 200:
            post = cut[:last_dot + 1] + "\n\n<b>ЧІТКО</b>"
        else:
            post = cut.rsplit(" ", 1)[0] + "…\n\n<b>ЧІТКО</b>"

    return post

if __name__ == "__main__":
    top = get_top_news_for_brief(5)
    print(f"\nЗнайдено {len(top)} якісних новин:\n")
    for i, n in enumerate(top, 1):
        print(f"{i}. [{n['class']}] {n['final_score']} | {n['source']}")
        print(f"   {n['title_chitko']}\n")
