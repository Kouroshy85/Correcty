"""SQLite storage: connection handling, versioned migrations and template CRUD."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import Flask, current_app, g

from .validators import validate_template

log = logging.getLogger(__name__)

COLUMNS = "id, title, description, body, closing, variables, sections, pinned, created_at, updated_at"


# --------------------------------------------------------------------------- connections


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    conn = connect(app.config["DATABASE"])
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn, seed=app.config.get("SEED_EXAMPLES", True))
    finally:
        conn.close()


# --------------------------------------------------------------------------- migrations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migration_1(conn: sqlite3.Connection, seed: bool) -> None:
    conn.execute(
        """
        CREATE TABLE templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            body        TEXT    NOT NULL,
            closing     TEXT    NOT NULL DEFAULT '',
            variables   TEXT    NOT NULL DEFAULT '[]',
            sections    TEXT    NOT NULL DEFAULT '[]',
            pinned      INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_templates_pinned ON templates (pinned)")
    if seed:
        for payload in SEED_TEMPLATES:
            clean, errors = validate_template(payload)
            if errors:  # pragma: no cover - guards against editing the seeds badly
                raise RuntimeError(f"Invalid seed template {payload['title']!r}: {errors}")
            _insert(conn, clean)


DEFAULT_PROMPT = {
    "name": "Friendly & professional",
    "prompt": (
        "You polish short messages for clear, natural communication.\n"
        "Fix spelling, grammar and punctuation. Make the tone friendly, polite and professional, "
        "and keep it short and clear. Keep the same language as the original: Persian stays natural, "
        "everyday Persian with correct half-spaces; English stays English. Don't add new information."
    ),
}


