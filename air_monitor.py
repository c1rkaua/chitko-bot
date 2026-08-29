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
    blob = " ".join([
        str(obj.get("to_city") or ""),
        str(obj.get("title") or ""),
        str(obj.get("name") or ""),
        str(obj.get("from_zone") or ""),
    ]).lower()
    return any(m in blob for m in KYIV_MARKERS)


def _map_type(obj: dict) -> str:
    raw = " ".join([
        str(obj.get("kind") or ""),
        str(obj.get("subkind") or ""),
        str(obj.get("title") or ""),
        str(obj.get("type") or ""),
    ]).lower()

    if any(w in raw for w in ["ballistic", "баліст", "iskander", "іскандер", "кинжал", "kinzhal"]):
        return "BALLISTIC"
    if any(w in raw for w in ["hypersonic", "гіпер"]):
        return "HYPER"
    if any(w in raw for w in ["cruise", "крилат", "калибр", "калібр", "x-101", "х-101"]):
        return "CRUISE"
    if any(w in raw for w in ["drone", "uav", "shahed", "шахед", "бпла"]):
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

    try:
        r2 = requests.get("https://neptun.in.ua/api/v1/threats", timeout=8)
        if r2.status_code == 200:
            data2 = r2.json()
            if isinstance(data2, list):
                objects.extend(data2)
            elif isinstance(data2, dict):
                objects.extend(data2.get("threats") or data2.get("items") or [])
    except Exception as e:
        print(f"AIR monitor neptun error: {e}")

    return objects


def poll_new_targets() -> list:
    from air_attack import ingest_combo

    objects = fetch_live_objects()
    kyiv_now = [obj for obj in objects if _is_kyiv(obj)]

    counts = {}
    for obj in kyiv_now:
        t = _map_type(obj)
        counts[t] = counts.get(t, 0) + 1

    state = load_seen()
    last_counts = {}
    if isinstance(state, dict) and "counts" in state:
        last_counts = state.get("counts") or {}
    elif isinstance(state, set):
        last_counts = {}

    buckets = {}
    for t, n in counts.items():
        prev = int(last_counts.get(t) or 0)
        delta = n - prev
        if delta > 0:
            buckets[t] = delta

    save_seen({"counts": counts})

    if not buckets:
        return []
    
    return [ingest_combo(buckets, "Київ")]
