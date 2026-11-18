"""Pages and JSON API."""
from __future__ import annotations

import logging
from functools import partial
from urllib.parse import urlsplit

from flask import (
    Blueprint, Flask, current_app, jsonify, redirect, render_template, request, url_for,
)
from markupsafe import Markup, escape
from werkzeug.exceptions import HTTPException

from . import __version__
from . import database as db
from . import i18n
from . import polish as polisher
from . import template_engine as engine
from .validators import validate_prompt, validate_template

log = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

LANG_COOKIE = "correcty_lang"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
HTTP_ERROR_CODES = {
    400: "bad_request", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
    413: "too_large", 415: "unsupported_media",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, fields: list[dict] | None = None, params: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.fields, self.params = status, code, fields or [], params or {}


# --------------------------------------------------------------------------- helpers


def current_lang() -> str:
    return i18n.normalize_language(request.cookies.get(LANG_COOKIE))


def label_for(lang: str):
    return partial(i18n.auto_label, lang=lang)


def _localized_errors(errors: list[dict], lang: str) -> list[dict]:
    return [
        {"field": e["field"], "code": e["code"], "message": i18n.error_message(e["code"], e.get("params"), lang)}
        for e in errors
    ]


def api_error_response(status: int, code: str, fields: list[dict] | None = None, params: dict | None = None):
    lang = current_lang()
    body = {"error": {"code": code, "message": i18n.error_message(code, params, lang)}}
    if fields:
        body["error"]["fields"] = _localized_errors(fields, lang)
    return jsonify(body), status


def _json_body() -> dict:
    if not request.is_json:
        raise ApiError(415, "unsupported_media")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "bad_json")
    return data


def _get_or_404(template_id: int) -> dict:
    tpl = db.get_template(db.get_db(), template_id)
    if tpl is None:
        raise ApiError(404, "not_found")
    return tpl


def summary(tpl: dict) -> dict:
    return {
        "id": tpl["id"],
        "title": tpl["title"],
        "description": tpl["description"],
        "pinned": tpl["pinned"],
        "preview": " ".join(tpl["body"].split())[:180],
        "inputs": len(tpl["variables"]),
        "sections": len(tpl["sections"]),
        "search": engine.search_blob(tpl),
        "updated_at": tpl["updated_at"],
    }


def full(tpl: dict, lang: str) -> dict:
    return {"template": tpl, "form": engine.build_form(tpl, label_for(lang))}


def _render_result(tpl: dict, data: dict, lang: str) -> dict:
    result = engine.render(tpl, data.get("choices"), data.get("values"), label_for(lang))
    result["errors"] = _localized_errors(result["errors"], lang)
    return result


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _safe_next(target: str | None) -> str:
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("main.quick_reply")
    return target


# --------------------------------------------------------------------------- request guards


@bp.before_app_request
def guard_request():
    """Only serve this machine, and block cross-site writes (CSRF / DNS rebinding)."""
    is_api = request.path.startswith("/api/")
    if _hostname(request.host) not in current_app.config["ALLOWED_HOSTS"]:
        return api_error_response(403, "forbidden") if is_api else ("Forbidden", 403)
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("Origin")
        if origin is not None and origin.rstrip("/") != request.host_url.rstrip("/"):
            return api_error_response(403, "forbidden") if is_api else ("Forbidden", 403)
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return api_error_response(403, "forbidden") if is_api else ("Forbidden", 403)
        if is_api and request.method != "DELETE" and not request.is_json:
            return api_error_response(415, "unsupported_media")
    return None


@bp.after_app_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", CSP)
    # Pages and API answers are never cached; static files are revalidated on every load.
    response.headers["Cache-Control"] = "no-cache" if request.path.startswith("/static/") else "no-store"
    return response


@bp.app_context_processor
def inject_globals():
    lang = current_lang()

    def asset(path: str) -> str:
        return url_for("static", filename=path)  # the static URL path already carries a version

    def icon(name: str, cls: str = "") -> Markup:
        classes = f"icon {cls}".strip()
        return Markup(
            f'<svg class="{escape(classes)}" aria-hidden="true" focusable="false">'
            f'<use href="#i-{escape(name)}"></use></svg>'
        )

    return {
        "lang": lang,
        "dir": i18n.direction(lang),
        "t": lambda key, **params: i18n.translate(key, lang, **params),
        "tn": lambda base, n, **params: i18n.plural(base, n, lang, **params),
        "i18n_client": i18n.client_payload(lang),
        "asset": asset,
        "icon": icon,
        "next_url": request.full_path.rstrip("?"),
        "app_version": __version__,
    }


