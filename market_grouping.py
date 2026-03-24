"""
market_grouping.py

Heuristics for grouping flat market titles/questions into higher-level events.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


SPORTS_MATCHUP_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9.'& -]+?)\s+(?:vs\.?|v\.?|@|at)\s+([A-Z][A-Za-z0-9.'& -]+)\b"
)

DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"(?:\s+\d{1,2}(?:,?\s+\d{2,4})?|\s+\d{4})\b",
    re.IGNORECASE,
)

POLITICS_RE = re.compile(
    r"\b(president|presidential|senate|house|governor|mayor|election|primary|congress)\b",
    re.IGNORECASE,
)

FINANCE_RE = re.compile(
    r"\b(s&p 500|nasdaq|dow|bitcoin|btc|ethereum|eth|fed|interest rate|inflation|cpi|gdp|oil|gold)\b",
    re.IGNORECASE,
)

CRYPTO_RE = re.compile(
    r"\b(bitcoin|btc|ethereum|eth|solana|sol|dogecoin|doge|xrp)\b",
    re.IGNORECASE,
)

SPORT_HINTS = (
    " vs ",
    " vs. ",
    " at ",
    " @ ",
    "warriors",
    "lakers",
    "rockets",
    "nba",
    "nfl",
    "mlb",
    "nhl",
    "match",
    "game",
)


@dataclass(frozen=True)
class GroupedMarket:
    group: str
    title: str
    price: float
    volume: float
    market_id: str


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -,:?")


def canonicalize_group_label(label: str) -> str:
    text = label.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\beoy\b", "end of year", text)
    text = re.sub(r"\beom\b", "end of month", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return _normalize_space(text)


def infer_theme(text: str) -> str:
    lower = text.lower()
    if any(hint in lower for hint in SPORT_HINTS):
        return "sports"
    if POLITICS_RE.search(text):
        return "politics"
    if CRYPTO_RE.search(text):
        return "crypto"
    if FINANCE_RE.search(text):
        return "finance"
    return "general"


def _strip_trailing_market_question(text: str) -> str:
    text = DATE_RE.sub("", text)
    text = re.sub(r"\bwill\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhow many\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwhat (?:will|is|are)\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(close|finish|end|be above|be below|win|score)\b.*$", "", text, flags=re.IGNORECASE)
    return _normalize_space(text)


def _sports_group(text: str) -> str:
    match = SPORTS_MATCHUP_RE.search(text)
    if match:
        left = _normalize_space(match.group(1))
        right = _normalize_space(
            re.sub(
                r"\b(winner|moneyline|spread|total|points?|score|scorer|wins?)\b.*$",
                "",
                match.group(2),
                flags=re.IGNORECASE,
            )
        )
        return f"{left} vs {right}"

    cleaned = _strip_trailing_market_question(text)
    return cleaned or "Sports Event"


def _politics_group(text: str) -> str:
    date_match = DATE_RE.search(text)
    date_part = date_match.group(0) if date_match else ""

    office_match = POLITICS_RE.search(text)
    if office_match:
        office = office_match.group(1).lower()
        office = "presidential election" if office in {"president", "presidential"} else office
        label = office.title()
        return _normalize_space(f"{label} {date_part}")

    cleaned = _strip_trailing_market_question(text)
    return cleaned or "Politics Event"


def _finance_group(text: str) -> str:
    lower = text.lower()
    if "s&p 500" in lower:
        base = "S&P 500"
    elif "nasdaq" in lower:
        base = "Nasdaq"
    elif "dow" in lower:
        base = "Dow"
    elif "bitcoin" in lower or "btc" in lower:
        base = "Bitcoin"
    elif "ethereum" in lower or "eth" in lower:
        base = "Ethereum"
    elif "fed" in lower or "interest rate" in lower:
        base = "Fed Rates"
    elif "inflation" in lower or "cpi" in lower:
        base = "Inflation"
    elif "gdp" in lower:
        base = "GDP"
    elif "oil" in lower:
        base = "Oil"
    elif "gold" in lower:
        base = "Gold"
    else:
        base = _strip_trailing_market_question(text) or "Finance Event"

    date_match = DATE_RE.search(text)
    if date_match:
        date_text = date_match.group(0)
        if re.search(r"\bdec(?:ember)?\s+31\b", date_text, flags=re.IGNORECASE):
            return f"{base} EOY"
        return f"{base} {date_text}"
    if "end of year" in lower or "year end" in lower:
        return f"{base} EOY"
    if "end of month" in lower or "month end" in lower:
        return f"{base} EOM"
    return base


def _general_group(text: str) -> str:
    if ":" in text:
        return _normalize_space(text.split(":", 1)[0])
    if " - " in text:
        return _normalize_space(text.split(" - ", 1)[0])
    return _strip_trailing_market_question(text) or "Other Markets"


def derive_group_label(text: str) -> str:
    theme = infer_theme(text)
    if theme == "sports":
        return _sports_group(text)
    if theme == "politics":
        return _politics_group(text)
    if theme in {"finance", "crypto"}:
        return _finance_group(text)
    return _general_group(text)


def build_grouped_markets(markets: list[tuple[str, dict]], title_field: str) -> list[GroupedMarket]:
    grouped: list[GroupedMarket] = []
    for market_id, info in markets:
        title = info.get(title_field) or market_id
        grouped.append(
            GroupedMarket(
                group=derive_group_label(title),
                title=title,
                price=float(info.get("price") or 0),
                volume=float(info.get("volume") or 0),
                market_id=market_id,
            )
        )
    grouped.sort(key=lambda item: (item.group.lower(), -item.volume, item.title.lower()))
    return grouped


def summarize_groups(markets: list[tuple[str, dict]], title_field: str) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for market in build_grouped_markets(markets, title_field):
        key = canonicalize_group_label(market.group)
        bucket = summary.setdefault(
            key,
            {"label": market.group, "count": 0, "volume": 0.0, "markets": []},
        )
        bucket["count"] += 1
        bucket["volume"] += market.volume
        bucket["markets"].append(market)
    return summary
