"""
market_matching.py

Cross-platform market matching based on extracted structure instead of
surface-form string similarity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "be",
    "by",
    "close",
    "end",
    "market",
    "of",
    "on",
    "the",
    "will",
}

INSTRUMENT_ALIASES = {
    "sp500": (
        "s&p 500",
        "s and p 500",
        "sp 500",
        "spx",
    ),
    "nasdaq100": (
        "nasdaq 100",
        "ndx",
        "qqq",
    ),
    "dow": (
        "dow jones",
        "dow",
        "djia",
    ),
    "bitcoin": (
        "bitcoin",
        "btc",
        "xbt",
    ),
    "ethereum": (
        "ethereum",
        "ether",
        "eth",
    ),
}

COMPARATOR_PATTERNS = (
    ("at_or_above", (r"\bat or above\b", r"\bat least\b", r"\bnot below\b")),
    ("at_or_below", (r"\bat or below\b", r"\bat most\b", r"\bnot above\b")),
    ("above", (r"\babove\b", r"\bover\b", r"\bhigher than\b", r"\bgreater than\b")),
    ("below", (r"\bbelow\b", r"\bunder\b", r"\blower than\b", r"\bless than\b")),
)


@dataclass(frozen=True)
class MarketSignature:
    venue: str
    market_id: str
    label: str
    raw_text: str
    instrument: Optional[str]
    threshold: Optional[float]
    comparator: Optional[str]
    event_date: Optional[date]
    date_alias: Optional[str]
    tokens: frozenset[str]


@dataclass(frozen=True)
class MatchResult:
    kalshi_ticker: str
    kalshi_title: str
    kalshi_price: float
    poly_id: str
    poly_question: str
    poly_price: float
    score: float
    reasons: tuple[str, ...]

    @property
    def spread(self) -> float:
        return abs(self.kalshi_price - self.poly_price)


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9.%/ ]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _tokenize(text: str) -> frozenset[str]:
    tokens = {
        tok
        for tok in _normalize_text(text).split()
        if len(tok) > 1 and tok not in STOPWORDS and not tok.isdigit()
    }
    return frozenset(tokens)


def _extract_instrument(text: str) -> Optional[str]:
    norm = _normalize_text(text)
    for canonical, aliases in INSTRUMENT_ALIASES.items():
        if any(alias in norm for alias in aliases):
            return canonical
    return None


def _extract_comparator(text: str) -> Optional[str]:
    norm = _normalize_text(text)
    for comparator, patterns in COMPARATOR_PATTERNS:
        if any(re.search(pattern, norm) for pattern in patterns):
            return comparator
    return None


def _extract_threshold(text: str) -> Optional[float]:
    norm = _normalize_text(text)
    patterns = (
        r"(?:above|over|below|under|at least|at most|at or above|at or below)\s+\$?([0-9]+(?:\.[0-9]+)?)",
        r"\b([0-9]{3,6}(?:\.[0-9]+)?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, norm)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _extract_date_alias(text: str) -> Optional[str]:
    norm = _normalize_text(text)
    if "end of year" in norm or "year end" in norm or "eoy" in norm:
        return "eoy"
    if "end of month" in norm or "month end" in norm or "eom" in norm:
        return "eom"
    return None


def _extract_date_from_text(text: str) -> Optional[date]:
    norm = _normalize_text(text)
    match = re.search(
        r"\b("
        r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
        r")[a-z]*\s+([0-9]{1,2})(?:,?\s+([0-9]{2,4}))?\b",
        norm,
    )
    if not match:
        return None

    month = MONTHS[match.group(1)[:3]]
    day = int(match.group(2))
    year_raw = match.group(3)
    year = 2000 + int(year_raw) if year_raw and len(year_raw) == 2 else int(year_raw or date.today().year)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_date_from_ticker(ticker: str) -> Optional[date]:
    match = re.search(r"-(\d{2})([A-Z]{3})(\d{2})-", ticker)
    if not match:
        return None
    year = 2000 + int(match.group(1))
    month = MONTHS.get(match.group(2).lower())
    day = int(match.group(3))
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _compare_dates(left: MarketSignature, right: MarketSignature) -> bool:
    if left.event_date and right.event_date:
        return left.event_date == right.event_date
    if left.event_date and right.date_alias == "eoy":
        return left.event_date.month == 12 and left.event_date.day == 31
    if right.event_date and left.date_alias == "eoy":
        return right.event_date.month == 12 and right.event_date.day == 31
    return left.date_alias is not None and left.date_alias == right.date_alias


def _numeric_match(left: float, right: float) -> bool:
    return abs(left - right) < 1e-9


def build_kalshi_signature(ticker: str, data: dict) -> MarketSignature:
    title = data.get("title") or ticker
    combined = f"{ticker} {title}"
    return MarketSignature(
        venue="kalshi",
        market_id=ticker,
        label=title,
        raw_text=combined,
        instrument=_extract_instrument(combined),
        threshold=_extract_threshold(title) or _extract_threshold(ticker),
        comparator=_extract_comparator(title),
        event_date=_extract_date_from_ticker(ticker) or _extract_date_from_text(title),
        date_alias=_extract_date_alias(title),
        tokens=_tokenize(title),
    )


def build_poly_signature(market_id: str, data: dict) -> MarketSignature:
    question = data.get("question") or market_id
    return MarketSignature(
        venue="polymarket",
        market_id=market_id,
        label=question,
        raw_text=question,
        instrument=_extract_instrument(question),
        threshold=_extract_threshold(question),
        comparator=_extract_comparator(question),
        event_date=_extract_date_from_text(question),
        date_alias=_extract_date_alias(question),
        tokens=_tokenize(question),
    )


def score_match(left: MarketSignature, right: MarketSignature) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []
    score = 0.0

    if left.instrument and right.instrument:
        if left.instrument != right.instrument:
            return 0.0, ("instrument mismatch",)
        score += 0.35
        reasons.append(f"instrument={left.instrument}")

    if left.threshold is not None and right.threshold is not None:
        if not _numeric_match(left.threshold, right.threshold):
            return 0.0, ("threshold mismatch",)
        score += 0.25
        reasons.append(f"threshold={left.threshold:g}")

    if left.comparator and right.comparator:
        if left.comparator != right.comparator:
            return 0.0, ("comparator mismatch",)
        score += 0.15
        reasons.append(f"comparator={left.comparator}")

    if (left.event_date or left.date_alias) and (right.event_date or right.date_alias):
        if not _compare_dates(left, right):
            return 0.0, ("date mismatch",)
        score += 0.20
        if left.event_date and right.event_date:
            reasons.append(f"date={left.event_date.isoformat()}")
        else:
            reasons.append("date_alias match")

    if left.tokens and right.tokens:
        overlap = left.tokens & right.tokens
        union = left.tokens | right.tokens
        token_score = len(overlap) / len(union)
        if token_score > 0:
            score += min(token_score, 0.10)
            reasons.append(f"token_overlap={len(overlap)}")

    return min(score, 1.0), tuple(reasons)


def find_cross_platform_matches(
    kalshi_data: dict[str, dict],
    poly_data: dict[str, dict],
    min_score: float = 0.65,
) -> list[MatchResult]:
    poly_signatures = {
        mid: build_poly_signature(mid, data)
        for mid, data in poly_data.items()
    }

    candidates: list[MatchResult] = []
    for ticker, k_data in kalshi_data.items():
        k_sig = build_kalshi_signature(ticker, k_data)
        best_match: Optional[MatchResult] = None
        for mid, p_data in poly_data.items():
            p_sig = poly_signatures[mid]
            score, reasons = score_match(k_sig, p_sig)
            if score < min_score:
                continue
            candidate = MatchResult(
                kalshi_ticker=ticker,
                kalshi_title=k_data.get("title") or ticker,
                kalshi_price=float(k_data.get("price") or 0.0),
                poly_id=mid,
                poly_question=p_data.get("question") or mid,
                poly_price=float(p_data.get("price") or 0.0),
                score=score,
                reasons=reasons,
            )
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate
        if best_match is not None:
            candidates.append(best_match)

    candidates.sort(key=lambda item: (-item.score, -item.spread, item.kalshi_ticker))
    return candidates