def _migration_2(conn: sqlite3.Connection, seed: bool) -> None:
    """Polish Text: saved prompts (one active) and simple key/value settings."""
    conn.execute(
        """
        CREATE TABLE polish_prompts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            prompt      TEXT    NOT NULL,
            active      INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    now = _now()
    conn.execute(
        "INSERT INTO polish_prompts (name, prompt, active, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
        (DEFAULT_PROMPT["name"], DEFAULT_PROMPT["prompt"], now, now),
    )


# Each entry upgrades the schema by one version (PRAGMA user_version).
MIGRATIONS = [_migration_1, _migration_2]


def migrate(conn: sqlite3.Connection, seed: bool = True) -> int:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > len(MIGRATIONS):
        log.warning("Database schema v%s is newer than this app (v%s).", current, len(MIGRATIONS))
        return current
    for version, step in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        with transaction(conn):
            step(conn, seed)
            conn.execute(f"PRAGMA user_version = {version}")
        log.info("Database migrated to schema v%s", version)
    return len(MIGRATIONS)


# --------------------------------------------------------------------------- CRUD


def _load_json(raw: str, fallback):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        log.error("Corrupted JSON column in templates table; using an empty value.")
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _row_to_template(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "body": row["body"],
        "closing": row["closing"],
        "variables": _load_json(row["variables"], []),
        "sections": _load_json(row["sections"], []),
        "pinned": bool(row["pinned"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _insert(conn: sqlite3.Connection, data: dict) -> int:
    now = _now()
    cur = conn.execute(
        "INSERT INTO templates (title, description, body, closing, variables, sections, pinned,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["title"], data["description"], data["body"], data["closing"],
            _dump(data["variables"]), _dump(data["sections"]), int(data["pinned"]), now, now,
        ),
    )
    return int(cur.lastrowid)


def list_templates(conn: sqlite3.Connection, pinned_only: bool = False) -> list[dict]:
    sql = f"SELECT {COLUMNS} FROM templates"
    if pinned_only:
        sql += " WHERE pinned = 1"
    items = [_row_to_template(row) for row in conn.execute(sql)]
    items.sort(key=lambda t: (t["title"].casefold(), t["id"]))
    return items


def get_template(conn: sqlite3.Connection, template_id: int) -> dict | None:
    row = conn.execute(f"SELECT {COLUMNS} FROM templates WHERE id = ?", (template_id,)).fetchone()
    return _row_to_template(row) if row else None


def create_template(conn: sqlite3.Connection, data: dict) -> int:
    with transaction(conn):
        return _insert(conn, data)


def update_template(conn: sqlite3.Connection, template_id: int, data: dict) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE templates SET title = ?, description = ?, body = ?, closing = ?, variables = ?,"
            " sections = ?, pinned = ?, updated_at = ? WHERE id = ?",
            (
                data["title"], data["description"], data["body"], data["closing"],
                _dump(data["variables"]), _dump(data["sections"]), int(data["pinned"]), _now(),
                template_id,
            ),
        )
        return cur.rowcount > 0


def set_pinned(conn: sqlite3.Connection, template_id: int, pinned: bool) -> bool:
    with transaction(conn):
        cur = conn.execute("UPDATE templates SET pinned = ? WHERE id = ?", (int(pinned), template_id))
        return cur.rowcount > 0


def delete_template(conn: sqlite3.Connection, template_id: int) -> bool:
    with transaction(conn):
        cur = conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------- polish prompts & settings


def _prompt_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "prompt": row["prompt"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_prompts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM polish_prompts ORDER BY id")
    return [_prompt_row(r) for r in rows]


def get_prompt(conn: sqlite3.Connection, prompt_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM polish_prompts WHERE id = ?", (prompt_id,)).fetchone()
    return _prompt_row(row) if row else None


def active_prompt(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM polish_prompts WHERE active = 1 ORDER BY id LIMIT 1").fetchone()
    return _prompt_row(row) if row else None


def create_prompt(conn: sqlite3.Connection, name: str, prompt: str, active: bool) -> int:
    now = _now()
    with transaction(conn):
        if active:
            conn.execute("UPDATE polish_prompts SET active = 0")
        cur = conn.execute(
            "INSERT INTO polish_prompts (name, prompt, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, prompt, int(active), now, now),
        )
        return int(cur.lastrowid)


def update_prompt(conn: sqlite3.Connection, prompt_id: int, name: str, prompt: str) -> bool:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE polish_prompts SET name = ?, prompt = ?, updated_at = ? WHERE id = ?",
            (name, prompt, _now(), prompt_id),
        )
        return cur.rowcount > 0


def activate_prompt(conn: sqlite3.Connection, prompt_id: int) -> bool:
    """Make one prompt the active one (only one can be active)."""
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM polish_prompts WHERE id = ?", (prompt_id,)).fetchone():
            return False
        conn.execute("UPDATE polish_prompts SET active = CASE WHEN id = ? THEN 1 ELSE 0 END", (prompt_id,))
        return True


def delete_prompt(conn: sqlite3.Connection, prompt_id: int) -> bool:
    with transaction(conn):
        cur = conn.execute("DELETE FROM polish_prompts WHERE id = ?", (prompt_id,))
        return cur.rowcount > 0


def get_settings(conn: sqlite3.Connection, defaults: dict[str, str]) -> dict[str, str]:
    stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    return {key: stored.get(key, value) for key, value in defaults.items()}


def save_settings(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    with transaction(conn):
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


# --------------------------------------------------------------------------- example data

SEED_TEMPLATES = [
    {
        "title": "Panel Login",
        "description": "لینک پنل، و اگه شماره همراه زبان‌آموز رو داریم، شماره ورود.",
        "body": "لطفا از طریق لینک panel.example.com وارد پنل خود بشید.",
        "pinned": True,
        "sections": [
            {
                "id": "s1",
                "question": "زبان‌آموز شماره همراه ثبت‌شده داره؟",
                "choices": [
                    {"id": "c1", "label": "داره", "text": "و از شماره همراه {{number}} جهت ورود استفاده کنید."},
                    {"id": "c2", "label": "نداره", "text": ""},
                ],
            }
        ],
        "variables": [
            {"name": "number", "label": "شماره همراه", "type": "number", "required": True,
             "placeholder": "09123456789"},
        ],
    },
    {
        "title": "Class Link Resend",
        "description": "Resend the live class link, with the passcode if there is one.",
        "body": "Hi {{student_name}},\n\nHere's the link to your class: {{class_link}}",
        "closing": "See you in class, {{student_name}}!\nBest wishes",
        "pinned": True,
        "sections": [
            {
                "id": "s1",
                "question": "Does the class need a passcode?",
                "choices": [
                    {"id": "c1", "label": "Yes", "text": "Passcode: {{passcode}}"},
                    {"id": "c2", "label": "No", "text": ""},
                ],
            }
        ],
        "variables": [
            {"name": "student_name", "label": "", "type": "text", "required": True, "placeholder": "Sara"},
            {"name": "class_link", "label": "", "type": "text", "required": True,
             "placeholder": "https://class.example.com/…"},
            {"name": "passcode", "label": "", "type": "text", "required": True, "placeholder": "4821"},
        ],
    },
    {
        "title": "یادآوری آزمون ماک",
        "description": "یادآوری زمان آزمون ماک و نوع آزمون.",
        "body": "سلام {{student_name}} عزیز،\nآزمون ماک شما {{exam_date}} ساعت {{exam_time}} برگزار می‌شه.",
        "closing": "اگه سؤالی داشتید، همین‌جا بپرسید. موفق باشید!",
        "pinned": False,
        "sections": [
            {
                "id": "s1",
                "question": "نوع آزمون؟",
                "choices": [
                    {"id": "c1", "label": "آکادمیک", "text": "نوع آزمون: آکادمیک"},
                    {"id": "c2", "label": "جنرال", "text": "نوع آزمون: جنرال ترینینگ"},
                ],
            }
        ],
        "variables": [
            {"name": "student_name", "label": "", "type": "text", "required": True, "placeholder": "سارا"},
            {"name": "exam_date", "label": "", "type": "text", "required": True, "placeholder": "شنبه ۲۰ مهر"},
            {"name": "exam_time", "label": "", "type": "text", "required": True, "placeholder": "۱۰ صبح"},
        ],
    },
]
