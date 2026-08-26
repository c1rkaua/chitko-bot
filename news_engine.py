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


# ====================== ОСНОВНА ФУНКЦІЯ ======================

def fetch_and_score_news(limit_per_source: int = 8) -> list:
    """
    Збирає новини з RSS, рахує score і повертає відсортований список.
    """
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
                    except:
                        published = datetime.now(timezone.utc)
                else:
                    published = datetime.now(timezone.utc)

                summary = clean_text(entry.get("summary", entry.get("description", "")))[:300]
                link = entry.get("link", "")

                importance = calculate_importance(title, meta["trust"])
                confidence = calculate_confidence(meta["trust"], meta["class"])
                freshness = calculate_freshness(published)
                
                final_score = importance * freshness * (confidence / 100)
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
                    "status": "pending"
                }

                # Спробуємо витягнути фото
                image_url = None
                if "media_content" in entry:
                    for media in entry.media_content:
                        if media.get("type", "").startswith("image"):
                            image_url = media.get("url")
                            break
                if not image_url and "links" in entry:
                    for link_item in entry.links:
                        if link_item.get("type", "").startswith("image"):
                            image_url = link_item.get("href")
                            break

                news_item["image_url"] = image_url
                all_news.append(news_item)

        except Exception as e:
            print(f"Помилка при читанні {source_name}: {e}")
            continue

    # Сортуємо за final_score
    all_news.sort(key=lambda x: x["final_score"], reverse=True)
    
    # Дедуплікація за event_id
    seen = set()
    unique_news = []
    for item in all_news:
        if item["event_id"] not in seen:
            seen.add(item["event_id"])
            unique_news.append(item)

    # Антидубль по схожості заголовків
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
def format_news_post(news: dict) -> str:
    title = news.get("title_chitko", news.get("title_original", "")).strip()
    text = news.get("text_chitko", news.get("summary", "")).strip()
    
    # Чистимо текст
    text = text.replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")
    
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    
    # Емодзі за темою
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
    
    # Формуємо тіло
    if len(sentences) >= 3:
        body = " ".join(sentences[:2]) + "\n\n" + " ".join(sentences[2:4])
    elif len(sentences) == 2:
        body = sentences[0] + "\n\n" + sentences[1]
    elif len(sentences) == 1:
        # Якщо тільки одне речення — перевіряємо, чи воно не копія заголовка
        if sentences[0].lower()[:40] in title.lower() or title.lower()[:40] in sentences[0].lower():
            body = sentences[0]
        else:
            body = sentences[0]
    else:
        body = "Деталі уточнюються."
    
    post = f"{emoji} <b>{title}</b>\n\n{body}\n\n<b>ЧІТКО</b>"
    return post

if __name__ == "__main__":
    top = get_top_news_for_brief(5)
    print(f"\nЗнайдено {len(top)} якісних новин:\n")
    for i, n in enumerate(top, 1):
        print(f"{i}. [{n['class']}] {n['final_score']} | {n['source']}")
        print(f"   {n['title_chitko']}\n")
