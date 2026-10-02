"""OpenStreetMap: local businesses around a place (Nominatim geocode + Overpass query).

Usage policy: Nominatim allows max 1 request/second with an identifying User-Agent.
leadhound makes one geocode call and one Overpass call per run.
"""
from __future__ import annotations

from urllib.parse import quote, urlencode

from ..models import Lead

NOMINATIM = "https://nominatim.openstreetmap.org/search?format=json&limit=1&q={}"
OVERPASS = "https://overpass-api.de/api/interpreter"

CATEGORY_TAGS = {
    "restaurant": ("amenity", "restaurant"), "cafe": ("amenity", "cafe"), "bar": ("amenity", "bar"),
    "dentist": ("amenity", "dentist"), "doctors": ("amenity", "doctors"), "clinic": ("amenity", "clinic"),
    "veterinary": ("amenity", "veterinary"), "pharmacy": ("amenity", "pharmacy"),
    "hairdresser": ("shop", "hairdresser"), "beauty": ("shop", "beauty"), "bakery": ("shop", "bakery"),
    "florist": ("shop", "florist"), "car_repair": ("shop", "car_repair"), "furniture": ("shop", "furniture"),
    "clothes": ("shop", "clothes"), "optician": ("shop", "optician"), "jewelry": ("shop", "jewelry"),
    "plumber": ("craft", "plumber"), "electrician": ("craft", "electrician"), "carpenter": ("craft", "carpenter"),
    "lawyer": ("office", "lawyer"), "accountant": ("office", "accountant"), "estate_agent": ("office", "estate_agent"),
    "insurance": ("office", "insurance"), "hotel": ("tourism", "hotel"), "guest_house": ("tourism", "guest_house"),
    "gym": ("leisure", "fitness_centre"), "driving_school": ("amenity", "driving_school"),
}
BOOKING_CATEGORIES = {"restaurant", "dentist", "doctors", "clinic", "veterinary", "hairdresser", "beauty",
                      "hotel", "guest_house", "gym", "driving_school"}


def category_tag(cat: str) -> tuple[str, str]:
    cat = cat.strip().lower()
    if "=" in cat:  # raw OSM tag, e.g. "shop=bicycle"
        k, v = cat.split("=", 1)
        return k.strip(), v.strip()
    if cat not in CATEGORY_TAGS:
        raise ValueError(f"unknown category '{cat}'. Use one of: {', '.join(sorted(CATEGORY_TAGS))} or key=value")
    return CATEGORY_TAGS[cat]


def geocode(fetcher, place: str) -> tuple[float, float, str]:
    res = fetcher.get_json(NOMINATIM.format(quote(place)))
    if not res:
        raise ValueError(f"place not found: {place}")
    return float(res[0]["lat"]), float(res[0]["lon"]), res[0].get("display_name", place)


def build_query(categories: list, lat: float, lon: float, radius: int) -> str:
    parts = []
    for cat in categories:
        k, v = category_tag(cat)
        parts.append(f'nwr["{k}"="{v}"]["name"](around:{int(radius)},{lat},{lon});')
    return f"[out:json][timeout:60];({''.join(parts)});out center tags;"


def _category_of(tags: dict, categories: list) -> str:
    for cat in categories:
        k, v = category_tag(cat)
        if tags.get(k) == v:
            return cat.split("=")[-1]
    return ""


def parse_elements(data: dict, categories: list) -> list[Lead]:
    leads = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        osm_id = f"{el.get('type', 'node')}/{el.get('id')}"
        osm_url = f"https://www.openstreetmap.org/{osm_id}"
        website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
        if website and not website.startswith(("http://", "https://")):
            website = "http://" + website
        phone = tags.get("phone") or tags.get("contact:phone") or ""
        email = tags.get("email") or tags.get("contact:email") or ""
        addr = " ".join(x for x in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if x)
        city = tags.get("addr:city", "")
        location = ", ".join(x for x in (addr, city) if x)
        center = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        cat = _category_of(tags, categories)
        leads.append(Lead(
            source="osm", external_id=osm_id, kind="business", title=name, url=website or osm_url,
            location=location, contact=", ".join(x for x in (email, phone) if x),
            signals=[] if website else ["no website listed"],
            extra={"category": cat, "website": website, "osm_url": osm_url, "phone": phone, "email": email,
                   "lat": center.get("lat"), "lon": center.get("lon"), "city": city,
                   "booking_relevant": cat in BOOKING_CATEGORIES},
        ))
    return leads


def find_businesses(fetcher, place: str, categories: list, radius: int) -> tuple[list[Lead], str]:
    lat, lon, display = geocode(fetcher, place)
    q = build_query(categories, lat, lon, radius)
    data = fetcher.get_json(OVERPASS, data=urlencode({"data": q}).encode())
    return parse_elements(data, categories), display
