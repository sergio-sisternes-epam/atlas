#!/usr/bin/env python3
"""Validate panel receipts and render the external recommendation."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


LENS_IDS = {
    "atlas-contract",
    "python-cli",
    "skill-agent-contract",
    "security-gitops",
}
SEVERITIES = ("Blocker", "Recommended", "Nit")
STANCES = {
    "ship now",
    "ship with follow-ups",
    "needs discussion",
    "needs rework",
}


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be non-empty text of at most {maximum} chars")
    return value.strip()


def validate_panelist(receipt: Any) -> None:
    if not isinstance(receipt, dict):
        raise ValueError("panelist receipt must be an object")
    required = {"lens_id", "status", "summary", "coverage", "findings", "limitations"}
    if set(receipt) != required:
        raise ValueError("panelist receipt fields do not match the schema")
    if receipt["lens_id"] not in LENS_IDS:
        raise ValueError("unknown lens_id")
    if receipt["status"] not in {"ran", "failed"}:
        raise ValueError("unknown panelist status")
    _text(receipt["summary"], "summary", 200)
    coverage = receipt["coverage"]
    if not isinstance(coverage, list) or not 1 <= len(coverage) <= 3:
        raise ValueError("coverage must contain one to three checks")
    for item in coverage:
        _text(item, "coverage item", 200)
    findings = receipt["findings"]
    if not isinstance(findings, list) or len(findings) > 10:
        raise ValueError("findings must be a list of at most ten items")
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("finding must be an object")
        required_finding = {"severity", "title", "rationale", "follow_up"}
        optional_finding = {"path", "line", "evidence"}
        if not required_finding <= set(finding) or set(finding) - (
            required_finding | optional_finding
        ):
            raise ValueError("finding fields do not match the schema")
        if finding["severity"] not in SEVERITIES:
            raise ValueError("unknown finding severity")
        _text(finding["title"], "finding title", 100)
        _text(finding["rationale"], "finding rationale", 500)
        _text(finding["follow_up"], "finding follow_up", 300)
        if "line" in finding:
            if "path" not in finding:
                raise ValueError("a finding line requires a path")
            if not isinstance(finding["line"], int) or finding["line"] < 1:
                raise ValueError("finding line must be a positive integer")
        if "path" in finding:
            path = _text(finding["path"], "finding path", 300)
            if path.startswith("/") or ".." in Path(path).parts:
                raise ValueError("finding path must be repo-relative")
        if "evidence" in finding:
            _text(finding["evidence"], "finding evidence", 500)
    limitations = receipt["limitations"]
    if not isinstance(limitations, list) or len(limitations) > 3:
        raise ValueError("limitations must be a list of at most three items")
    for item in limitations:
        _text(item, "limitation", 200)


def validate_synthesizer(receipt: Any, panelists: list[dict[str, Any]]) -> None:
    if not isinstance(receipt, dict):
        raise ValueError("synthesizer receipt must be an object")
    required = {"headline", "synthesis", "top_items", "ship_recommendation"}
    optional = {"dissent"}
    if not required <= set(receipt) or set(receipt) - (required | optional):
        raise ValueError("synthesizer receipt fields do not match the schema")
    _text(receipt["headline"], "headline", 200)
    _text(receipt["synthesis"], "synthesis", 700)
    if "dissent" in receipt:
        _text(receipt["dissent"], "dissent", 400)
    top_items = receipt["top_items"]
    if not isinstance(top_items, list) or len(top_items) > 3:
        raise ValueError("top_items must contain at most three items")
    source_findings = {
        (panelist["lens_id"], finding["severity"], finding["title"])
        for panelist in panelists
        for finding in panelist["findings"]
    }
    for item in top_items:
        if not isinstance(item, dict) or set(item) != {
            "lens_id",
            "severity",
            "title",
            "why",
        }:
            raise ValueError("top item fields do not match the schema")
        key = (item["lens_id"], item["severity"], item["title"])
        if key not in source_findings:
            raise ValueError("top item does not match an input finding")
        _text(item["why"], "top item why", 300)
    recommendation = receipt["ship_recommendation"]
    if not isinstance(recommendation, dict) or set(recommendation) != {
        "stance",
        "rationale",
    }:
        raise ValueError("ship_recommendation fields do not match the schema")
    if recommendation["stance"] not in STANCES:
        raise ValueError("unknown recommendation stance")
    _text(recommendation["rationale"], "recommendation rationale", 500)


def validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {"panelists", "synthesizer"}:
        raise ValueError("fixture must contain panelists and synthesizer")
    panelists = payload["panelists"]
    if not isinstance(panelists, list) or not 1 <= len(panelists) <= 4:
        raise ValueError("panelists must contain one to four receipts")
    for panelist in panelists:
        validate_panelist(panelist)
    lens_ids = [panelist["lens_id"] for panelist in panelists]
    if len(lens_ids) != len(set(lens_ids)):
        raise ValueError("panelist lens ids must be unique")
    validate_synthesizer(payload["synthesizer"], panelists)


def inline_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    validate_payload(payload)
    return [
        finding
        for panelist in payload["panelists"]
        for finding in panelist["findings"]
        if "path" in finding and "line" in finding
    ]


def _safe(value: str) -> str:
    return html.escape(value, quote=False)


def _table(value: str) -> str:
    return _safe(value).replace("|", "\\|").replace("\n", " ")


def render_summary(payload: dict[str, Any]) -> str:
    validate_payload(payload)
    panelists = payload["panelists"]
    synthesis = payload["synthesizer"]
    recommendation = synthesis["ship_recommendation"]
    lines = [
        f"## Atlas panel: {_safe(recommendation['stance'])}",
        "",
        f"**{_safe(synthesis['headline'])}**",
        "",
        _safe(synthesis["synthesis"]),
    ]
    if synthesis.get("dissent"):
        lines.extend(["", "### Dissent", "", _safe(synthesis["dissent"])])
    lines.extend(
        [
            "",
            "| Lens | Blocker | Recommended | Nits | Takeaway |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for panelist in panelists:
        counts = {
            severity: sum(
                finding["severity"] == severity for finding in panelist["findings"]
            )
            for severity in SEVERITIES
        }
        lines.append(
            f"| `{panelist['lens_id']}` | {counts['Blocker']} | "
            f"{counts['Recommended']} | {counts['Nit']} | "
            f"{_table(panelist['summary'])} |"
        )
    if synthesis["top_items"]:
        lines.extend(["", "### Top items", ""])
        for index, item in enumerate(synthesis["top_items"], start=1):
            lines.append(
                f"{index}. **{item['severity']} - {_safe(item['title'])}** "
                f"(`{item['lens_id']}`): {_safe(item['why'])}"
            )
    lines.extend(
        [
            "",
            "### Advisory recommendation",
            "",
            _safe(recommendation["rationale"]),
        ]
    )
    for panelist in panelists:
        lines.extend(
            [
                "",
                "<details>",
                f"<summary>{panelist['lens_id']} - "
                f"{_safe(panelist['summary'])}</summary>",
                "",
                "**Coverage**",
                "",
            ]
        )
        lines.extend(f"- {_safe(item)}" for item in panelist["coverage"])
        if panelist["limitations"]:
            lines.extend(["", "**Limitations**", ""])
            lines.extend(f"- {_safe(item)}" for item in panelist["limitations"])
        lines.extend(["", "**Findings**", ""])
        if not panelist["findings"]:
            lines.append("No findings after the checks above.")
        for finding in panelist["findings"]:
            location = ""
            if "path" in finding:
                location = f" - `{finding['path']}"
                if "line" in finding:
                    location += f":{finding['line']}"
                location += "`"
            entry = (
                f"- **{finding['severity']}** - {_safe(finding['title'])}"
                f"{location} - {_safe(finding['rationale'])} "
                f"Follow-up: {_safe(finding['follow_up'])}"
            )
            if finding.get("evidence"):
                entry += f" Evidence: {_safe(finding['evidence'])}"
            lines.append(entry)
        lines.extend(["", "</details>"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a panel fixture and render its Markdown summary."
    )
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    print(render_summary(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
