import json
import os
import requests

from air_attack import ingest_targets

SEEN_FILE = "air_seen_ids.json"

KYIV_MARKERS = [
    "kyiv", "київ", "киев", "київщин", "бровар", "вишгород",
    "ірпін", "буч", "фастів", "біла церк",
]


def load_seen() -> set:
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(ids_set: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids_set)[-400:], f)


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

    seen = load_seen()
    objects = fetch_live_objects()

    if not seen and objects:
        for obj in objects:
            oid = str(obj.get("id") or obj.get("key") or "")
            if oid:
                seen.add(oid)
        save_seen(seen)
        return []

    fresh = []
    for obj in objects:
        oid = str(obj.get("id") or obj.get("key") or "")
        if not oid or oid in seen:
            continue
        if not _is_kyiv(obj):
            seen.add(oid)
            continue
        fresh.append(obj)
        seen.add(oid)

    save_seen(seen)

    buckets = {}
    for obj in fresh:
        t = _map_type(obj)
        buckets[t] = buckets.get(t, 0) + 1

    if not buckets:
        return []

    return [ingest_combo(buckets, "Київ")]
