"""Profession profiles: one click sets skills, pitch, sources and local-business targets.

Every feed URL and Freelancer.com category below was checked to return live listings (October 2026).
"""
from __future__ import annotations

from dataclasses import dataclass, field

WWR = "https://weworkremotely.com/categories/remote-{}-jobs.rss"
COMMON_SUBS = ("forhire", "jobbit", "hiring")


@dataclass(frozen=True)
class Profession:
    id: str
    skills: tuple
    pitch: str
    freelancer: tuple  # Freelancer.com RSS category slugs (job_<slug>.xml)
    subreddits: tuple = COMMON_SUBS
    feeds: tuple = ()
    github: bool = False
    github_labels: tuple = ()
    github_languages: tuple = ()
    local: tuple = ()  # local business categories worth pitching; empty = local search not a focus
    mastodon_tags: tuple = ("FediHire", "hiring", "freelance")
    extra: dict = field(default_factory=dict)


PROFESSIONS = [
    Profession("developer", ("python", "javascript", "php", "wordpress", "react", "website", "web app", "api", "shopify"),
               "I build fast, reliable websites and web apps for small businesses",
               ("Website-Design", "PHP", "WordPress", "Python", "JavaScript", "Shopify", "HTML"),
               COMMON_SUBS + ("hireaprogrammer",), (WWR.format("programming"), "https://jobspresso.co/feed/?post_type=job_listing"),
               True, ("bounty", "help wanted"), (),
               ("restaurant", "cafe", "dentist", "hairdresser", "beauty", "hotel", "lawyer", "car_repair")),
    Profession("mobile", ("flutter", "react native", "ios", "android", "swift", "kotlin", "mobile app", "app"),
               "I build mobile apps for iPhone and Android, from idea to the app stores",
               ("Mobile-App-Development", "Flutter", "iPhone"), COMMON_SUBS + ("hireaprogrammer",), (WWR.format("programming"),),
               True, ("bounty",), ("dart", "swift", "kotlin"), ("restaurant", "gym", "beauty")),
    Profession("designer", ("graphic design", "logo", "branding", "ui", "ux", "figma", "illustration", "brand identity", "web design"),
               "I design logos, brands and websites that make small businesses look trustworthy",
               ("Graphic-Design", "Logo-Design", "UX-UI-Design", "Figma", "Illustration"),
               COMMON_SUBS + ("DesignJobs",), (WWR.format("design"), "https://dribbble.com/jobs.rss"),
               False, (), (), ("restaurant", "cafe", "bakery", "beauty", "florist", "clothes")),
    Profession("writer", ("copywriting", "content writing", "blog", "article", "ghostwriting", "seo writing", "editing", "proofreading"),
               "I write clear website copy, blog posts and emails that bring in customers",
               ("Content-Writing", "Article-Writing", "Copywriting", "Ghostwriting", "Technical-Writing"),
               COMMON_SUBS + ("HireaWriter",), ("https://www.authenticjobs.com/feed/",),
               False, (), (), ("dentist", "lawyer", "hotel", "estate_agent")),
    Profession("translator", ("translation", "translator", "localization", "proofreading", "subtitles", "transcription"),
               "I translate and localize websites, documents and videos accurately",
               ("Translation",), COMMON_SUBS, (), False, (), (), ("hotel", "guest_house", "dentist", "lawyer")),
    Profession("marketer", ("seo", "social media", "marketing", "google ads", "facebook ads", "instagram", "email marketing", "content strategy"),
               "I help local businesses get found on Google and win more customers online",
               ("Internet-Marketing", "Social-Media-Marketing", "Search-Engine-Optimization"),
               COMMON_SUBS, (WWR.format("sales-and-marketing"),), False, (), (),
               ("restaurant", "cafe", "dentist", "hairdresser", "beauty", "gym", "hotel")),
    Profession("video", ("video editing", "animation", "motion graphics", "youtube", "premiere", "after effects", "reels", "tiktok"),
               "I edit videos and reels that grab attention and get shared",
               ("Video-Editing", "Animation", "Video-Services"), COMMON_SUBS + ("HireAnEditor",), (),
               False, (), (), ("restaurant", "gym", "hotel", "beauty", "car_repair")),
    Profession("photographer", ("photography", "photo editing", "retouching", "product photos", "photoshoot", "lightroom"),
               "I take and edit photos that make products and places look their best",
               ("Photography", "Photo-Editing"), COMMON_SUBS + ("PhotographyJobs",), (), False, (), (),
               ("restaurant", "cafe", "hotel", "guest_house", "florist", "clothes")),
    Profession("assistant", ("virtual assistant", "data entry", "admin", "excel", "customer support", "research", "scheduling", "email management"),
               "I take admin work off your plate: email, scheduling, data entry and research",
               ("Virtual-Assistant", "Data-Entry", "Excel", "Customer-Support"), COMMON_SUBS, (WWR.format("customer-support"),),
               False, (), (), ("dentist", "lawyer", "accountant", "estate_agent")),
    Profession("data", ("python", "automation", "scraping", "ai", "chatbot", "machine learning", "data analysis", "excel", "api"),
               "I automate repetitive work and build data and AI tools that save hours every week",
               ("Web-Scraping", "Python", "Machine-Learning-ML", "Artificial-Intelligence", "Excel"),
               COMMON_SUBS + ("hireaprogrammer",), (WWR.format("programming"),), True, ("bounty", "help wanted"), ("python",),
               ("accountant", "estate_agent", "lawyer")),
    Profession("audio", ("voice over", "audio editing", "podcast", "music", "mixing", "mastering", "sound design"),
               "I record voice-overs and edit audio and podcasts that sound professional",
               ("Audio-Services", "Voice-Talent", "Music"), COMMON_SUBS, (), False, (), (), ()),
    Profession("accounting", ("bookkeeping", "accounting", "quickbooks", "xero", "tax", "invoicing", "payroll"),
               "I keep small businesses' books accurate, on time and ready for tax season",
               ("Accounting", "Bookkeeping"), COMMON_SUBS, (), False, (), (),
               ("restaurant", "cafe", "dentist", "car_repair", "plumber", "electrician")),
]
BY_ID = {p.id: p for p in PROFESSIONS}


def defaults(pid: str) -> dict:
    """Config values for a profession, as accepted by config.from_dict."""
    p = BY_ID[pid]
    return {
        "profession": p.id, "skills": list(p.skills), "pitch": p.pitch, "freelancer_categories": list(p.freelancer),
        "reddit_subreddits": list(p.subreddits), "rss_feeds": list(p.feeds), "github": p.github,
        "github_labels": list(p.github_labels) or ["bounty"], "github_languages": list(p.github_languages),
        "mastodon_tags": list(p.mastodon_tags), "categories": list(p.local) or ["restaurant", "dentist"],
    }


def summary() -> list[dict]:
    """For the UI: id, skills and whether local business search fits this work."""
    return [{"id": p.id, "skills": list(p.skills), "pitch": p.pitch, "local": bool(p.local),
             "categories": list(p.local)} for p in PROFESSIONS]
