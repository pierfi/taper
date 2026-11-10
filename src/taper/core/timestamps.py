"""Pure helpers for time values and timestamps found in video descriptions.

All times are integer milliseconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "M:SS", "MM:SS" or "H:MM:SS" (first group up to 3 digits so "120:30" works).
_TIME = r"(?<![\d:])\d{1,3}:\d{2}(?::\d{2})?(?!\d|:\d)"
_OPEN = r"[\[(]?"
_CLOSE = r"[\])]?"
_BULLET = r"[^\w\[(]*"  # any run of bullets/emoji/symbols/spaces before the time
_NUMBERING = r"(?:#?\d{1,3}[.)]?\s+)?"
_SEP = r"[\s\-–\u2014:|~>]*"

_RANGE_RE = re.compile(
    rf"^{_BULLET}{_NUMBERING}{_OPEN}(?P<t1>{_TIME}){_CLOSE}\s*[-–\u2014~>]+\s*"
    rf"{_OPEN}(?P<t2>{_TIME}){_CLOSE}{_SEP}(?P<title>.*)$"
)
_LEADING_RE = re.compile(
    rf"^{_BULLET}{_NUMBERING}{_OPEN}(?P<t1>{_TIME}){_CLOSE}{_SEP}(?P<title>.*)$"
)
_TRAILING_RE = re.compile(rf"^(?P<title>.*?\S)\s*[-–\u2014:|~(\[]*\s*(?P<t1>{_TIME}){_CLOSE}\s*$")
_STARTS_WITH_TIME = re.compile(rf"^{_OPEN}{_TIME}")

_LIST_NUMBER = re.compile(r"^(?:#\d{1,3}[.)]?|\d{1,3}[.)])\s+")
_DECORATION = " \t-–\u2014:|~>*•·"


@dataclass(frozen=True)
class TimestampEntry:
    start_ms: int
    end_ms: int | None  # only for "00:00 - 04:12 Title" lines
    title: str


def parse_time(text: str) -> int:
    """Parse "H:MM:SS(.mmm)", "M:SS(.f)" or plain seconds ("90", "90.5") to milliseconds."""
    value = text.strip()
    if not value:
        raise ValueError("tempo vuoto")
    try:
        if ":" not in value:
            seconds = float(value)
            if seconds < 0:
                raise ValueError
            return round(seconds * 1000)
        parts = value.split(":")
        if len(parts) not in (2, 3):
            raise ValueError
        *head, last = parts
        ints = [int(p) for p in head]
        seconds = float(last)
        if not 0 <= seconds < 60 or any(i < 0 for i in ints):
            raise ValueError
        if len(parts) == 3 and not 0 <= ints[1] < 60:
            raise ValueError
        total = 0
        for i in ints:
            total = total * 60 + i
        return round((total * 60 + seconds) * 1000)
    except (ValueError, OverflowError):  # OverflowError: "inf"
        raise ValueError(f"tempo non valido: {text!r}") from None


def format_time(ms: int) -> str:
    """`H:MM:SS.mmm` (always the same shape, easy to read and to edit)."""
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_short(ms: int) -> str:
    """`M:SS` or `H:MM:SS` for human-facing summaries."""
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _clean_title(title: str) -> str:
    return title.strip(_DECORATION).strip()


def _safe_time(text: str) -> int | None:
    try:
        return parse_time(text)
    except ValueError:
        return None


def _scan(lines: list[str], style: str) -> list[TimestampEntry]:
    entries: list[TimestampEntry] = []
    for line in lines:
        if style == "range":
            m = _RANGE_RE.match(line)
            if not m:
                continue
            start, end = _safe_time(m["t1"]), _safe_time(m["t2"])
            if start is None or end is None or end <= start:
                continue
            entries.append(TimestampEntry(start, end, _clean_title(m["title"])))
        elif style == "leading":
            m = _LEADING_RE.match(line)
            if not m or _STARTS_WITH_TIME.match(m["title"].lstrip(_DECORATION)):
                continue
            start = _safe_time(m["t1"])
            if start is None:
                continue
            entries.append(TimestampEntry(start, None, _clean_title(m["title"])))
        else:  # trailing
            m = _TRAILING_RE.match(line)
            if not m or _STARTS_WITH_TIME.match(m["title"]):
                continue
            start = _safe_time(m["t1"])
            if start is None:
                continue
            title = _LIST_NUMBER.sub("", _clean_title(m["title"]))
            entries.append(TimestampEntry(start, None, title))
    return _keep_increasing(entries)


def _keep_increasing(entries: list[TimestampEntry]) -> list[TimestampEntry]:
    """Drop entries that do not move forward in time (stray timestamps in comments)."""
    kept: list[TimestampEntry] = []
    for entry in entries:
        if not kept or entry.start_ms > kept[-1].start_ms:
            kept.append(entry)
    return kept


def parse_description_timestamps(text: str) -> list[TimestampEntry]:
    """Find a track list in a video description.

    Supports "00:00 Title", "1:02:33 - Title", "[00:00] Title", "(1:02) Title",
    "1. 00:00 Title", "Title 00:00" and ranges "00:00 - 04:12 Title" (the second
    time is the END of the track). The dominant style wins, so a stray timestamp in
    a sentence does not pollute the list. At least 2 entries are required.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Priority breaks ties: range > leading > trailing.
    best: list[TimestampEntry] = []
    for style in ("range", "leading", "trailing"):
        found = _scan(lines, style)
        if len(found) > len(best):
            best = found
    return best if len(best) >= 2 else []
