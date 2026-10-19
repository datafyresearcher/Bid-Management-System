"""Strict validation for LLM JSON outputs.

The LLM is asked to return JSON. Anything it returns is untrusted: it may be
malformed, truncated, contain the wrong types, or (in the worst case) contain
text influenced by a prompt-injection attempt carried in a tender document.

Every structured task validates against these schemas before the result is
allowed anywhere near the database. A payload that fails validation is
discarded and the deterministic fallback is used instead.
"""

from dataclasses import dataclass, field

CATEGORIES = {"form", "qualification", "commercial", "technical", "compliance", "deadline"}
SEVERITIES = {"High", "Medium", "Low"}


@dataclass
class ValidationResult:
    valid: bool
    payload: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def error_text(self) -> str:
        return "; ".join(self.errors)[:300]


def _clean_text(value, limit=300) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # Strip control characters that can corrupt downstream rendering.
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text[:limit]


def validate_requirements(payload) -> ValidationResult:
    """Validate the EXTRACT task payload: {requirements: [{category, text, anchor, mandatory}]}."""
    errors = []
    if not isinstance(payload, dict):
        return ValidationResult(False, {}, ["payload is not an object"])

    items = payload.get("requirements")
    if not isinstance(items, list):
        return ValidationResult(False, {}, ["'requirements' missing or not a list"])

    clean = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {index} is not an object")
            continue
        text = _clean_text(item.get("text"))
        if not text:
            errors.append(f"item {index} has no text")
            continue
        category = _clean_text(item.get("category"), 40).lower()
        if category not in CATEGORIES:
            category = "compliance"
        anchor = _clean_text(item.get("anchor"), 120)
        mandatory = item.get("mandatory", True)
        if not isinstance(mandatory, bool):
            mandatory = str(mandatory).lower() in ("true", "yes", "1", "mandatory")
        clean.append(
            {
                "category": category,
                "text": text,
                "anchor": anchor,
                "mandatory": mandatory,
            }
        )

    if not clean and not errors:
        errors.append("no usable requirements in payload")
    if errors and not clean:
        return ValidationResult(False, {}, errors)
    return ValidationResult(True, {"requirements": clean}, errors)


def validate_risk_flags(payload) -> ValidationResult:
    """Validate the RISK task payload: {flags: [{severity, category, title, detail, suggested_action}]}."""
    errors = []
    if not isinstance(payload, dict):
        return ValidationResult(False, {}, ["payload is not an object"])

    items = payload.get("flags")
    if not isinstance(items, list):
        return ValidationResult(False, {}, ["'flags' missing or not a list"])

    clean = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {index} is not an object")
            continue
        title = _clean_text(item.get("title"), 200)
        if not title:
            errors.append(f"item {index} has no title")
            continue
        severity = _clean_text(item.get("severity"), 20).title()
        if severity not in SEVERITIES:
            severity = "Medium"
        clean.append(
            {
                "severity": severity,
                "category": _clean_text(item.get("category"), 80) or "General",
                "title": title,
                "detail": _clean_text(item.get("detail"), 600),
                "anchor": _clean_text(item.get("anchor"), 120) or "llm",
                "suggested_action": _clean_text(item.get("suggested_action"), 300),
            }
        )

    if not clean and not errors:
        errors.append("no usable flags in payload")
    if errors and not clean:
        return ValidationResult(False, {}, errors)
    return ValidationResult(True, {"flags": clean}, errors)
