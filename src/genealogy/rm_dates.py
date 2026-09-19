"""Explicit decoding for the RootsMagic date values observed in snapshots."""

from dataclasses import dataclass
from calendar import monthrange
from datetime import date
import re


DATE_PATTERN = re.compile(
    r"^(?P<kind>D\.|DA|DB|DR)\+(?P<start>\d{8})\.\.\+(?P<end>\d{8})\.\.$"
)

MODIFIERS = {"D.": "exact", "DA": "after", "DB": "before", "DR": "range"}


@dataclass(frozen=True)
class PartialDate:
    """A RootsMagic date with an optional month and day."""

    year: int | None
    month: int | None
    day: int | None


@dataclass(frozen=True)
class ParsedDate:
    """The original RootsMagic value and its explicit decoding result."""

    original: str
    modifier: str
    start: PartialDate | None
    end: PartialDate | None
    parse_status: str


def _decode_partial(raw: str) -> PartialDate | None | bool:
    """Return a partial date, no date for eight zeroes, or False if invalid."""
    if raw == "00000000":
        return None

    year = int(raw[:4])
    month = int(raw[4:6])
    day = int(raw[6:])
    if year == 0 or (month == 0 and day != 0) or not 0 <= month <= 12:
        return False
    if month == 0:
        return PartialDate(year, None, None)
    if day == 0:
        return PartialDate(year, month, None)

    try:
        date(year, month, day)
    except ValueError:
        return False
    return PartialDate(year, month, day)


def _unparsed(raw: str) -> ParsedDate:
    return ParsedDate(raw, "unknown", None, None, "unparsed")


def _bounds(value: PartialDate) -> tuple[date, date]:
    """Calendar bounds are for comparison only, never inferred source precision."""
    assert value.year is not None
    first_month=value.month or 1
    last_month=value.month or 12
    return (date(value.year,first_month,value.day or 1),
            date(value.year,last_month,value.day or monthrange(value.year,last_month)[1]))


def parse_rm_date(raw: str) -> ParsedDate:
    """Decode only observed RootsMagic date forms, retaining unparsed values."""
    if raw == ".":
        return ParsedDate(raw, "unknown", None, None, "empty")

    match = DATE_PATTERN.fullmatch(raw)
    if match is None:
        return _unparsed(raw)

    start = _decode_partial(match["start"])
    end = _decode_partial(match["end"])
    if start is False or end is False:
        return _unparsed(raw)

    modifier = MODIFIERS[match["kind"]]
    if modifier == "range":
        if start is None or end is None:
            return _unparsed(raw)
        if _bounds(start)[0] > _bounds(end)[1]:
            return _unparsed(raw)
    elif end is not None or start is None:
        return _unparsed(raw)

    return ParsedDate(raw, modifier, start, end, "parsed")
