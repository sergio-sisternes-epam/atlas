"""Opt-in per-type contracts over Atlas's existing frontmatter subset."""
from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .frontmatter import read_page
from .paths import RESERVED, SKIP_DIRS

FIELD_TYPES = {"string", "integer", "number", "boolean", "date"}


def _strings(value: object, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(isinstance(x, str) and bool(x.strip()) and x == x.strip() for x in value)
        and len(value) == len(set(value))
    )


def _number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def declaration_errors(name: str, block: object) -> list[str]:
    prefix = f"templates.by_type.{name}"
    errors: list[str] = []

    def bad(part: str, message: str) -> None:
        errors.append(f"{prefix}.{part}: {message}")

    if not isinstance(block, dict):
        return [f"{prefix} must be an object"]
    fm = block.get("frontmatter", {})
    if not isinstance(fm, dict):
        bad("frontmatter", "must be an object")
        fm = {}
    if "required" in fm and not _strings(fm["required"]):
        bad("frontmatter.required", "must be a unique list of nonempty field names")
    sections = block.get("sections", {})
    if not isinstance(sections, dict):
        bad("sections", "must be an object")
    else:
        for key in ("enforce", "require_content"):
            if key in sections and type(sections[key]) is not bool:
                bad(f"sections.{key}", "must be a boolean")
        if "required" in sections and (
            not _strings(sections["required"])
            or any("\n" in x or "\r" in x for x in sections["required"])
        ):
            bad("sections.required", "must be a unique list of single-line heading names")
        if sections.get("enforce") is True and "required" not in sections:
            bad("sections.required", "must be declared when enforce is true")
        if sections.get("require_content") is True and sections.get("enforce") is not True:
            bad("sections.require_content", "requires enforce: true")
        for key in sections.keys() - {"required", "recommended", "enforce", "require_content"}:
            bad(f"sections.{key}", "unsupported declaration")
    fields = fm.get("fields", {})
    if not isinstance(fields, dict):
        bad("frontmatter.fields", "must be an object")
        fields = {}
    for key, rule in fields.items():
        loc = f"frontmatter.fields.{key}"
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            bad(loc, "invalid scalar field name")
        if not isinstance(rule, dict):
            bad(loc, "must be an object")
            continue
        kind = rule.get("type")
        if not isinstance(kind, str) or kind not in FIELD_TYPES:
            bad(loc, "type must be string, integer, number, boolean, or date")
        for extra in rule.keys() - {"type", "enum", "unknown", "minimum", "maximum"}:
            bad(f"{loc}.{extra}", "unsupported declaration")
        for option in ("enum", "unknown"):
            if option in rule and not _strings(rule[option], nonempty=True):
                bad(f"{loc}.{option}", "must be a nonempty unique list of scalar strings")
        if "unknown" in rule and kind != "date":
            bad(loc, "unknown is supported only for date fields")
        if "enum" in rule and kind != "string":
            bad(loc, "enum is supported only for string fields")
        for bound in ("minimum", "maximum"):
            if bound in rule and (kind not in ("integer", "number") or not _number(rule[bound])):
                bad(f"{loc}.{bound}", "requires a finite numeric bound on integer/number")
        if _number(rule.get("minimum")) and _number(rule.get("maximum")):
            if rule["minimum"] > rule["maximum"]:
                bad(loc, "minimum exceeds maximum")
    orders = fm.get("date_order", [])
    if not isinstance(orders, list):
        bad("frontmatter.date_order", "must be a list")
    else:
        for i, rule in enumerate(orders):
            loc = f"frontmatter.date_order[{i}]"
            if not isinstance(rule, dict):
                bad(loc, "must be an object")
                continue
            for extra in rule.keys() - {"before", "after", "allow_equal"}:
                bad(f"{loc}.{extra}", "unsupported declaration")
            for key in ("before", "after"):
                field = rule.get(key)
                definition = fields.get(field) if isinstance(field, str) else None
                if not isinstance(definition, dict) or definition.get("type") != "date":
                    bad(loc, f"{key} must name a declared date field")
            if "allow_equal" in rule and type(rule["allow_equal"]) is not bool:
                bad(loc, "allow_equal must be a boolean")
    relations = block.get("relates_to", [])
    if not isinstance(relations, list):
        bad("relates_to", "must be a list")
    else:
        seen: set[str] = set()
        for i, rule in enumerate(relations):
            loc = f"relates_to[{i}]"
            if not isinstance(rule, dict):
                bad(loc, "must be an object")
                continue
            for extra in rule.keys() - {"kind", "target_types", "min", "max"}:
                bad(f"{loc}.{extra}", "unsupported declaration")
            kind = rule.get("kind")
            if not isinstance(kind, str) or not kind.strip() or kind != kind.strip():
                bad(loc, "kind must be a nonempty string")
            elif kind in seen:
                bad(loc, "duplicate kind")
            else:
                seen.add(kind)
            if not _strings(rule.get("target_types"), nonempty=True):
                bad(loc, "target_types must be a nonempty unique list")
            for bound in ("min", "max"):
                if bound in rule and (type(rule[bound]) is not int or rule[bound] < 0):
                    bad(loc, f"{bound} must be a nonnegative integer")
            if type(rule.get("min")) is int and type(rule.get("max")) is int:
                if rule["min"] > rule["max"]:
                    bad(loc, "min exceeds max")
    return errors


