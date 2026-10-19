import re
from datetime import datetime

DATE_FORMATS = [
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%B-%Y",
    "%d %B %Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d.%m.%Y",
]

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    text = re.sub(r"\s+\d{1,2}:\d{2}\s*(am|pm)?$", "", text, flags=re.I)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})[\s\-/]([A-Za-z]{3,9})[\s\-/,]*(\d{4})", text)
    if m:
        day, month_name, year = m.groups()
        month = MONTHS.get(month_name[:3].lower())
        if month:
            try:
                return datetime(int(year), month, int(day))
            except ValueError:
                return None
    return None


def parse_amount(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    m = re.search(r"([\d][\d,\.]*)", text.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


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
