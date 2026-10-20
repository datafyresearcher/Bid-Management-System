import re
from datetime import datetime, timezone


def source_id_for_code(db, code: str):
    """Resolve the registry row id for a source code.

    Records created outside a portal scan (manual entries, converted leads)
    still need to point at a source row so the dashboard can attribute them.
    """
    from sqlalchemy import select

    from app.models import Source

    row = db.execute(select(Source).where(Source.code == code)).scalars().first()
    return row.id if row else None


DATE_FORMATS = [
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%B-%Y",
    "%d %B %Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d-%b-%y",
    "%d %b %y",
    "%d/%m/%y",
    "%d-%m-%y",
]

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Urdu month names appear in bilingual (Urdu/English) tender notices.
URDU_MONTHS = {
    "جنوری": 1, "فروری": 2, "مارچ": 3, "اپریل": 4, "مئی": 5, "جون": 6,
    "جولائی": 7, "اگست": 8, "ستمبر": 9, "اکتوبر": 10, "نومبر": 11, "دسمبر": 12,
}

SCALE_WORDS = {
    "hundred": 100,
    "thousand": 1_000,
    "lakh": 100_000,
    "million": 1_000_000,
    "crore": 10_000_000,
    "billion": 1_000_000_000,
}


def utcnow() -> datetime:
    """Naive UTC timestamp, used for every stored datetime column.

    Stored values stay naive so existing rows and SQL comparisons keep working,
    but we avoid the deprecated ``datetime.utcnow()``.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_date(value):
    """Parse a date from a notice or document.

    Handles the formats Pakistani tender notices actually use: ``25-11-2026``,
    ``25 Nov 2026``, ``25 November 2026, 11:00 hours``, ``25th Nov 2026``,
    ``25/11/2026``, ``2026-11-25`` and ordinal/Urdu variants.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    text = re.sub(r"\s*\d{1,2}[:.]\d{2}\s*(am|pm)?\s*(hours|hrs|h)?\s*$", "", text, flags=re.I)
    text = re.sub(r"\s+(hours|hrs|hrs\.?|time|date|on|by)$", "", text, flags=re.I)
    text = text.strip().rstrip(",.").strip()

    # Ordinal suffixes: 25th, 3rd, 1st
    text = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.I)

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # Named month in any casing, with optional comma / separators.
    m = re.search(r"(\d{1,2})[\s\-/]*([A-Za-z]{3,9})[\s\-/,]*(\d{2,4})", text)
    if m:
        day, month_name, year = m.groups()
        month = MONTHS.get(month_name[:3].lower())
        if month:
            year_int = int(year)
            if year_int < 100:
                year_int += 2000
            try:
                return datetime(year_int, month, int(day))
            except ValueError:
                return None

    # Bilingual notices: numeric day with a Urdu month name.
    m = re.search(r"(\d{1,2})[\s\-/]*([؀-ۿ]{3,10})[\s\-/]*(\d{2,4})", text)
    if m:
        day, month_name, year = m.groups()
        month = URDU_MONTHS.get(month_name)
        if month:
            year_int = int(year)
            if year_int < 100:
                year_int += 2000
            try:
                return datetime(year_int, month, int(day))
            except ValueError:
                return None

    return None


def parse_amount(value):
    """Parse a monetary amount, tolerating Pakistani notation.

    Handles ``5,000,000``, ``Rs. 5,000,000/-``, ``PKR 25,000`` and
    ``2.5 million`` / ``5 billion`` style scale words.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if not text.strip():
        return None

    m = re.search(r"([\d][\d,\.]*)\s*([a-z]+)?", text, flags=re.I)
    if not m:
        return None
    number_text, trailing = m.group(1), (m.group(2) or "").lower()
    # A trailing word that is not a scale word means this was not a number.
    if trailing and trailing not in SCALE_WORDS:
        trailing = ""
    try:
        amount = float(number_text.replace(",", ""))
    except ValueError:
        return None
    if trailing:
        amount *= SCALE_WORDS[trailing]
    return amount


def parse_money(text: str):
    """Extract (amount, currency) from free text mentioning a currency.

    Returns ``(None, None)`` when no currency-denominated figure is present,
    so callers can distinguish "no bid security stated" from "found zero".
    """
    if not text:
        return None, None
    patterns = [
        r"(?:rs\.?|pkr)\s*\.?\s*([\d][\d,\.]*\s*(?:million|billion|crore|lakh|thousand)?)",
        r"(?:us\$|usd|\$)\s*([\d][\d,\.]*\s*(?:million|billion)?)",
    ]
    for idx, pattern in enumerate(patterns):
        m = re.search(pattern, text, flags=re.I)
        if m:
            currency = "PKR" if idx == 0 else "USD"
            amount = parse_amount(m.group(1))
            if amount is not None:
                return amount, currency
    return None, None


def detect_currency(text: str) -> str:
    if not text:
        return "PKR"
    t = text.lower()
    if "us$" in t or "usd" in t or "$" in t:
        return "USD"
    if "sar" in t or "riyal" in t:
        return "SAR"
    return "PKR"


def value_band(value, currency="PKR"):
    if value is None:
        return "unknown"
    v = value
    if currency == "USD":
        v = value * 280
    if v < 50_000_000:
        return "small"
    if v < 250_000_000:
        return "medium"
    if v < 1_000_000_000:
        return "large"
    return "mega"


def snippet(text: str, keyword: str, radius: int = 140) -> str:
    if not text:
        return ""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def sanitize_inline(text, limit: int = 200) -> str:
    """Flatten untrusted text to a single safe line.

    Portal titles and buyer names are attacker-controlled. Before they reach a
    prompt they are stripped of control characters and newlines, so a crafted
    title cannot forge a new field in the instruction block.
    """
    if text is None:
        return ""
    flat = re.sub(r"[\r\n\t]+", " ", str(text))
    flat = "".join(ch for ch in flat if ord(ch) >= 32)
    flat = re.sub(r"\s{2,}", " ", flat).strip()
    return flat[:limit]


def days_between(later, earlier) -> int:
    """Whole days between two datetimes, tolerant of None."""
    if not later or not earlier:
        return 0
    return (later - earlier).days