def h2_sections(body: str) -> dict[str, list[str]]:
    """ATX H2 bodies, excluding HTML comments and headings inside fenced code."""
    result: dict[str, list[list[str]]] = {}
    current: list[str] | None = None
    fence: str | None = None
    comment = False
    for raw in body.splitlines():
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", raw):
                fence = None
            elif current is not None:
                current.append(raw)
            continue
        visible = ""
        rest = raw
        while rest:
            marker = "-->" if comment else "<!--"
            pos = rest.find(marker)
            if pos < 0:
                if not comment:
                    visible += rest
                break
            if not comment:
                visible += rest[:pos]
            rest = rest[pos + len(marker):]
            comment = not comment
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", visible)
        if opening and not (opening[1][0] == "`" and "`" in opening[2]):
            fence = opening[1]
            continue
        heading = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)", visible)
        if heading:
            level = len(heading[1])
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2] or "").strip()
            if level <= 2:
                current = None
            if level == 2:
                current = []
                result.setdefault(title, []).append(current)
            continue
        if current is not None:
            current.append(visible)
    return {title: ["\n".join(lines) for lines in bodies] for title, bodies in result.items()}


def _date(value: str) -> date | None:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def page_rule_errors(
    root: Path, meta: dict, body: str, block: dict, staging_dir: str = "staging",
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    sections = block.get("sections", {})
    if sections.get("enforce") is True:
        found = h2_sections(body)
        for name in sections["required"]:
            bodies = found.get(name, [])
            if not bodies:
                errors.append(("required_sections", f"missing required H2 '{name}'"))
            elif len(bodies) != 1:
                errors.append(("required_sections", f"duplicate required H2 '{name}'"))
            elif sections.get("require_content") and not bodies[0].strip():
                errors.append(("required_sections", f"required H2 '{name}' has no content"))
    fm = block.get("frontmatter", {})
    dates: dict[str, date] = {}
    for key, rule in fm.get("fields", {}).items():
        if key not in meta:
            continue
        value = meta[key]
        kind = rule["type"]
        valid = isinstance(value, str) and bool(value.strip())
        number = None
        if valid:
            if kind == "date":
                if value in rule.get("unknown", []):
                    continue
                parsed = _date(value)
                valid = parsed is not None
                if parsed is not None:
                    dates[key] = parsed
            elif kind in ("integer", "number"):
                pattern = r"[+-]?[0-9]+" if kind == "integer" else r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
                valid = re.fullmatch(pattern, value) is not None
                if valid:
                    try:
                        number = Decimal(value)
                        valid = number.is_finite()
                    except InvalidOperation:
                        valid = False
            elif kind == "boolean":
                valid = value in ("true", "false")
            elif "enum" in rule:
                valid = value in rule["enum"]
        if not valid:
            errors.append(("field_contract", f"field '{key}' must satisfy {kind} rule"))
        elif number is not None:
            for bound, comparison in (("minimum", lambda a, b: a < b), ("maximum", lambda a, b: a > b)):
                if bound in rule and comparison(number, Decimal(str(rule[bound]))):
                    errors.append(("field_contract", f"field '{key}' violates {bound} {rule[bound]}"))
    for rule in fm.get("date_order", []):
        before, after = dates.get(rule["before"]), dates.get(rule["after"])
        if before is not None and after is not None:
            if before > after or (before == after and not rule.get("allow_equal", True)):
                errors.append(("date_order", f"'{rule['before']}' must precede '{rule['after']}'"))
    rules = block.get("relates_to", [])
    if rules:
        rels = meta.get("relates_to", [])
        if not isinstance(rels, list):
            errors.append(("typed_relates_to", "relates_to must be a list of {path, kind} objects"))
            rels = []
        if any(not isinstance(item, dict) or not isinstance(item.get("kind"), str) or not item["kind"].strip() for item in rels):
            errors.append(("typed_relates_to", "each relates_to entry must have an explicit kind"))
        for rule in rules:
            matches = [item for item in rels if isinstance(item, dict) and item.get("kind") == rule["kind"]]
            targets: set[Path] = set()
            for item in matches:
                raw = item.get("path")
                if not isinstance(raw, str) or not raw.strip() or "\\" in raw or ":" in raw or Path(raw).is_absolute():
                    errors.append(("typed_relates_to", f"kind {rule['kind']} requires a local page path"))
                    continue
                target = (root / raw).resolve()
                try:
                    target.relative_to(root.resolve())
                except ValueError:
                    errors.append(("typed_relates_to", f"kind {rule['kind']} target escapes store"))
                    continue
                parts = target.relative_to(root.resolve()).parts
                if (
                    not target.is_file() or target.suffix != ".md" or target.name in RESERVED
                    or parts[0] in SKIP_DIRS
                    or target.is_relative_to((root / staging_dir).resolve())
                ):
                    errors.append(("typed_relates_to", f"kind {rule['kind']} target is not a local concept page"))
                    continue
                if target in targets:
                    errors.append(("typed_relates_to", f"kind {rule['kind']} has a duplicate target"))
                targets.add(target)
                target_meta, _ = read_page(target)
                if target_meta.get("type") not in rule["target_types"]:
                    errors.append(("typed_relates_to", f"kind {rule['kind']} target type must be one of {rule['target_types']}"))
            count = len(targets)
            if "min" in rule and count < rule["min"]:
                errors.append(("typed_relates_to", f"kind {rule['kind']} requires at least {rule['min']} distinct targets"))
            if "max" in rule and count > rule["max"]:
                errors.append(("typed_relates_to", f"kind {rule['kind']} allows at most {rule['max']} distinct targets"))
    return errors
