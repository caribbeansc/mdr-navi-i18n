#!/usr/bin/env python3
"""Entry point: run ``python navi.py`` for the menu, or a subcommand directly.

Deliberately tiny, and with no dependencies of its own, so that a bare
``python navi.py`` works anywhere Python 3.10 does.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print(f"Python 3.10 or newer is needed; this is {sys.version.split()[0]}")
        raise SystemExit(3)
    from navi.cli import main

    raise SystemExit(main())
