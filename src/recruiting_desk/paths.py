"""
Where things live.

Two different kinds of location, and they must not be confused:

- DATA is the family's: the athlete record, the coach list, what was sent, the
  AI key, the GameChanger session. It lives in the user's own profile folder and
  survives uninstalling and reinstalling the app.

      Windows   %APPDATA%\\RecruitingDesk
      macOS     ~/Library/Application Support/RecruitingDesk
      Linux     ~/.local/share/recruiting-desk

  RECRUITING_DESK_HOME overrides it, which is how the tests and anyone running
  two separate campaigns keep them apart.

- RESOURCES are the app's own files -- the pages it serves. Inside a packaged
  build they are unpacked by PyInstaller to a temporary folder; from source they
  sit next to this file.
"""

import os
import sys
import pathlib

APP_NAME = "RecruitingDesk"


def data_dir() -> pathlib.Path:
    override = os.environ.get("RECRUITING_DESK_HOME") or os.environ.get("GC_RECRUITING_HOME")
    if override:
        p = pathlib.Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(pathlib.Path.home() / "AppData" / "Roaming")
        p = pathlib.Path(base) / APP_NAME
    elif sys.platform == "darwin":
        p = pathlib.Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(pathlib.Path.home() / ".local" / "share")
        p = pathlib.Path(base) / "recruiting-desk"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_dir() -> pathlib.Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return pathlib.Path(bundled) / "recruiting_desk"
    return pathlib.Path(__file__).resolve().parent


def static_dir() -> pathlib.Path:
    return resource_dir() / "static"
