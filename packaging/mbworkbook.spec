# PyInstaller spec: one --onedir bundle carrying both front ends.
#
# Two executables share a single COLLECT, so the Qt DLLs and the requirements
# snapshot are on disk once rather than twice:
#
#   MeritBadgeWorkbook.exe  windowed, no console - the desktop app
#   mbworkbook.exe          console - the same CLI, for scripting a batch
#
# --onedir rather than --onefile on purpose. A onefile build unpacks the whole
# Qt runtime to a temp directory on every launch, which is slow and is a
# reliable way to get flagged by antivirus heuristics. The installer hides the
# directory anyway.
#
# Build with:  python -m PyInstaller packaging/mbworkbook.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent

# The prebuilt requirements. Without this the app still runs, but every badge
# costs a network round trip, so treat a missing snapshot as a broken build.
SNAPSHOT = ROOT / "mbworkbook" / "data" / "requirements.json"
if not SNAPSHOT.is_file():
    raise SystemExit(
        "mbworkbook/data/requirements.json is missing. "
        "Run: python tools/build_snapshot.py"
    )

datas = [(str(SNAPSHOT), "mbworkbook/data")]
datas += collect_data_files("reportlab")  # built-in fonts and glyph tables

# Qt ships far more than a form and a tree view need. Dropping these takes the
# bundle down by roughly half without touching anything the app uses.
EXCLUDED_QT = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNfc", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql",
    "PySide6.QtStateMachine", "PySide6.QtSvgWidgets", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets", "PySide6.QtXml",
]

# reportlab and pypdf are imported inside functions, so that the CLI still
# starts when they are absent. PyInstaller's static pass does not follow that,
# and collect_data_files brings the fonts without the code - which fails at
# runtime with "PDF output needs reportlab" in a build that does have it. So
# name the packages explicitly.
hiddenimports = [
    "mbworkbook.render.card", "mbworkbook.render.cardform",
    "mbworkbook.render.pdf", "mbworkbook.render.html",
]
hiddenimports += collect_submodules("reportlab")
hiddenimports += collect_submodules("pypdf")

excludes = EXCLUDED_QT + [
    "tkinter",       # the old front end; nothing imports it any more
    "matplotlib", "numpy", "pandas", "scipy",
    "pytest", "_pytest", "setuptools", "pip",
]
# Not PIL: reportlab imports Pillow on the way into reportlab.lib, so excluding
# it produces a bundle that reports "PDF output needs reportlab" while shipping
# all 159 reportlab modules.

analysis = Analysis(
    [str(SPEC_DIR / "entry_gui.py"), str(SPEC_DIR / "entry_cli.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(analysis.pure)

def script(name):
    """The one PYSOURCE entry for ``name``, so each EXE gets its own main."""
    picked = [s for s in analysis.scripts if s[0] == name]
    if not picked:
        raise SystemExit(f"spec error: no script entry named {name!r}")
    return picked


gui = EXE(
    pyz,
    script("entry_gui"),
    [],
    exclude_binaries=True,
    name="MeritBadgeWorkbook",
    console=False,          # no console window behind the app
    icon=str(SPEC_DIR / "app.ico") if (SPEC_DIR / "app.ico").is_file() else None,
)

cli = EXE(
    pyz,
    script("entry_cli"),
    [],
    exclude_binaries=True,
    name="mbworkbook",
    console=True,           # the CLI needs one
    icon=str(SPEC_DIR / "app.ico") if (SPEC_DIR / "app.ico").is_file() else None,
)

COLLECT(
    gui,
    cli,
    analysis.binaries,
    analysis.datas,
    name="MeritBadgeWorkbook",
)
