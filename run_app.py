"""
Entry point for the built app (PyInstaller) and for running from source:

    python run_app.py                   open the window
    python run_app.py "<file.pdf>"      open the window with a file
    python run_app.py --selftest [--selftest-log out.txt]
"""

import site
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Source copy started by the base pythonw.exe (the dev shortcut does this,
    # to avoid a console window): load this folder's .venv packages anyway.
    _root = Path(__file__).resolve().parent
    _site = _root / ".venv" / "Lib" / "site-packages"
    if _site.is_dir() and Path(sys.prefix).resolve() != (_root / ".venv").resolve():
        site.addsitedir(str(_site))
    sys.path.insert(0, str(_root))


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        from prestige_impose.selftest import run
        log = args[args.index("--selftest-log") + 1] if "--selftest-log" in args else None
        sys.exit(run(log))
    from prestige_impose.app import main as app_main
    app_main(args)


if __name__ == "__main__":
    main()
