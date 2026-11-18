"""Server-side validation and normalization of template payloads.

``validate_template`` never trusts the client: it checks every field, detects
the variables actually used in the text, and returns a clean template dict plus
a list of field errors (``{"field", "code", "params"}``).
"""
from __future__ import annotations

import re

from . import template_engine as engine

LIMITS = {
    "title": 120,
    "description": 300,
    "body": 10000,
    "closing": 5000,
    "question": 200,
    "choice_label": 80,
    "choice_text": 5000,
    "var_label": 80,
    "var_placeholder": 120,
    "sections": 10,
    "choices_min": 2,
    "choices_max": 8,
    "variables": 30,
    "prompt_name": 80,
    "prompt_text": 4000,
}
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


class Errors(list):
    def add(self, field: str, code: str, **params) -> None:
        self.append({"field": field, "code": code, "params": params})

    def has(self, field: str) -> bool:
        return any(e["field"] == field for e in self)


def _text(value, field: str, errors: Errors, *, max_len: int, required_code: str | None = None,
          single_line: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors.add(field, "invalid_type")
        return ""
    value = engine.normalize_newlines(value)
    if single_line:
        value = " ".join(value.split("\n"))
    value = value.strip()
    if required_code and not value:
        errors.add(field, required_code)
    elif len(value) > max_len:
        errors.add(field, "too_long", max=max_len)
    return value


def _bool(value, field: str, errors: Errors, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    errors.add(field, "invalid_type")
    return default


def _ident(value, used: set[str], prefix: str, field: str, errors: Errors) -> str:
    if value in (None, ""):
        n = len(used) + 1
        while f"{prefix}{n}" in used:
            n += 1
        value = f"{prefix}{n}"
    elif not isinstance(value, str) or not _ID_RE.fullmatch(value) or value in used:
        errors.add(field, "id_invalid")
        value = f"{prefix}x{len(used) + 1}"
    used.add(value)
    return value


def _sections(raw, errors: Errors) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.add("sections", "invalid_type")
        return []
    if len(raw) > LIMITS["sections"]:
        errors.add("sections", "sections_max", max=LIMITS["sections"])
        raw = raw[: LIMITS["sections"]]

    section_ids: set[str] = set()
    out: list[dict] = []
    for i, section in enumerate(raw):
        base = f"sections.{i}"
        if not isinstance(section, dict):
            errors.add(base, "invalid_type")
            continue
        sid = _ident(section.get("id"), section_ids, "s", f"{base}.id", errors)
        question = _text(section.get("question"), f"{base}.question", errors,
                         max_len=LIMITS["question"], required_code="question_required", single_line=True)

        raw_choices = section.get("choices")
        if not isinstance(raw_choices, list):
            errors.add(f"{base}.choices", "invalid_type")
            raw_choices = []
        if len(raw_choices) < LIMITS["choices_min"]:
            errors.add(f"{base}.choices", "choices_min", min=LIMITS["choices_min"])
        elif len(raw_choices) > LIMITS["choices_max"]:
            errors.add(f"{base}.choices", "choices_max", max=LIMITS["choices_max"])
            raw_choices = raw_choices[: LIMITS["choices_max"]]

        choice_ids: set[str] = set()
        labels: set[str] = set()
        choices: list[dict] = []
        for j, choice in enumerate(raw_choices):
            cbase = f"{base}.choices.{j}"
            if not isinstance(choice, dict):
                errors.add(cbase, "invalid_type")
                continue
            cid = _ident(choice.get("id"), choice_ids, "c", f"{cbase}.id", errors)
            label = _text(choice.get("label"), f"{cbase}.label", errors, max_len=LIMITS["choice_label"],
                          required_code="choice_label_required", single_line=True)
            if label:
                key = label.casefold()
                if key in labels:
                    errors.add(f"{cbase}.label", "choice_label_duplicate")
                labels.add(key)
            text = _text(choice.get("text"), f"{cbase}.text", errors, max_len=LIMITS["choice_text"])
            choices.append({"id": cid, "label": label, "text": text})

        out.append({"id": sid, "question": question, "choices": choices})
    return out


def _variable_definitions(raw, errors: Errors) -> dict[str, dict]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        raw = [{"name": k, **v} if isinstance(v, dict) else v for k, v in raw.items()]
    if not isinstance(raw, list):
        errors.add("variables", "invalid_type")
        return {}

    out: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            errors.add("variables", "invalid_type")
            continue
        name = item.get("name")
        if not engine.is_valid_name(name):
            errors.add("variables", "var_def_invalid", name=str(name)[:40])
            continue
        if name in out:
            errors.add("variables", "var_def_duplicate", name=name)
            continue
        base = f"variables.{name}"
        var_type = item.get("type") or "text"
        if var_type not in engine.VAR_TYPES:
            errors.add(f"{base}.type", "var_type_invalid")
            var_type = "text"
        out[name] = {
            "name": name,
            "label": _text(item.get("label"), f"{base}.label", errors,
                           max_len=LIMITS["var_label"], single_line=True),
            "type": var_type,
            "required": _bool(item.get("required"), f"{base}.required", errors, default=True),
            "placeholder": _text(item.get("placeholder"), f"{base}.placeholder", errors,
                                 max_len=LIMITS["var_placeholder"], single_line=True),
        }
    return out


def validate_prompt(payload) -> tuple[dict | None, Errors]:
    """A saved Polish Text prompt: a short name and the instructions for the AI."""
    errors = Errors()
    if not isinstance(payload, dict):
        errors.add("_", "bad_request")
        return None, errors
    name = _text(payload.get("name"), "name", errors, max_len=LIMITS["prompt_name"],
                 required_code="prompt_name_required", single_line=True)
    prompt = _text(payload.get("prompt"), "prompt", errors, max_len=LIMITS["prompt_text"],
                   required_code="prompt_text_required")
    active = _bool(payload.get("active"), "active", errors, default=False)
    return {"name": name, "prompt": prompt, "active": active}, errors


def validate_template(payload) -> tuple[dict | None, Errors]:
    errors = Errors()
    if not isinstance(payload, dict):
        errors.add("_", "bad_request")
        return None, errors

    title = _text(payload.get("title"), "title", errors, max_len=LIMITS["title"],
                  required_code="title_required", single_line=True)
    description = _text(payload.get("description"), "description", errors,
                        max_len=LIMITS["description"], single_line=True)
    body = _text(payload.get("body"), "body", errors, max_len=LIMITS["body"], required_code="body_required")
    closing = _text(payload.get("closing"), "closing", errors, max_len=LIMITS["closing"])
    pinned = _bool(payload.get("pinned"), "pinned", errors, default=False)
    sections = _sections(payload.get("sections"), errors)

    texts = [("body", body)]
    for i, section in enumerate(sections):
        for j, choice in enumerate(section["choices"]):
            texts.append((f"sections.{i}.choices.{j}.text", choice["text"]))
    texts.append(("closing", closing))

    names: list[str] = []
    for field, text in texts:
        tokens, issues = engine.parse(text)
        for issue in issues:
            errors.add(field, issue["code"], snippet=issue["snippet"])
        for name in engine.var_names(tokens):
            if name not in names:
                names.append(name)

    spelling: dict[str, str] = {}
    for name in names:
        key = name.casefold()
        if key in spelling and spelling[key] != name:
            errors.add("variables", "var_case_conflict", a=spelling[key], b=name)
        spelling.setdefault(key, name)
    if len(names) > LIMITS["variables"]:
        errors.add("variables", "vars_max", max=LIMITS["variables"])

    definitions = _variable_definitions(payload.get("variables"), errors)
    variables = [definitions.get(n) or engine.default_variable(n) for n in names]

    clean = {
        "title": title,
        "description": description,
        "body": body,
        "closing": closing,
        "pinned": pinned,
        "sections": sections,
        "variables": variables,
    }
    return clean, errors
