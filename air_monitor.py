import json
import os
import requests

from air_attack import ingest_targets

SEEN_FILE = "air_seen_ids.json"


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {"counts": {}}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {"counts": {}}
    except Exception:
        return {"counts": {}}


def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def _is_kyiv_city(obj: dict) -> bool:
    city = " ".join([
        str(obj.get("to_city") or ""),
        str(obj.get("to") or ""),
        str(obj.get("city") or ""),
    ]).lower().replace("м.", " ").strip()
    if "област" in city or "oblast" in city or "київщин" in city or "киевщин" in city:
        return False
    return (
        city in ("kyiv", "київ", "киев")
        or city.startswith("kyiv")
        or city.startswith("київ")
        or city.startswith("киев")
    )

def _is_kyiv(obj: dict) -> bool:
    return _is_kyiv_city(obj)

def detect_districts(text: str) -> list:
    low = (text or "").lower()
    found = []
    for key, name in KYIV_DISTRICTS:
        if key in low and name not in found:
            found.append(name)
    return found

def _map_type(obj: dict) -> str:
    kind = str(obj.get("kind") or obj.get("subkind") or "").lower().strip()
    raw = " ".join([
        kind,
        str(obj.get("title") or ""),
        str(obj.get("name") or ""),
    ]).lower()

    if "орешник" in raw or "oreshnik" in raw:
        return "ORESHNIK"
    if "кінжал" in raw or "кинжал" in raw or "kinzhal" in raw:
        return "KINZHAL"
    if "циркон" in raw or "zircon" in raw:
        return "ZIRCON"
    if "іскандер" in raw or "искандер" in raw or "iskander" in raw:
        return "ISKANDER"
    if kind == "missile_cruise":
        return "CRUISE"
    if kind == "missile_ballistic":
        return "BALLISTIC"
    if kind in ("drone_piston", "drone_jet") or kind.startswith("drone"):
        return "UAV"
    if any(w in raw for w in ["shahed", "шахед", "бпла", "uav", "geran", "геран"]):
        return "UAV"
    return "UAV"

def fetch_live_objects() -> list:
    objects = []
    try:
        r = requests.get("https://mapa.ua/api/v1/current", timeout=8)
        if r.status_code == 200:
            data = r.json()
            objects.extend(data.get("objects") or [])
    except Exception as e:
        print(f"AIR monitor mapa error: {e}")
    return objects

def poll_new_targets() -> list:
    from air_attack import ingest_combo

    objects = fetch_live_objects()
    kyiv_now = [obj for obj in objects if _is_kyiv_city(obj)]

    by_district = {}
    for obj in kyiv_now:
        blob = " ".join([
            str(obj.get("title") or ""),
            str(obj.get("name") or ""),
            str(obj.get("to_city") or ""),
        ])
        names = detect_districts(blob)
        label = names[0] if names else "Київ"
        t = _map_type(obj)
        n = int(obj.get("amount") or 1)
        slot = by_district.setdefault(label, {})
        slot[t] = slot.get(t, 0) + max(n, 1)

    hints = fetch_district_hints()
    if "Київ" in by_district and hints:
        by_district["Київ"]["_hints"] = hints

    state = load_seen()
    last = (state.get("by_district") if isinstance(state, dict) else None) or {}
    out = []
    for label, counts in by_district.items():
        hints_now = []
        if isinstance(counts, dict) and "_hints" in counts:
            hints_now = counts.pop("_hints") or []
        prev = last.get(label) or {}
        buckets = {}
        for t, n in counts.items():
            if t == "_hints":
                continue
            delta = n - int(prev.get(t) or 0)
            if delta > 0:
                buckets[t] = delta
        if not buckets:
            continue
        result = ingest_combo(buckets, "Київ")
        if isinstance(result, dict):
            result["district"] = label
            result["totals_now"] = counts
            result["hints"] = hints_now
            out.append(result)

    save_seen({
        "by_district": by_district,
        "counts": {},
        "districts": list(by_district.keys()),
    })
    return out

MONITOR_LAST = {"sig": "", "at": 0.0}

