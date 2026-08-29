import json
import os
import requests

from air_attack import ingest_targets

SEEN_FILE = "air_seen_ids.json"

KYIV_MARKERS = [
    "kyiv", "київ", "киев", "київщин", "бровар", "вишгород",
    "ірпін", "буч", "фастів", "біла церк",
]

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

def _is_kyiv(obj: dict) -> bool:
    city = " ".join([
        str(obj.get("to_city") or ""),
        str(obj.get("to") or ""),
        str(obj.get("city") or ""),
    ]).lower()
    return "kyiv" in city or "київ" in city or "киев" in city


def _map_type(obj: dict) -> str:
    kind = str(obj.get("kind") or obj.get("subkind") or "").lower()
    raw = " ".join([
        kind,
        str(obj.get("title") or ""),
        str(obj.get("name") or ""),
        str(obj.get("type") or ""),
    ]).lower()

    if "орешник" in raw or "oreshnik" in raw:
        return "ORESHNIK"
    if "кінжал" in raw or "кинжал" in raw or "kinzhal" in raw:
        return "KINZHAL"
    if "циркон" in raw or "zircon" in raw:
        return "ZIRCON"
    if "іскандер" in raw or "искандер" in raw or "iskander" in raw:
        return "ISKANDER"
    if "х-22" in raw or "x-22" in raw:
        return "X22"
    if "х-101" in raw or "x-101" in raw or "х-555" in raw:
        return "X101"
    if kind in ("drone_piston", "drone_jet") or "drone" in kind:
        return "UAV"
    if kind == "missile_cruise" or "cruise" in kind:
        return "CRUISE"
    if kind == "missile_ballistic" or "ballistic" in kind:
        return "BALLISTIC"
    if "hypersonic" in raw or "гіпер" in raw:
        return "HYPER"
    if any(w in raw for w in ["shahed", "шахед", "бпла", "uav"]):
        return "UAV"
    if "ракет" in raw or "missile" in raw:
        return "UNKNOWN"
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

    state = load_seen()
    last = (state.get("by_district") if isinstance(state, dict) else None) or {}
    out = []
    for label, counts in by_district.items():
        prev = last.get(label) or {}
        buckets = {}
        for t, n in counts.items():
            delta = n - int(prev.get(t) or 0)
            if delta > 0:
                buckets[t] = delta
        if not buckets:
            continue
        result = ingest_combo(buckets, "Київ")
        if isinstance(result, dict):
            result["district"] = label
            result["totals_now"] = counts
            out.append(result)

    save_seen({"by_district": by_district, "counts": {}, "districts": list(by_district.keys())})
    return out

MONITOR_LAST = {"sig": "", "at": 0.0}

KYIV_MONITOR = [
    "київ", "киев", "київщин", "киевщин",
    "троєщин", "оболон", "дарниц", "дарницьк",
    "святошин", "печерськ", "поділ", "голосіїв",
    "солом'ян", "солом’ян", "деснян",
    "лівобереж", "борщаг", "виноградар",
    "вишгород", "бровар", "ірпін", "буч",
    "фастів", "біла церк", "погреб", "переяслав",
    "славутич", "васильків",
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