# --------------------------------------------------------------------------- pages


@bp.get("/")
def quick_reply():
    conn = db.get_db()
    pinned = [summary(t) for t in db.list_templates(conn, pinned_only=True)]
    return render_template("index.html", page="quick", script="quick-reply.js", pinned=pinned,
                           active_prompt=db.active_prompt(conn))


@bp.get("/settings")
def settings_page():
    conn = db.get_db()
    tab = request.args.get("tab") if request.args.get("tab") in ("prompts", "ai") else "prompts"
    return render_template("settings.html", page="settings", script="settings.js", tab=tab,
                           prompts=db.list_prompts(conn), ai=_ai_settings(conn))


@bp.get("/templates")
def manage_templates():
    templates = [summary(t) for t in db.list_templates(db.get_db())]
    return render_template("manage_templates.html", page="manage", script="templates.js", templates=templates)


@bp.get("/templates/new")
def new_template():
    blank = {"id": None, "title": "", "description": "", "body": "", "closing": "", "pinned": False,
             "sections": [], "variables": []}
    return render_template("edit_template.html", page="editor", script="editor.js", template=blank, is_new=True)


@bp.get("/templates/<int:template_id>/edit")
def edit_template(template_id: int):
    tpl = db.get_template(db.get_db(), template_id)
    if tpl is None:
        return render_template("error.html", page="error", script="app.js"), 404
    return render_template("edit_template.html", page="editor", script="editor.js", template=tpl, is_new=False)


@bp.get("/lang/<code>")
def set_language(code: str):
    response = redirect(_safe_next(request.args.get("next")))
    response.set_cookie(LANG_COOKIE, i18n.normalize_language(code), max_age=60 * 60 * 24 * 365,
                        samesite="Lax", httponly=True)
    return response


@bp.get("/healthz")
def healthz():
    return jsonify({"app": "correcty", "version": __version__, "ok": True})


# --------------------------------------------------------------------------- API


@bp.get("/api/templates")
def api_list():
    pinned_only = request.args.get("pinned") in ("1", "true")
    query = request.args.get("q", "")
    items = [t for t in db.list_templates(db.get_db(), pinned_only) if engine.matches(t, query)]
    return jsonify({"templates": [summary(t) for t in items]})


@bp.post("/api/templates")
def api_create():
    clean, errors = validate_template(_json_body())
    if errors:
        raise ApiError(422, "validation", errors)
    conn = db.get_db()
    new_id = db.create_template(conn, clean)
    return jsonify(full(db.get_template(conn, new_id), current_lang())), 201


@bp.get("/api/templates/<int:template_id>")
def api_get(template_id: int):
    return jsonify(full(_get_or_404(template_id), current_lang()))


@bp.put("/api/templates/<int:template_id>")
def api_update(template_id: int):
    data = _json_body()
    _get_or_404(template_id)
    clean, errors = validate_template(data)
    if errors:
        raise ApiError(422, "validation", errors)
    conn = db.get_db()
    if not db.update_template(conn, template_id, clean):
        raise ApiError(404, "not_found")
    return jsonify(full(db.get_template(conn, template_id), current_lang()))


@bp.patch("/api/templates/<int:template_id>/pin")
def api_pin(template_id: int):
    pinned = _json_body().get("pinned")
    if not isinstance(pinned, bool):
        raise ApiError(400, "bad_request", [{"field": "pinned", "code": "invalid_type", "params": {}}])
    if not db.set_pinned(db.get_db(), template_id, pinned):
        raise ApiError(404, "not_found")
    return jsonify({"id": template_id, "pinned": pinned})


@bp.delete("/api/templates/<int:template_id>")
def api_delete(template_id: int):
    if not db.delete_template(db.get_db(), template_id):
        raise ApiError(404, "not_found")
    return "", 204


@bp.post("/api/templates/<int:template_id>/render")
def api_render(template_id: int):
    data = _json_body()
    return jsonify(_render_result(_get_or_404(template_id), data, current_lang()))


@bp.post("/api/preview")
def api_preview():
    """Validate an unsaved template from the editor and render it for the preview dialog."""
    data = _json_body()
    clean, errors = validate_template(data.get("template"))
    if errors:
        raise ApiError(422, "validation", errors)
    lang = current_lang()
    clean["id"] = None
    return jsonify({**full(clean, lang), "result": _render_result(clean, data, lang)})


# --------------------------------------------------------------------------- Polish Text (local AI)

