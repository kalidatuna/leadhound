"""Money in any currency: find budgets in text and compare them with your minimum.

Exchange rates are approximate (USD per 1 unit). They are only used to compare a budget with
your minimum, never shown as exact figures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# code: (symbols that unambiguously mean this currency, approx USD per unit)
CURRENCIES = {
    "USD": (("$", "US$"), 1.0), "EUR": (("€",), 1.08), "GBP": (("£",), 1.27), "INR": (("₹",), 0.012),
    "GEL": (("₾",), 0.37), "RUB": (("₽",), 0.011), "UAH": (("₴",), 0.024), "TRY": (("₺",), 0.03),
    "BRL": (("R$",), 0.18), "JPY": (("¥", "JP¥"), 0.0067), "CNY": (("CN¥", "元"), 0.14), "KRW": (("₩",), 0.00073),
    "CAD": (("C$", "CA$"), 0.73), "AUD": (("A$", "AU$"), 0.65), "NZD": (("NZ$",), 0.6), "MXN": (("MX$",), 0.055),
    "CHF": ((), 1.13), "PLN": (("zł",), 0.25), "CZK": (("Kč",), 0.043), "SEK": ((), 0.095), "NOK": ((), 0.093),
    "DKK": ((), 0.145), "HUF": (("Ft",), 0.0027), "RON": (("lei",), 0.22), "NGN": (("₦",), 0.00065),
    "PHP": (("₱",), 0.017), "PKR": ((), 0.0036), "BDT": (("৳",), 0.0083), "IDR": (("Rp",), 0.000063),
    "VND": (("₫",), 0.00004), "THB": (("฿",), 0.029), "MYR": (("RM",), 0.22), "SGD": (("S$",), 0.75),
    "HKD": (("HK$",), 0.13), "ZAR": ((), 0.055), "EGP": ((), 0.02), "KES": (("KSh",), 0.0077),
    "AED": (("د.إ",), 0.27), "SAR": (("﷼",), 0.27), "ILS": (("₪",), 0.27), "KZT": (("₸",), 0.002),
    "AMD": (("֏",), 0.0026), "AZN": (("₼",), 0.59), "ARS": ((), 0.001), "CLP": ((), 0.0011), "COP": ((), 0.00025),
    "PEN": (("S/",), 0.27),
}
CODE_ALIASES = {"RMB": "CNY", "TL": "TRY", "RS": "INR", "EURO": "EUR", "EUROS": "EUR", "DOLLARS": "USD", "BUCKS": "USD"}
_SYMBOLS = sorted(((s, c) for c, (syms, _) in CURRENCIES.items() for s in syms), key=lambda x: -len(x[0]))
SYMBOL_TO_CODE = dict(_SYMBOLS)
_SYM_RX = "|".join(re.escape(s) for s, _ in _SYMBOLS)
_CODE_RX = "|".join(sorted(list(CURRENCIES) + list(CODE_ALIASES), key=len, reverse=True))
NUM = r"(\d{1,3}(?:[,.\s]\d{3})+(?![\d])|\d+(?:[.,]\d+)?)\s*([kKmM])?(?![\w])"
HOURLY = r"(\s*(?:/|per|an?)\s*(?:h|hr|hrs|hour|hora|heure|stunde|час)\b)"
TOKEN = rf"(?:({_SYM_RX})\s*{NUM}(?:\s*({_CODE_RX})\b)?|{NUM}\s*(?:({_SYM_RX})|({_CODE_RX})\b))"
RANGE_RX = re.compile(rf"{TOKEN}\s*(?:-|–|to|a|bis|до)\s*{TOKEN}{HOURLY}?", re.I)
HALF_RANGE_RX = re.compile(rf"{TOKEN}\s*(?:-|–|to|a|bis|до)\s*{NUM}{HOURLY}?", re.I)  # "$100-150k"
SINGLE_RX = re.compile(rf"{TOKEN}{HOURLY}?", re.I)
LABELLED_RX = re.compile(rf"\b(?:budget|pay(?:ing)?|rate|compensation|presupuesto|orçamento|бюджет)\b\s*(?:is|of|:)?\s*{NUM}", re.I)
MULT = {"k": 1_000, "m": 1_000_000}


@dataclass
class Budget:
    low: float
    high: float
    hourly: bool
    text: str
    currency: str = ""  # ISO code, "" when the text gives none

    def usd(self, which: str = "high") -> float | None:
        return to_usd(self.high if which == "high" else self.low, self.currency)


def _num(raw: str, mult: str | None) -> float:
    raw = raw.strip()
    if re.fullmatch(r"\d{1,3}(?:[,.\s]\d{3})+", raw):
        raw = re.sub(r"[,.\s]", "", raw)  # thousands separators: 1,500 / 1.500 / 1 500
    else:
        raw = raw.replace(",", ".")
    return float(raw) * MULT.get((mult or "").lower(), 1)


def _code(sym: str | None, code: str | None) -> str:
    if code:
        c = code.upper()
        return CODE_ALIASES.get(c, c)
    return SYMBOL_TO_CODE.get(sym or "", "") or ("USD" if sym == "$" else "")


def _token(g: tuple) -> tuple[float, str | None, str]:
    """g = groups of one TOKEN match: (sym, num, mult, code, num2, mult2, sym2, code2)."""
    sym, num, mult, code, num2, mult2, sym2, code2 = g
    if num:
        return _num(num, mult), mult, _code(sym, code)
    return _num(num2, mult2), mult2, _code(sym2, code2)


def parse_budget(text: str) -> Budget | None:
    """Find the first money amount or range. Returns None if no explicit amount."""
    text = text or ""
    m = RANGE_RX.search(text)
    if m:
        g = m.groups()
        lo, lo_mult, c1 = _token(g[0:8])
        hi, hi_mult, c2 = _token(g[8:16])
        if not lo_mult and hi_mult:  # "$100-150k": the low end shares the high end's multiplier
            lo *= MULT[hi_mult.lower()]
        return Budget(min(lo, hi), max(lo, hi), bool(g[16]), m.group(0).strip(), c2 or c1)
    m = HALF_RANGE_RX.search(text)
    if m:
        g = m.groups()
        lo, lo_mult, c = _token(g[0:8])
        hi = _num(g[8], g[9])
        if not lo_mult and g[9]:
            lo *= MULT[g[9].lower()]
        if hi >= lo:
            return Budget(lo, hi, bool(g[10]), m.group(0).strip(), c)
    m = SINGLE_RX.search(text)
    if m:
        v, _, c = _token(m.groups()[0:8])
        return Budget(v, v, bool(m.groups()[8]), m.group(0).strip(), c)
    m = LABELLED_RX.search(text)
    if m:
        v = _num(m.group(1), m.group(2))
        hourly = bool(re.match(HOURLY, text[m.end():m.end() + 14], re.I))
        return Budget(v, v, hourly, m.group(0).strip(), "")
    return None


def to_usd(amount: float, code: str) -> float | None:
    if not code or code not in CURRENCIES:
        return None
    return amount * CURRENCIES[code][1]


def compare_min(b: Budget, minimum: float, my_currency: str) -> bool | None:
    """True if the budget meets the minimum, False if below, None if it can't be compared."""
    if not minimum:
        return True
    cur = b.currency or my_currency  # no currency in the text: assume the user's own
    if cur == my_currency:
        return b.high >= minimum
    have, need = to_usd(b.high, cur), to_usd(minimum, my_currency)
    if have is None or need is None:
        return None
    return have >= need
