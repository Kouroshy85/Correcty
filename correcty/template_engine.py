"""Plain-text template engine.

Templates are made of:
  * a main message (``body``),
  * optional sections: a question whose chosen answer adds its own paragraph on the next line
    (an unanswered question adds nothing),
  * an optional closing text.

Any of those texts may contain ``{{variable}}`` placeholders. Text is never
evaluated as code: it is split into literal text and placeholder tokens, and
values are inserted verbatim (they are never parsed again).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

TOKEN_RE = re.compile(r"\{\{([^{}\n]*)\}\}")
NAME_RE = re.compile(r"[^\W\d]\w*")  # a letter or "_" first, then letters/digits/"_"
MAX_NAME_LEN = 40
VAR_TYPES = ("text", "number", "multiline")
VALUE_LIMITS = {"text": 500, "number": 40, "multiline": 4000}
# Digits (any script, e.g. Persian), optionally grouped by spaces/hyphens, optional decimals.
NUMBER_RE = re.compile(r"[+-]?\d+(?:[ \-]\d+)*(?:[.,٫]\d+)?")
PART_SEPARATOR = "\n"  # each added paragraph starts on the next line

_SENTINEL_OPEN, _SENTINEL_CLOSE = "", ""
_SENTINEL_RE = re.compile(f"{_SENTINEL_OPEN}([^{_SENTINEL_CLOSE}]*){_SENTINEL_CLOSE}")
_SNIPPET_LEN = 28

LabelFor = Callable[[str], str]


@dataclass(frozen=True)
class Token:
    kind: str  # "text" or "var"
    value: str


# --------------------------------------------------------------------------- parsing


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_valid_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and 0 < len(name) <= MAX_NAME_LEN
        and NAME_RE.fullmatch(name) is not None
    )


def _clip(text: str) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= _SNIPPET_LEN else text[:_SNIPPET_LEN] + "…"


def _literal(chunk: str, tokens: list[Token], issues: list[dict]) -> None:
    if not chunk:
        return
    opening = chunk.find("{{")
    closing = chunk.find("}}")
    if opening != -1:
        issues.append({"code": "var_unclosed", "snippet": _clip(chunk[opening:])})
    elif closing != -1:
        start = max(0, closing - _SNIPPET_LEN + 2)
        issues.append({"code": "var_stray", "snippet": _clip(chunk[start : closing + 2])})
    tokens.append(Token("text", chunk))


def parse(text: str) -> tuple[list[Token], list[dict]]:
    """Split text into tokens and report malformed placeholders.

    Returns ``(tokens, issues)``; each issue is ``{"code", "snippet"}``.
    """
    tokens: list[Token] = []
    issues: list[dict] = []
    pos = 0
    for match in TOKEN_RE.finditer(text):
        _literal(text[pos : match.start()], tokens, issues)
        raw = match.group(0)
        name = match.group(1).strip()
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if is_valid_name(name) and before != "{" and after != "}":
            tokens.append(Token("var", name))
        else:
            snippet = (before if before == "{" else "") + raw + (after if after == "}" else "")
            issues.append({"code": "var_malformed", "snippet": _clip(snippet)})
            tokens.append(Token("text", raw))
        pos = match.end()
    _literal(text[pos:], tokens, issues)
    return tokens, issues


def var_names(tokens: Iterable[Token]) -> list[str]:
    """Unique variable names in order of first appearance."""
    seen: list[str] = []
    for token in tokens:
        if token.kind == "var" and token.value not in seen:
            seen.append(token.value)
    return seen


def names_in(text: str) -> list[str]:
    return var_names(parse(text)[0])


def default_variable(name: str) -> dict:
    return {"name": name, "label": "", "type": "text", "required": True, "placeholder": ""}


def template_issues(template: dict) -> list[dict]:
    """Placeholder problems anywhere in a stored template (should normally be empty)."""
    issues: list[dict] = []
    for text in _all_texts(template):
        issues.extend(parse(text)[1])
    return issues


def _all_texts(template: dict) -> list[str]:
    texts = [template.get("body", "")]
    for section in template.get("sections", []):
        texts.extend(choice.get("text", "") for choice in section.get("choices", []))
    texts.append(template.get("closing", ""))
    return texts


# --------------------------------------------------------------------------- form


def _field(definition: dict | None, name: str, label_for: LabelFor) -> dict:
    d = definition or default_variable(name)
    return {
        "name": name,
        "label": d.get("label") or label_for(name),
        "type": d.get("type", "text"),
        "required": bool(d.get("required", True)),
        "placeholder": d.get("placeholder", ""),
    }


def build_form(template: dict, label_for: LabelFor) -> dict:
    """Describe the inputs an agent fills in, in the order they appear in the message.

    ``layout`` lists main-message inputs, then each optional section with the
    inputs its answers introduce, then closing-text inputs. ``always`` holds the
    inputs that are needed no matter which answers are chosen; ``choice_vars``
    maps section id -> choice id -> inputs that answer needs.
    """
    definitions = {v["name"]: v for v in template.get("variables", [])}
    body_vars = names_in(template.get("body", ""))
    closing_vars = names_in(template.get("closing", ""))

    seen: list[str] = list(body_vars)
    layout: list[dict] = [{"kind": "var", "name": n} for n in body_vars]
    sections: list[dict] = []
    choice_vars: dict[str, dict[str, list[str]]] = {}

    for section in template.get("sections", []):
        introduced: list[str] = []
        per_choice: dict[str, list[str]] = {}
        for choice in section["choices"]:
            names = names_in(choice.get("text", ""))
            per_choice[choice["id"]] = names
            for n in names:
                if n not in seen:
                    seen.append(n)
                    introduced.append(n)
        choice_vars[section["id"]] = per_choice
        layout.append({"kind": "section", "id": section["id"], "vars": introduced})
        sections.append(
            {
                "id": section["id"],
                "question": section["question"],
                "choices": [{"id": c["id"], "label": c["label"]} for c in section["choices"]],
            }
        )

    for n in closing_vars:
        if n not in seen:
            seen.append(n)
            layout.append({"kind": "var", "name": n})

    always: list[str] = []
    for n in body_vars + closing_vars:
        if n not in always:
            always.append(n)

    return {
        "layout": layout,
        "fields": {n: _field(definitions.get(n), n, label_for) for n in seen},
        "always": always,
        "choice_vars": choice_vars,
        "sections": sections,
    }


# --------------------------------------------------------------------------- rendering


def clean_value(raw: object, var_type: str, required: bool) -> tuple[str, dict | None]:
    """Normalize one entered value. Returns ``(value, error_or_None)``."""
    if raw is None:
        raw = ""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return "", {"code": "value_invalid", "params": {}}
    value = normalize_newlines(str(raw))
    if var_type != "multiline":
        value = " ".join(value.split("\n"))
    value = value.strip()

    limit = VALUE_LIMITS.get(var_type, VALUE_LIMITS["text"])
    if not value:
        return "", ({"code": "value_required", "params": {}} if required else None)
    if len(value) > limit:
        return value, {"code": "value_too_long", "params": {"max": limit}}
    if "{{" in value or "}}" in value:
        return value, {"code": "value_braces", "params": {}}
    if var_type == "number" and not NUMBER_RE.fullmatch(value):
        return value, {"code": "value_number", "params": {}}
    return value, None


def _assemble(parts: list[list[Token]], resolve: Callable[[str], str]) -> str:
    pieces: list[str] = []
    for tokens in parts:
        text = "".join(t.value if t.kind == "text" else resolve(t.value) for t in tokens)
        text = "\n".join(line.rstrip() for line in normalize_newlines(text).split("\n")).strip()
        if text:
            pieces.append(text)
    return re.sub(r"\n{3,}", "\n\n", PART_SEPARATOR.join(pieces))


def render(
    template: dict,
    choices: object = None,
    values: object = None,
    label_for: LabelFor = lambda name: name,
) -> dict:
    """Build the final message for the chosen answers and entered values.

    ``choices`` maps section id -> chosen answer id; sections without an answer are skipped.

    Returns ``{"ok", "text", "segments", "errors", "needed"}``. ``text`` is only
    set when everything required is filled in correctly, so callers can never
    copy a message with missing or unresolved placeholders. ``segments`` is a
    preview of the message where each placeholder is a separate item.
    """
    choices = choices if isinstance(choices, dict) else {}
    values = values if isinstance(values, dict) else {}
    errors: list[dict] = []

    if template_issues(template):
        errors.append({"field": "_template", "code": "template_broken", "params": {}})

    parts: list[list[Token]] = [parse(template.get("body", ""))[0]]
    for section in template.get("sections", []):
        wanted = choices.get(section["id"])
        if wanted in (None, ""):
            continue  # unanswered: the section adds nothing
        choice = next((c for c in section["choices"] if c["id"] == wanted), None)
        if choice is None:
            errors.append({"field": f"section:{section['id']}", "code": "choice_invalid", "params": {}})
            continue
        parts.append(parse(choice.get("text", ""))[0])
    parts.append(parse(template.get("closing", ""))[0])

    definitions = {v["name"]: v for v in template.get("variables", [])}
    needed = var_names(token for tokens in parts for token in tokens)
    resolved: dict[str, str] = {}
    invalid: set[str] = set()
    for name in needed:
        d = definitions.get(name) or default_variable(name)
        value, error = clean_value(values.get(name), d.get("type", "text"), bool(d.get("required", True)))
        resolved[name] = value
        if error:
            invalid.add(name)
            errors.append({"field": f"var:{name}", **error})

    text = None if errors else _assemble(parts, lambda n: resolved[n])

    marked = _assemble(parts, lambda n: f"{_SENTINEL_OPEN}{n}{_SENTINEL_CLOSE}")
    segments: list[dict] = []
    for i, piece in enumerate(_SENTINEL_RE.split(marked)):
        if i % 2 == 0:
            if piece:
                segments.append({"t": "text", "v": piece})
            continue
        d = definitions.get(piece) or default_variable(piece)
        segments.append(
            {
                "t": "var",
                "name": piece,
                "v": resolved.get(piece, ""),
                "filled": bool(resolved.get(piece)),
                "required": bool(d.get("required", True)),
                "invalid": piece in invalid,
                "label": d.get("label") or label_for(piece),
            }
        )

    return {"ok": not errors, "text": text, "segments": segments, "errors": errors, "needed": needed}


# --------------------------------------------------------------------------- search helpers

_SEARCH_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "‌": " "})


def normalize_search(text: str) -> str:
    """Case-fold and unify Arabic/Persian letter variants so search is forgiving."""
    return " ".join(text.translate(_SEARCH_FOLD).casefold().split())


def search_blob(template: dict) -> str:
    pieces = [template.get("title", ""), template.get("description", "")]
    pieces.extend(_all_texts(template))
    for section in template.get("sections", []):
        pieces.append(section.get("question", ""))
        pieces.extend(c.get("label", "") for c in section.get("choices", []))
    return normalize_search(" ".join(pieces))


def matches(template: dict, query: str) -> bool:
    q = normalize_search(query)
    return not q or q in search_blob(template)
