"""Safe deterministic renderers for aggregate genealogy coverage."""

from __future__ import annotations

from dataclasses import asdict
import json

from genealogy.coverage import CoverageReport


def _coverage_units(report: CoverageReport) -> dict[str, dict[str, int]]:
    units: dict[str, dict[str, int]] = {}
    for metric in sorted(report.metrics, key=lambda item: item.name):
        summary = units.setdefault(
            metric.unit,
            {"eligible": metric.eligible, "metric_count": 0},
        )
        if summary["eligible"] != metric.eligible:
            raise ValueError(
                f"inconsistent eligible count for unit {metric.unit}"
            )
        summary["metric_count"] += 1
    return dict(sorted(units.items()))


def _summary(report: CoverageReport) -> dict[str, object]:
    people = report.metric("people")
    return {
        "anomaly_type_count": len(report.anomalies),
        "coverage_units": _coverage_units(report),
        "eligible_people": people.eligible,
        "metric_count": len(report.metrics),
    }


def render_coverage_markdown(report: CoverageReport) -> str:
    """Render aggregate-only Markdown with summary counts first."""
    summary = _summary(report)
    lines = [
        "# TL;DR",
        "",
        (
            f"Cohort {report.cohort} has "
            f"{summary['eligible_people']} eligible people across "
            f"{summary['metric_count']} coverage metrics, with "
            f"{summary['anomaly_type_count']} anomaly types flagged "
            "for review."
        ),
        "",
        "## Summary counts",
        "",
        f"- Eligible people: {summary['eligible_people']}",
        f"- Coverage metrics: {summary['metric_count']}",
    ]
    coverage_units = summary["coverage_units"]
    if not isinstance(coverage_units, dict):
        raise TypeError("coverage unit summary must be a dictionary")
    for unit, counts in sorted(coverage_units.items()):
        metric_count = counts["metric_count"]
        metric_label = "metric" if metric_count == 1 else "metrics"
        lines.append(
            f"- {unit}: {metric_count} {metric_label}, "
            f"{counts['eligible']} eligible"
        )
    lines.extend(
        [
            f"- Anomaly types: {summary['anomaly_type_count']}",
            f"- Evidence floor: `{report.evidence_floor}`",
            "",
            "## Snapshot acquisitions",
            "",
            (
                "These immutable RootsMagic source counts distinguish "
                "acquisitions and are not cohort denominators."
            ),
            "",
            "| Snapshot | People | Families | Child links | Events | Places |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for acquisition in report.snapshot_acquisitions:
        lines.append(
            "| "
            + " | ".join(
                (
                    acquisition.snapshot_id,
                    str(acquisition.people),
                    str(acquisition.families),
                    str(acquisition.child_links),
                    str(acquisition.events),
                    str(acquisition.places),
                )
            )
            + " |"
        )
    if not report.snapshot_acquisitions:
        lines.append("| None | 0 | 0 | 0 | 0 | 0 |")
    lines.extend(
        [
            "## Coverage metrics",
            "",
            (
                "Each row states its own eligible, included, and unknown "
                "denominator for the selected cohort."
            ),
            "",
            (
                "| Metric | Unit | Eligible | Included | Unknown | Cohort | "
                "Evidence floor |"
            ),
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for metric in sorted(report.metrics, key=lambda item: item.name):
        lines.append(
            "| "
            + " | ".join(
                (
                    metric.name,
                    metric.unit,
                    str(metric.eligible),
                    str(metric.included),
                    str(metric.unknown),
                    metric.cohort,
                    metric.evidence_floor,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Anomalies",
            "",
            (
                "Anomalies remain visible for review and are not promoted "
                "to accepted evidence."
            ),
            "",
        ]
    )
    for name, count in sorted(report.anomalies.items()):
        lines.append(f"- {name}: {count}")
    return "\n".join(lines) + "\n"


def render_coverage_json(report: CoverageReport) -> str:
    """Render aggregate-only sorted JSON with a terminal newline."""
    payload = {
        "anomalies": dict(sorted(report.anomalies.items())),
        "cohort": report.cohort,
        "evidence_floor": report.evidence_floor,
        "metrics": [
            asdict(metric)
            for metric in sorted(report.metrics, key=lambda item: item.name)
        ],
        "snapshot_acquisitions": [
            asdict(acquisition) for acquisition in report.snapshot_acquisitions
        ],
        "summary": _summary(report),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
