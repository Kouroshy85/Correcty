# Correcty

A local desktop tool for reusable message templates and AI text polishing, with English and Persian interfaces.

Create templates with `{{placeholders}}`, add optional paragraphs, pin frequent replies, and copy completed messages. Polish text using your own local Ollama model and editable prompts. Persian includes right-to-left layout and the bundled Vazirmatn font.

## Install on Windows

Download **Correcty-Setup-1.0.0.exe** from [Releases](https://github.com/Kouroshy85/Correcty/releases/latest), run it, and launch **Correcty**. Python is not required for the installer. The app opens in your browser at **http://127.0.0.1:5056** and runs locally in the background. Use **Stop Correcty** in the Start menu to stop it.

The installer is unsigned; Windows may display an unknown-publisher notice.

## Run from source

Requires Python 3.10 or newer. On Windows, double-click **Start Correcty.bat** to create a virtual environment, install dependencies, and open the app. **Stop Correcty.bat** stops it.

Alternatively:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py --open-browser
```

On macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --open-browser
```

## Local AI polishing

Install [Ollama](https://ollama.com/), start it, and install an instruction-following model such as `qwen3:4b-instruct`. Choose an installed model in **Settings → AI model**. Create or edit instructions in **Settings → Polish prompts**. A general writing prompt is included. Template features work without Ollama.

Correcty binds to the loopback address and sends polishing requests only to a local Ollama endpoint. Templates and prompts are stored on your computer, with no built-in cloud sync. The Flask development server is intended for personal local use.

## Data and configuration

Windows data: `%APPDATA%\Correcty`.
macOS/Linux data: `$XDG_DATA_HOME/correcty` (default `~/.local/share/correcty`).

The folder contains `templates.db`, `logs/app.log`, and a running process file. To back up templates and settings, stop Correcty and copy `templates.db`. A fresh database includes generic example templates and a general writing prompt. No personal databases or model files are distributed.

| Option | CLI / environment variable |
| --- | --- |
| Port (default 5056) | `--port 5060` / `CORRECTY_PORT` |
| Data folder | `--data-dir PATH` / `CORRECTY_DATA_DIR` |
| Suppress browser opening | `CORRECTY_NO_BROWSER=1` |
| Stop background instance | `--stop` |

## Development and Windows builds

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe installer\make_icon.py
.venv\Scripts\pyinstaller.exe --noconfirm --clean Correcty.spec
```

The portable build is `dist/Correcty/Correcty.exe`; keep its `_internal` folder beside it. With [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\installer.iss
```

The installer is created in `installer/Output/`. Correcty uses its own executable name, installer identifier, data folder, language cookie, and default port.

## License

Correcty source code is licensed under [MIT](LICENSE). The bundled Vazirmatn font is licensed separately under the [SIL Open Font License 1.1](correcty/static/fonts/OFL.txt). Dependencies retain their respective licenses.
