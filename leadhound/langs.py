"""Language knowledge used across sources, audit and drafts.

Phrases are deliberately short and common. They catch "I need someone" posts in many languages and
drop "I am looking for work" posts (other freelancers, not clients).
"""
from __future__ import annotations

import re

LANGUAGES = {  # code: native name (UI and message drafts)
    "en": "English", "es": "Español", "pt": "Português", "fr": "Français", "de": "Deutsch", "ru": "Русский",
    "ka": "ქართული", "tr": "Türkçe", "ar": "العربية", "hi": "हिन्दी", "zh": "中文",
}

# Someone asks for help: "looking for / need / hiring" + a person or service
CLIENT_RX = re.compile("|".join([
    r"\b(looking for|need|needs|seeking|searching for|want to hire|hiring)\b.{0,40}\b(developer|dev|programmer|freelancer|"
    r"designer|writer|editor|translator|marketer|photographer|videographer|assistant|engineer|agency|expert|someone|help|consultant)\b",
    r"\[\s*(hiring|task|paid)\s*\]", r"\bseeking freelancers?\b",
    r"\b(busco|buscamos|necesito|necesitamos|se busca|contrato)\b.{0,40}\b(desarrollador|programador|diseñador|freelance|redactor|traductor|editor|fotógrafo|alguien|ayuda|experto)",
    r"\b(procuro|procuramos|preciso de|precisamos de|precisa-se)\b.{0,40}\b(desenvolvedor|programador|designer|freelancer|redator|tradutor|editor|fotógrafo|alguém|ajuda|especialista)",
    r"\b(je cherche|nous cherchons|recherche|besoin d'un|besoin d’une?)\b.{0,40}\b(développeur|developpeur|graphiste|freelance|rédacteur|traducteur|monteur|photographe|quelqu'un|aide|expert)",
    r"\b(suche|suchen|gesucht|brauche|brauchen)\b.{0,40}\b(entwickler|programmierer|designer|freelancer|texter|übersetzer|cutter|fotograf|jemanden|hilfe|experte)",
    r"\b(ищу|ищем|нужен|нужна|нужны|требуется|требуются)\b.{0,40}(разработчик|программист|дизайнер|фрилансер|копирайтер|переводчик|монтажер|фотограф|помощь|специалист|исполнител)",
    r"\b(arıyorum|arıyoruz|aranıyor|lazım|ihtiyacım var)\b",
    r"\b(cerco|cerchiamo|cercasi)\b.{0,40}\b(sviluppatore|programmatore|grafico|freelance|traduttore|fotografo|qualcuno|aiuto)",
    r"(ვეძებ|გვჭირდება|მჭირდება)",
    r"(أبحث عن|نبحث عن|مطلوب)",
    r"(招聘|寻找|需要).{0,10}(开发|设计|翻译|自由职业|兼职)",
]), re.I)

# Someone offers their own services or wants a job: competitor or job seeker, not a client
SEEKER_RX = re.compile("|".join([
    r"\bfor hire\b", r"\bhire me\b", r"#?open ?to ?work\b", r"\blooking for (a )?(new )?(job|work|gig|role|position|opportunit)",
    r"\b(i am|i'm) (available|a freelance)", r"\bmy (portfolio|services|rates)\b", r"\bseeking (work|employment)\b",
    r"\bbusco (trabajo|empleo)\b", r"\bprocuro (emprego|trabalho)\b", r"\bje cherche (un )?(emploi|travail|poste)\b",
    r"\bsuche (arbeit|job|stelle)\b", r"\bищу работу\b", r"\biş arıyorum\b",
    r"\b(i|we) can help\b", r"\b(dm|message|contact) me\b", r"\b(i|we) offer\b", r"\bour services\b",
    r"^\s*(looking for|need|needs?)\b[^.?!\n]{0,80}\?",  # "Need a website?" = an ad, not a request
]), re.I | re.M)

# Freelance-shaped work (not a salaried job): used where job ads would otherwise drown real clients
FREELANCE_RX = re.compile(
    r"\b(freelanc\w*|contract\w*|gig|project|commission\w*|part[- ]time|one[- ]off|budget|paid task|"
    r"autónomo|proyecto|projeto|projet|projekt|serbest|proje)\b|проект|фриланс|подработ|პროექტ|ფრილანს|مشروع|兼职|项目|परियोजना|"
    r"\bfor (my|our) (\w+ ){0,2}(website|site|app|shop|store|business|brand|startup|restaurant|book|channel|podcast)\b", re.I)


def is_freelance_client(text: str) -> bool:
    return is_client_text(text) and bool(FREELANCE_RX.search(text or ""))


# Website words, for the audit
CONTACT_WORDS = (r"contact|kontakt|contacto|contato|contatti|contactez|контакт|კონტაქტ|iletişim|اتصل|تواصل|联系|संपर्क")
BOOKING_WORDS = (r"\b(book|booking|reserve|reservation|appointment|schedule online|order online)\b|reservar|reserva|agendar|"
                 r"marcar|réserver|réservation|rendez-vous|buchen|termin|prenota|записаться|запись|бронир|დაჯავშნ|"
                 r"rezervasyon|randevu|احجز|حجز|预约|预订|बुक|"
                 r"calendly|opentable|resy|booksy|fresha|treatwell|simplybook|setmore|square\.site|doctolib|thefork")

COUNTRY_LANG = {
    "es": "es", "mx": "es", "ar": "es", "co": "es", "cl": "es", "pe": "es", "ve": "es", "ec": "es", "gt": "es", "cu": "es",
    "bo": "es", "do": "es", "hn": "es", "py": "es", "sv": "es", "ni": "es", "cr": "es", "pa": "es", "uy": "es",
    "pt": "pt", "br": "pt", "ao": "pt", "mz": "pt", "fr": "fr", "be": "fr", "lu": "fr", "mc": "fr", "sn": "fr", "ci": "fr",
    "cm": "fr", "ma": "fr", "tn": "fr", "dz": "fr", "de": "de", "at": "de", "ch": "de", "li": "de",
    "ru": "ru", "by": "ru", "kz": "ru", "kg": "ru", "ge": "ka", "tr": "tr", "az": "tr",
    "sa": "ar", "ae": "ar", "eg": "ar", "jo": "ar", "lb": "ar", "kw": "ar", "qa": "ar", "bh": "ar", "om": "ar", "iq": "ar",
    "in": "hi", "cn": "zh", "tw": "zh", "hk": "zh", "sg": "en",
}


def is_client_text(text: str) -> bool:
    return bool(CLIENT_RX.search(text or "")) and not SEEKER_RX.search(text or "")


def language_for(site_lang: str = "", country: str = "", fallback: str = "en") -> str:
    """Pick a draft language we have templates for: website <html lang>, then country, then fallback."""
    code = (site_lang or "").split("-")[0].split("_")[0].lower()
    if code in LANGUAGES:
        return code
    return COUNTRY_LANG.get((country or "").lower(), fallback)
