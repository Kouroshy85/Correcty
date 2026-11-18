"""Start Correcty on this computer.

    python app.py                 start the server on http://127.0.0.1:5056
    python app.py --open-browser  start it and open the app in the default browser
    python app.py --stop          stop a copy that is running in the background
    python app.py --port 5060     use another port (or set CORRECTY_PORT)
    python app.py --data-dir DIR  keep the database somewhere else (or set CORRECTY_DATA_DIR)

If Correcty is already running, starting it again just opens the browser.
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import signal
import sys
import threading
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = 5056

# pythonw.exe (used by the Windows launcher) has no console: give stray prints somewhere to go.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from correcty import __version__, create_app, default_data_dir  # noqa: E402

log = logging.getLogger("correcty")


def _show_message(message: str, error: bool = False) -> None:
    """Print a message, or show it in a dialog when there is no console window (pythonw, packaged .exe)."""
    print(message, file=sys.stderr if error else sys.stdout)
    if sys.platform == "win32" and not sys.stdin:
        try:
            import ctypes

            icon = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, message, "Correcty", icon)
        except Exception:  # pragma: no cover - best effort only
            pass


def _show_error(message: str) -> None:
    _show_message(message, error=True)


def _running_instance(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "healthz", timeout=1.5) as response:
            return json.load(response).get("app") == "correcty"
    except Exception:
        return False


def _setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stdin:  # interactive console: also log there
        root.addHandler(logging.StreamHandler())


def _stop(data_dir: Path, url: str) -> int:
    pid_file = data_dir / "app.pid"
    if not _running_instance(url) or not pid_file.exists():
        _show_message("Correcty is not running.")
        return 0
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError) as exc:
        _show_error(f"Could not stop Correcty: {exc}")
        return 1
    # On Windows the process is terminated without running atexit, so tidy up its pid file here.
    pid_file.unlink(missing_ok=True)
    _show_message("Correcty stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Correcty locally.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CORRECTY_PORT", DEFAULT_PORT)))
    parser.add_argument("--open-browser", action="store_true", help="open the app in the default browser")
    parser.add_argument("--stop", action="store_true", help="stop a running copy")
    parser.add_argument("--data-dir", help="store the database and logs in this folder instead")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["CORRECTY_DATA_DIR"] = str(Path(args.data_dir).resolve())
    url = f"http://{HOST}:{args.port}/"
    data_dir = default_data_dir()
    # A packaged .exe (PyInstaller) has no launcher script, so it always opens the browser.
    wants_browser = args.open_browser or getattr(sys, "frozen", False)
    open_browser = wants_browser and os.environ.get("CORRECTY_NO_BROWSER") != "1"

    if args.stop:
        return _stop(data_dir, url)

    if _running_instance(url):
        print(f"Correcty is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    data_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(data_dir)
    try:
        app = create_app()
    except Exception as exc:
        log.exception("Startup failed")
        _show_error(f"Correcty couldn't start:\n{exc}\n\nDetails: {data_dir / 'logs' / 'app.log'}")
        return 1

    pid_file = data_dir / "app.pid"
    pid_file.write_text(str(os.getpid()))
    atexit.register(lambda: pid_file.unlink(missing_ok=True))

    log.info("Correcty %s starting at %s (data: %s)", __version__, url, data_dir)
    print(f"Correcty is running at {url}  (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        app.run(host=HOST, port=args.port, debug=False, use_reloader=False, threaded=True)
    except OSError as exc:
        log.exception("Server failed")
        _show_error(
            f"Correcty couldn't use port {args.port} ({exc}).\n\n"
            "Another program may be using it. Set CORRECTY_PORT to a different number and try again."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
