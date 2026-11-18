"""Polish Text: rewrite a message with a local Ollama model, guided by the active prompt.

Only Ollama on this computer is allowed (localhost addresses), so student text never leaves the machine.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

# qwen3:4b on Ollama is the "thinking" edition (slow, always reasons first); the instruct edition
# is the same size but answers directly, which suits quick polishing.
DEFAULTS = {"ollama_url": "http://127.0.0.1:11434", "model": "qwen3:4b-instruct"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_TEXT = 4000
TIMEOUT = 120  # the first request loads the model into memory, which can take a while

# Always added after the user's prompt, so the reply is usable as-is.
OUTPUT_RULES = (
    "Rules for your reply: return ONLY the polished message, with no explanations, notes, headings or "
    "quotation marks around it. Keep links, email addresses, phone numbers, names, numbers and anything "
    "inside {{ }} exactly as written."
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_PERSIAN_RE = re.compile(r"[؀-ۿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def language_rule(text: str) -> str:
    """Small models drift into translating; tell them the language explicitly."""
    persian = "Persian (Farsi)" if len(_PERSIAN_RE.findall(text)) >= len(_LATIN_RE.findall(text)) else "English"
    return f"The message is written in {persian}. Reply in {persian} only. Never translate it."
_MODEL_RE = re.compile(r"[A-Za-z0-9._:/-]{1,100}")


class PolishError(Exception):
    """Something the agent can act on; ``code`` maps to a translated message."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def validate_url(url: object) -> str | None:
    """Return a cleaned Ollama URL, or None if it isn't an http address on this computer."""
    if not isinstance(url, str):
        return None
    url = url.strip().rstrip("/")
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or (parts.hostname or "") not in LOCAL_HOSTS:
        return None
    if parts.path or parts.query or parts.fragment:
        return None
    return url


def validate_model(model: object) -> str | None:
    if isinstance(model, str) and _MODEL_RE.fullmatch(model.strip()):
        return model.strip()
    return None


def _request(url: str, path: str, payload: dict | None = None, timeout: float = 5) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url + path, data=data, headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001 - best effort only
            pass
        if exc.code == 404 and "not found" in detail.lower():
            raise PolishError("model_missing") from exc
        raise PolishError("ollama_failed", detail=detail or str(exc.code)) from exc
    except TimeoutError as exc:
        raise PolishError("ollama_timeout") from exc
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise PolishError("ollama_timeout") from exc
        raise PolishError("ollama_unavailable") from exc
    except ValueError as exc:
        raise PolishError("ollama_failed", detail="invalid response") from exc


_thinking_cache: dict[tuple[str, str], bool] = {}


def thinking_only(settings: dict) -> bool:
    """True for "thinking" editions whose chat template forces a <think> block before every answer.

    These can't be told to skip reasoning (``think: false`` is ignored), so they are far too slow for
    quick polishing and would return their reasoning instead of the message.
    """
    key = (settings["ollama_url"], settings["model"])
    if key not in _thinking_cache:
        template = _request(settings["ollama_url"], "/api/show", {"model": settings["model"]}, timeout=5).get("template", "")
        _thinking_cache[key] = "assistant\n<think>" in template
    return _thinking_cache[key]


def status(settings: dict) -> dict:
    """Is Ollama running, and is the chosen model installed?"""
    result = {"reachable": False, "version": None, "models": [], "model": settings["model"],
              "model_installed": False, "thinking_only": False, "ollama_url": settings["ollama_url"]}
    try:
        result["version"] = _request(settings["ollama_url"], "/api/version", timeout=3).get("version")
        tags = _request(settings["ollama_url"], "/api/tags", timeout=3)
    except PolishError:
        return result
    result["reachable"] = True
    result["models"] = sorted(m.get("name", "") for m in tags.get("models", []) if m.get("name"))
    wanted = settings["model"]
    result["model_installed"] = any(m == wanted or m == f"{wanted}:latest" for m in result["models"])
    if result["model_installed"]:
        try:
            result["thinking_only"] = thinking_only(settings)
        except PolishError:
            pass
    return result


def polish(text: str, prompt: str, settings: dict) -> str:
    text = text.strip()
    if not text:
        raise PolishError("polish_empty")
    if len(text) > MAX_TEXT:
        raise PolishError("polish_too_long", max=MAX_TEXT)
    if thinking_only(settings):
        raise PolishError("model_thinks", model=settings["model"])
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": f"{prompt.strip()}\n\n{OUTPUT_RULES} {language_rule(text)}"},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "think": False,  # hybrid models: answer directly, no reasoning text
        # Cap the length so a model that rambles (or "thinks" anyway) can't run for minutes.
        "options": {"temperature": 0.3, "num_predict": max(256, len(text) * 2)},
    }
    try:
        reply = _request(settings["ollama_url"], "/api/chat", payload, timeout=TIMEOUT)
    except PolishError as exc:
        if "think" not in str(exc.params.get("detail", "")).lower():
            raise
        payload.pop("think")  # models without a thinking mode reject the option
        reply = _request(settings["ollama_url"], "/api/chat", payload, timeout=TIMEOUT)
    message = reply.get("message") or {}
    content = _THINK_RE.sub("", message.get("content", "")).strip()
    if not content and message.get("thinking"):
        raise PolishError("model_thinks", model=settings["model"])
    if len(content) >= 2 and (content[0], content[-1]) in {('"', '"'), ("'", "'"), ("«", "»"), ("“", "”")}:
        content = content[1:-1].strip()
    if not content:
        raise PolishError("ollama_failed", detail="empty reply")
    return content
