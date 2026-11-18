"""Correcty — quick replies, reusable templates and local text polishing."""
from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

from flask import Flask

__version__ = "1.0.0"
APP_FOLDER_NAME = "Correcty"

# Windows can map .js to text/plain through the registry, which breaks ES modules.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")


def default_data_dir() -> Path:
    """Persistent, per-user folder for the database and logs.

    Windows: %APPDATA%\\Correcty. Elsewhere: $XDG_DATA_HOME/correcty.
    Override with the CORRECTY_DATA_DIR environment variable.
    """
    override = os.environ.get("CORRECTY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_FOLDER_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "correcty"


def _static_version(folder: Path) -> str:
    """Short fingerprint of the static files, used in their URLs.

    ES modules import each other by relative path, so putting the version in the folder part of the
    URL (/static/<version>/js/app.js) makes browsers fetch fresh copies of every file after an update.
    """
    digest = hashlib.sha1()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(f"{path.relative_to(folder).as_posix()}:{stat.st_size}:{int(stat.st_mtime)}".encode())
    return digest.hexdigest()[:10]


def create_app(test_config: dict | None = None) -> Flask:
    static_folder = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, static_url_path=f"/static/{_static_version(static_folder)}")
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    data_dir = Path((test_config or {}).get("DATA_DIR") or default_data_dir())
    app.config.from_mapping(
        DATA_DIR=str(data_dir),
        DATABASE=str(data_dir / "templates.db"),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SEED_EXAMPLES=True,
        ALLOWED_HOSTS={"127.0.0.1", "localhost", "::1"},
        SEND_FILE_MAX_AGE_DEFAULT=0,  # always revalidate (cheap 304s locally); URLs are versioned too
    )
    if test_config:
        app.config.update(test_config)
    data_dir.mkdir(parents=True, exist_ok=True)

    from . import database, routes

    database.init_app(app)
    routes.init_app(app)
    return app
