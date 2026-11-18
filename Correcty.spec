# PyInstaller build for the Windows app: one folder, no console window.
#   .venv\Scripts\pyinstaller.exe --noconfirm --clean "Correcty.spec"
# Output: dist\Correcty\Correcty.exe (installer\installer.iss packages that folder).
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "correcty" / "templates"), "correcty/templates"),
        (str(ROOT / "correcty" / "static"), "correcty/static"),
    ],
    hiddenimports=["correcty.database", "correcty.routes"],  # imported inside create_app()
    excludes=["tkinter", "PIL", "setuptools"],  # not used by the app
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Correcty",
    icon=str(ROOT / "installer" / "correcty.ico"),
    console=False,  # windowed: errors are shown in a dialog and written to the log
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Correcty",
    upx=False,
)
