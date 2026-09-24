# PyInstaller spec -- builds two programs that share one folder of libraries:
#
#   Recruiting Desk.exe      windowed; what families double-click
#   recruiting-desk-mcp.exe  console; what Claude Desktop runs as a local command
#
# Two because MCP talks over stdin/stdout, and a windowed Windows program has
# neither. One folder (onedir) rather than one file, because a single-file
# build unpacks itself to a temp folder on every launch -- slow to start, and
# exactly the behaviour antivirus products flag.
#
# Build from the repository root:
#   pyinstaller installer/recruiting_desk.spec --noconfirm

import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")
ICON = os.path.join(SPECPATH, "icon.ico")

datas = [(os.path.join(SRC, "recruiting_desk", "static"), "recruiting_desk/static")]
hidden = (
    collect_submodules("recruiting_desk")
    + collect_submodules("uvicorn")
    # mcp.cli pulls in an optional CLI dependency and exits on import without it.
    + collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli"))
)

def analysis(script):
    return Analysis(
        [os.path.join(SPECPATH, script)],
        pathex=[SRC],
        datas=datas,
        hiddenimports=hidden,
        excludes=["tkinter", "matplotlib", "numpy", "pandas"],
    )

app_a = analysis("launch_app.py")
mcp_a = analysis("launch_mcp.py")

app_pyz = PYZ(app_a.pure)
mcp_pyz = PYZ(mcp_a.pure)

app_exe = EXE(
    app_pyz, app_a.scripts, [],
    exclude_binaries=True,
    name="Recruiting Desk",
    console=False,
    icon=ICON,
)
mcp_exe = EXE(
    mcp_pyz, mcp_a.scripts, [],
    exclude_binaries=True,
    name="recruiting-desk-mcp",
    console=True,
    icon=ICON,
)

coll = COLLECT(
    app_exe, app_a.binaries, app_a.datas,
    mcp_exe, mcp_a.binaries, mcp_a.datas,
    name="RecruitingDesk",
)