KYIV_DISTRICTS = [
    ("почайн", "Почайна"),
    ("жулян", "Жуляни"),
    ("вишнев", "Вишневе"),
    ("мінськ", "Мінський"),
    ("минск", "Мінський"),
    ("нивк", "Нивки"),
    ("івасюк", "Івасюка"),
    ("винагород", "Виноградар"),
    ("виговськ", "Виговського"),
    ("на центр", "центр"),
    ("на цент", "центр"),
    ("центр києв", "центр"),
    ("трою", "Троєщина"),
    ("троєщин", "Троєщина"),
    ("троещин", "Троєщина"),
    ("оболон", "Оболонь"),
    ("дарниц", "Дарниця"),
    ("дарницьк", "Дарницький"),
    ("святошин", "Святошин"),
    ("печерськ", "Печерськ"),
    ("печерск", "Печерськ"),
    ("поділ", "Поділ"),
    ("подольск", "Поділ"),
    ("голосіїв", "Голосіїв"),
    ("голосеев", "Голосіїв"),
    ("солом'ян", "Солом'янка"),
    ("солом’ян", "Солом'янка"),
    ("солом'янк", "Солом'янка"),
    ("деснян", "Деснянський"),
    ("лівобереж", "Лівобережка"),
    ("левобереж", "Лівобережка"),
    ("борщаг", "Борщагівка"),
    ("позняк", "Позняки"),
    ("осокорк", "Осокорки"),
    ("харьківськ", "Харківський"),
    ("харківськ", "Харківський"),
    ("відрадн", "Відрадний"),
    ("сирець", "Сирець"),
    ("сирец", "Сирець"),
    ("куренів", "Куренівка"),
    ("куренев", "Куренівка"),
    ("теремк", "Теремки"),
    ("білич", "Біличі"),
    ("белич", "Біличі"),
    ("академміст", "Академмістечко"),
    ("академгород", "Академмістечко"),
    ("совк", "Совки"),
    ("лук’ян", "Лук'янівка"),
    ("лук'ян", "Лук'янівка"),
    ("конч", "Конча-Заспа"),
    ("шуляв", "Шулявка"),
    ("трухан", "Труханів"),
    ("наталк", "Наталка"),
    ("оболонськ набереж", "Набережна"),
    ("рибальськ", "Рибальський"),
    ("подольск", "Поділ"),
    ("героїв дніпр", "Героїв Дніпра"),
    ("мінський масив", "Мінський"),
    ("вигурівщин", "Вигурівщина"),
    ("воскресенк", "Воскресенка"),
    ("лісов", "Лісовий"),
    ("київська русанівк", "Русанівка"),
    ("русанівк", "Русанівка"),
    ("березняк", "Березняки"),
    ("харьківська площ", "Харківська"),
    ("червоний хутір", "Червоний хутір"),
    ("бориспільськ", "Бориспільська"),
    ("павлоградськ", "Павлоградський"),
    ("осокорк", "Осокорки"),
    ("подол", "Поділ"),
    ("контрактов", "Контрактова"),
    ("майдан", "центр"),
    ("хрещатик", "Хрещатик"),
    ("липки", "Липки"),
    ("клочк", "Клов"),
    ("дружби народ", "Дружби народів"),
    ("либідськ", "Либідська"),
    ("демїїв", "Деміївка"),
    ("деміїв", "Деміївка"),
    ("саперн", "Саперна"),
    ("китаїв", "Китаєво"),
    ("феофані", "Феофанія"),
    ("пирогів", "Пирогів"),
    ("голосіївськ ліс", "Голосіїв"),
    ("теремки-2", "Теремки"),
    ("житній", "Житній"),
    ("сирецький гай", "Сирець"),
    ("берковець", "Берковець"),
    ("пуща-водиц", "Пуща-Водиця"),
    ("пуща водиц", "Пуща-Водиця"),
    ("вишгородськ", "Вишгородська"),
    ("оболонський просп", "Оболонь"),
    ("стеценка", "Стеценка"),
    ("моста патона", "міст Патона"),
    ("південний міст", "Південний міст"),
    ("московськ міст", "Північний міст"),
    ("північний міст", "Північний міст"),
    ("гавань", "Гавань"),
    ("караваєві дач", "Караваєві дачі"),
    ("відрадний", "Відрадний"),
    ("чубаїв", "Чубаївщина"),
    ("жуляни", "Жуляни"),
    ("аеропорт київ", "Жуляни"),
    ("бориспіль", "Бориспіль"),
    ("лісовий масив", "Лісовий"),
    ("квітнев", "Квітневий"),
    ("радужн", "Радужний"),
    ("войт", "Воскресенка"),
    ("галаган", "Галагани"),
    ("нижні сади", "Нижні сади"),
    ("верхні сади", "Верхні сади"),
    ("чапаєвк", "Чапаєвка"),
    ("пірогів", "Пирогів"),
    ("корчуват", "Корчувате"),
    ("мишоловк", "Мишоловка"),
    ("цеглян", "Цегляний"),
    ("борщагівк", "Борщагівка"),
    ("петрівк", "Петрівка"),
    ("почайна", "Почайна"),
    ("вишгород", "Вишгород"),
    ("видубич", "Видубичі"),
    ("олімпійськ", "Олімпійська"),
    ("олимпийск", "Олімпійська"),
    ("палац спорт", "Палац спорту"),
    ("львівськ площ", "Львівська площа"),
    ("бровар", "Бровари"),
    ("бориспіл", "Бориспіль"),
    ("бориспол", "Бориспіль"),
    ("погреб", "Погреби"),
    ("вишгород", "Вишгород"),
    ("видубич", "Видубичі"),
    ("олімпійськ", "Олімпійська"),
    ("дврз", "ДВРЗ"),
    ("димерк", "Велика Димерка"),
    ("бориспіл", "Бориспіль"),
    ("бориспол", "Бориспіль"),
    ("погреб", "Погреби"),
    ("чабан", "Чабани"),
    ("вишеньк", "Вишеньки"),
    ("обухів", "Обухів"),
    ("гостомл", "Гостомель"),
    ("ірпін", "Ірпінь"),
    ("ірпен", "Ірпінь"),
]

