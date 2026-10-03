"""OpenStreetMap: local businesses around a place (Nominatim geocode + Overpass query).

Usage policy: Nominatim allows max 1 request/second with an identifying User-Agent.
leadhound makes one geocode call and one Overpass call per run.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from ..models import Lead
from ..net import FetchError

NOMINATIM = "https://nominatim.openstreetmap.org/search?format=json&limit=1&addressdetails=1&q={}"
# Public Overpass servers, tried in order: the main one is often busy at peak hours
OVERPASS_SERVERS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter")
OVERPASS = OVERPASS_SERVERS[0]

CATEGORY_TAGS = {
    # food and drink
    "restaurant": ("amenity", "restaurant"), "cafe": ("amenity", "cafe"), "bar": ("amenity", "bar"),
    "pub": ("amenity", "pub"), "fast_food": ("amenity", "fast_food"), "bakery": ("shop", "bakery"),
    "butcher": ("shop", "butcher"), "ice_cream": ("amenity", "ice_cream"), "wine": ("shop", "wine"),
    # health
    "dentist": ("amenity", "dentist"), "doctors": ("amenity", "doctors"), "clinic": ("amenity", "clinic"),
    "veterinary": ("amenity", "veterinary"), "pharmacy": ("amenity", "pharmacy"), "optician": ("shop", "optician"),
    "physiotherapist": ("healthcare", "physiotherapist"), "psychotherapist": ("healthcare", "psychotherapist"),
    # beauty and fitness
    "hairdresser": ("shop", "hairdresser"), "beauty": ("shop", "beauty"), "massage": ("shop", "massage"),
    "tattoo": ("shop", "tattoo"), "cosmetics": ("shop", "cosmetics"), "gym": ("leisure", "fitness_centre"),
    "sports_centre": ("leisure", "sports_centre"), "yoga": ("sport", "yoga"),
    # shops
    "clothes": ("shop", "clothes"), "shoes": ("shop", "shoes"), "jewelry": ("shop", "jewelry"), "florist": ("shop", "florist"),
    "furniture": ("shop", "furniture"), "bicycle": ("shop", "bicycle"), "car": ("shop", "car"), "car_repair": ("shop", "car_repair"),
    "car_parts": ("shop", "car_parts"), "electronics": ("shop", "electronics"), "mobile_phone": ("shop", "mobile_phone"),
    "hardware": ("shop", "hardware"), "pet": ("shop", "pet"), "toys": ("shop", "toys"), "books": ("shop", "books"),
    "gift": ("shop", "gift"), "photo_shop": ("shop", "photo"), "dry_cleaning": ("shop", "dry_cleaning"),
    "laundry": ("shop", "laundry"), "car_wash": ("amenity", "car_wash"), "funeral": ("shop", "funeral_directors"),
    # trades
    "plumber": ("craft", "plumber"), "electrician": ("craft", "electrician"), "carpenter": ("craft", "carpenter"),
    "painter": ("craft", "painter"), "roofer": ("craft", "roofer"), "hvac": ("craft", "hvac"), "locksmith": ("craft", "locksmith"),
    "tailor": ("craft", "tailor"), "photographer": ("craft", "photographer"),
    # offices and services
    "lawyer": ("office", "lawyer"), "accountant": ("office", "accountant"), "estate_agent": ("office", "estate_agent"),
    "insurance": ("office", "insurance"), "architect": ("office", "architect"), "travel_agency": ("shop", "travel_agency"),
    "it_company": ("office", "it"), "coworking": ("amenity", "coworking_space"),
    # lodging and education
    "hotel": ("tourism", "hotel"), "guest_house": ("tourism", "guest_house"), "hostel": ("tourism", "hostel"),
    "apartment": ("tourism", "apartment"), "kindergarten": ("amenity", "kindergarten"),
    "language_school": ("amenity", "language_school"), "music_school": ("amenity", "music_school"),
    "driving_school": ("amenity", "driving_school"), "dancing_school": ("leisure", "dance"),
}
BOOKING_CATEGORIES = {"restaurant", "dentist", "doctors", "clinic", "veterinary", "hairdresser", "beauty", "massage",
                      "tattoo", "physiotherapist", "psychotherapist", "hotel", "guest_house", "hostel", "apartment", "gym",
                      "yoga", "driving_school", "language_school", "music_school", "dancing_school", "car_repair", "car_wash"}


def category_tag(cat: str) -> tuple[str, str]:
    cat = cat.strip().lower()
    if "=" in cat:  # raw OSM tag, e.g. "shop=bicycle"
        k, v = cat.split("=", 1)
        return k.strip(), v.strip()
    if cat not in CATEGORY_TAGS:
        raise ValueError(f"unknown category '{cat}'. Use one of: {', '.join(sorted(CATEGORY_TAGS))} or key=value")
    return CATEGORY_TAGS[cat]


def geocode(fetcher, place: str) -> dict:
    res = fetcher.get_json(NOMINATIM.format(quote(place)))
    if not res:
        raise ValueError(f"place not found: {place}")
    r = res[0]
    bb = [float(x) for x in r.get("boundingbox", [])] or None  # [south, north, west, east]
    return {"lat": float(r["lat"]), "lon": float(r["lon"]), "name": r.get("display_name", place),
            "country": ((r.get("address") or {}).get("country_code") or "").lower(), "bbox": bb}


def build_query(categories: list, lat: float, lon: float, radius: int, bbox: list | None = None, limit: int = 1500) -> str:
    """radius 0 = whole area of the place (its bounding box), else a circle around the center."""
    if not radius and bbox:
        s_, n, w, e = bbox
        area = f"({s_},{w},{n},{e})"
    else:
        area = f"(around:{int(radius or 3000)},{lat},{lon})"
    parts = []
    for cat in categories:
        k, v = category_tag(cat)
        parts.append(f'nwr["{k}"="{v}"]["name"]{area};')
    return f"[out:json][timeout:90];({''.join(parts)});out center tags {int(limit)};"


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
        # OSM separates several values with ";"
        phones = [x.strip() for x in (tags.get("phone") or tags.get("contact:phone") or "").split(";") if x.strip()]
        emails = [x.strip() for x in (tags.get("email") or tags.get("contact:email") or "").split(";") if x.strip()]
        phones += [x.strip() for x in (tags.get("contact:whatsapp") or "").split(";") if x.strip() and x.strip() not in phones]
        telegram = (tags.get("contact:telegram") or "").strip().lstrip("@").removeprefix("https://t.me/")
        phone, email = (phones[0] if phones else ""), (emails[0] if emails else "")
        addr = " ".join(x for x in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if x)
        city = tags.get("addr:city", "")
        location = ", ".join(x for x in (addr, city) if x)
        center = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        cat = _category_of(tags, categories)
        leads.append(Lead(
            source="osm", external_id=osm_id, kind="business", title=name, url=website or osm_url,
            location=location, contact=", ".join(emails + phones + ([f"Telegram: @{telegram}"] if re.fullmatch(r"\w{4,32}", telegram) else [])),
            signals=[] if website else ["no website listed"],
            extra={"category": cat, "website": website, "osm_url": osm_url, "phone": phone, "email": email,
                   "lat": center.get("lat"), "lon": center.get("lon"), "city": city,
                   "booking_relevant": cat in BOOKING_CATEGORIES},
        ))
    return leads


def overpass(fetcher, query: str) -> dict:
    """Run a query, falling back to the next public server when one is busy or slow."""
    body = urlencode({"data": query}).encode()
    errors = []
    for url in OVERPASS_SERVERS:
        try:
            r = fetcher.request(url, method="POST", data=body, timeout=95,
                                headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
            if r.status < 400:
                return r.json()
            errors.append(f"{url.split('/')[2]}: HTTP {r.status}")
        except (FetchError, ValueError) as e:
            errors.append(f"{url.split('/')[2]}: {str(e)[-60:]}")
    raise FetchError("map servers busy, try again in a minute (" + "; ".join(errors) + ")")


def find_businesses(fetcher, place: str, categories: list, radius: int) -> tuple[list[Lead], str]:
    g = geocode(fetcher, place)
    q = build_query(categories, g["lat"], g["lon"], radius, g["bbox"])
    data = overpass(fetcher, q)
    leads = parse_elements(data, categories)
    city = g["name"].split(",")[0].strip()
    for lead in leads:
        lead.extra["country"] = g["country"]
        lead.extra["city"] = lead.extra.get("city") or city
    return leads, g["name"]