POLISH_ERROR_STATUS = {
    "polish_empty": 400, "polish_too_long": 400, "ollama_unavailable": 503,
    "model_missing": 503, "ollama_timeout": 504, "ollama_failed": 502, "model_thinks": 502,
}


def _ai_settings(conn) -> dict:
    return db.get_settings(conn, polisher.DEFAULTS)


def _get_prompt_or_404(prompt_id: int) -> dict:
    prompt = db.get_prompt(db.get_db(), prompt_id)
    if prompt is None:
        raise ApiError(404, "prompt_not_found")
    return prompt


@bp.get("/api/prompts")
def api_prompts():
    return jsonify({"prompts": db.list_prompts(db.get_db())})


@bp.post("/api/prompts")
def api_prompt_create():
    clean, errors = validate_prompt(_json_body())
    if errors:
        raise ApiError(422, "validation", errors)
    conn = db.get_db()
    new_id = db.create_prompt(conn, clean["name"], clean["prompt"], clean["active"])
    return jsonify({"prompt": db.get_prompt(conn, new_id)}), 201


@bp.put("/api/prompts/<int:prompt_id>")
def api_prompt_update(prompt_id: int):
    data = _json_body()
    _get_prompt_or_404(prompt_id)
    clean, errors = validate_prompt(data)
    if errors:
        raise ApiError(422, "validation", errors)
    conn = db.get_db()
    db.update_prompt(conn, prompt_id, clean["name"], clean["prompt"])
    return jsonify({"prompt": db.get_prompt(conn, prompt_id)})


@bp.post("/api/prompts/<int:prompt_id>/activate")
def api_prompt_activate(prompt_id: int):
    conn = db.get_db()
    if not db.activate_prompt(conn, prompt_id):
        raise ApiError(404, "prompt_not_found")
    return jsonify({"prompts": db.list_prompts(conn)})


@bp.delete("/api/prompts/<int:prompt_id>")
def api_prompt_delete(prompt_id: int):
    if not db.delete_prompt(db.get_db(), prompt_id):
        raise ApiError(404, "prompt_not_found")
    return "", 204


@bp.get("/api/ai/status")
def api_ai_status():
    return jsonify(polisher.status(_ai_settings(db.get_db())))


@bp.put("/api/ai/settings")
def api_ai_settings():
    data = _json_body()
    url = polisher.validate_url(data.get("ollama_url"))
    model = polisher.validate_model(data.get("model"))
    fields = []
    if url is None:
        fields.append({"field": "ollama_url", "code": "url_not_local", "params": {}})
    if model is None:
        fields.append({"field": "model", "code": "model_invalid", "params": {}})
    if fields:
        raise ApiError(422, "validation", fields)
    conn = db.get_db()
    db.save_settings(conn, {"ollama_url": url, "model": model})
    return jsonify(polisher.status(_ai_settings(conn)))


@bp.post("/api/polish")
def api_polish():
    text = _json_body().get("text")
    if not isinstance(text, str):
        raise ApiError(400, "bad_request")
    conn = db.get_db()
    prompt = db.active_prompt(conn) or {"name": db.DEFAULT_PROMPT["name"], "prompt": db.DEFAULT_PROMPT["prompt"]}
    settings = _ai_settings(conn)
    try:
        polished = polisher.polish(text, prompt["prompt"], settings)
    except polisher.PolishError as exc:
        params = {**exc.params, "model": settings["model"]}
        raise ApiError(POLISH_ERROR_STATUS.get(exc.code, 502), exc.code, params=params) from exc
    return jsonify({"text": polished, "prompt": prompt["name"], "model": settings["model"]})


# --------------------------------------------------------------------------- errors


def _handle_api_error(error: ApiError):
    return api_error_response(error.status, error.code, error.fields, error.params)


def _handle_http_error(error: HTTPException):
    if request.path.startswith("/api/"):
        return api_error_response(error.code or 500, HTTP_ERROR_CODES.get(error.code, "server_error"))
    if error.code == 404:
        return render_template("error.html", page="error", script="app.js"), 404
    return error


def _handle_unexpected(error: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.path)
    if request.path.startswith("/api/"):
        return api_error_response(500, "server_error")
    return render_template("error.html", page="error", script="app.js", server_error=True), 500


def init_app(app: Flask) -> None:
    app.register_blueprint(bp)
    app.register_error_handler(ApiError, _handle_api_error)
    app.register_error_handler(HTTPException, _handle_http_error)
    app.register_error_handler(Exception, _handle_unexpected)