KYIV_MONITOR = [
    "київ", "kyiv", "киев",
    "троєщин", "оболон", "дарниц", "святошин",
    "печерськ", "поділ", "голосіїв", "солом",
    "деснян", "лівобереж", "борщаг", "виноградар",
    "позняк", "осокорк", "нивк", "сирець",
    "куренів", "теремк", "білич", "академміст",
]

def fetch_monitor_kyiv() -> str:
    import re
    import requests

    html = requests.get(
        "https://t.me/s/war_monitor",
        timeout=12,
        headers={"User-Agent": "Mozilla/5.0"},
    ).text
    chunks = re.split(r'class="tgme_widget_message_text', html)
    texts = []
    for chunk in chunks[1:6]:
        raw = re.sub(r"<[^>]+>", " ", chunk)
        raw = re.sub(r"\s+", " ", raw).strip()
        low = raw.lower()
        if not any(k in low for k in KYIV_MONITOR):
            continue
        if any(x in low for x in ["стратегічн", "обстановка станом", "флот", "ракетоносі"]):
            continue
        texts.append(raw[:400])
    return texts[0] if texts else ""

def fetch_tg_districts(url: str) -> list:
    import re
    import requests

    try:
        html = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception as e:
        print(f"DISTRICT fetch {url}: {e}")
        return []

    chunks = re.split(r'class="tgme_widget_message_text', html)
    found = []
    skip = (
        "ірпін", "фастів", "київщин",
        "област", "димерк", "лебедів",
        "повітряна тривога", "air siren",
        "відбій повітряної",
    )
    for chunk in chunks[1:8]:
        raw = re.sub(r"<[^>]+>", " ", chunk)
        raw = re.sub(r"\s+", " ", raw).strip()
        low = raw.lower()
        if any(s in low for s in skip):
            continue
        for name in detect_districts(raw):
            if name not in found:
                found.append(name)
    return found


def fetch_eradar_districts() -> list:
    return fetch_tg_districts("https://t.me/s/eradarrua")


def fetch_kievreal_districts() -> list:
    return fetch_tg_districts("https://t.me/s/kievreal1")

def fetch_latest_course() -> list:
    import re
    import requests

    urls = (
        "https://t.me/s/k_dvizh",
        "https://t.me/s/kievreal1",
        "https://t.me/s/eradarrua",
    )
    skip = (
        "підписатися", "присылайте", "реклам", "купим",
        "надіслати новину", "повітряна тривога", "оголошена",
        "відбій", "отбой", "air siren", "підтримай",
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            html = requests.get(url, timeout=10, headers=headers).text
        except Exception as e:
            print(f"COURSE {url} {e}")
            continue
        chunks = re.split(r'class="tgme_widget_message_text', html)
        for chunk in chunks[1:8]:
            raw = re.sub(r"<[^>]+>", " ", chunk)
            raw = re.sub(r"\s+", " ", raw).strip()
            low = raw.lower()
            if any(s in low for s in skip):
                continue
            found = detect_districts(raw)
            if not found:
                continue
            print(f"COURSE now {found[0]} via {url}")
            return [found[0]]
    return []


def fetch_district_hints() -> list:
    return fetch_latest_course() or []
   
