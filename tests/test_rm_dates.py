import pytest

from genealogy.rm_dates import ParsedDate, PartialDate, parse_rm_date


@pytest.mark.parametrize(
    ("raw", "modifier", "start", "end", "status"),
    [
        ("D.+19331018..+00000000..", "exact", PartialDate(1933, 10, 18), None, "parsed"),
        ("D.+18200000..+00000000..", "exact", PartialDate(1820, None, None), None, "parsed"),
        ("DA+18700101..+00000000..", "after", PartialDate(1870, 1, 1), None, "parsed"),
        ("DB+18480214..+00000000..", "before", PartialDate(1848, 2, 14), None, "parsed"),
        (
            "DR+17980000..+18020000..",
            "range",
            PartialDate(1798, None, None),
            PartialDate(1802, None, None),
            "parsed",
        ),
        (".", "unknown", None, None, "empty"),
        ("unexpected", "unknown", None, None, "unparsed"),
    ],
)
def test_parse_rm_date_observed_values(
    raw: str,
    modifier: str,
    start: PartialDate | None,
    end: PartialDate | None,
    status: str,
) -> None:
    """A changed RootsMagic date modifier or decoder branch must be visible."""
    parsed = parse_rm_date(raw)

    assert parsed == ParsedDate(raw, modifier, start, end, status)


@pytest.mark.parametrize(
    "raw",
    [
        "D.+19000230..+00000000..",
        "D.+19001300..+00000000..",
        "D.+19000001..+00000000..",
        "D.+00000101..+00000000..",
        "DR+17980000..+00000000..",
    ],
)
def test_parse_rm_date_rejects_invalid_or_incomplete_calendar_values(raw: str) -> None:
    """An invalid calendar date or incomplete range must not become a fact."""
    parsed = parse_rm_date(raw)

    assert parsed == ParsedDate(raw, "unknown", None, None, "unparsed")


@pytest.mark.parametrize(
    "raw",
    ["", " D.+19331018..+00000000..", "D.+19331018..+00000000.. ", "D.\ud800"],
)
def test_parse_rm_date_keeps_unsupported_input_verbatim(raw: str) -> None:
    """Unsupported strings must remain available for review without parser errors."""
    parsed = parse_rm_date(raw)

    assert parsed.original == raw
    assert parsed.parse_status == "unparsed"
