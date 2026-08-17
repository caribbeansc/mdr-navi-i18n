#!/usr/bin/env python3
"""Which rows are wider than the box that draws them.

  python3 tools/wide.py             # rows not yet recorded as debt
  python3 tools/wide.py --all       # every over-wide row, worst first
  python3 tools/wide.py --update    # record the current set as the debt

A line is not too long on its own: it is too long for its box. navi/boxes.py
says which box draws which range and how many columns each one really paints,
every width measured in the emulator with an A-Z-0-9 ruler. This walks the
pack against that.

langs/es/wide.json is DEBT, not a list of exceptions — it should shrink to
zero. Run --update only after shortening a batch, never to silence one.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from navi.boxes import box_for                      # noqa: E402
from navi.table import rows_by_box                  # noqa: E402

PACK = ROOT / "langs/es"
DEBT = PACK / "wide.json"


def sites() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    gfx = json.loads((PACK / "gfx.json").read_text("utf-8"))
    for key, entry in gfx["extra_strings"].items():
        for site in entry.get("sites", []):
            out[int(str(site), 16)] = (entry.get("t", ""), f"extra:{key}")
    for entry in json.loads((PACK / "menus.json").read_text("utf-8"))["entries"]:
        if entry["key"].startswith("str:") and entry.get("t"):
            out[int(entry["key"][4:], 16)] = (entry["t"], entry["key"])
    return out


def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    found = []
    for at, (text, where) in sorted(sites().items()):
        box = box_for(at)
        if box.columns is None:
            continue
        for row in rows_by_box(text):
            limit = box.columns if row.first_in_box else box.later_rows
            if limit is not None and len(row.text) > limit:
                found.append((at, where, box, len(row.text), limit, row.text))

    if "--update" in flags:
        DEBT.write_text(json.dumps(
            {"comment": json.loads(DEBT.read_text("utf-8"))["comment"],
             "known": sorted({f"{at:06X}:{n}" for at, _, _, n, _, _ in found})},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"deuda registrada: {len(found)} filas")
        return 0

    debt = set(json.loads(DEBT.read_text("utf-8"))["known"])
    show = found if "--all" in flags else [
        f for f in found if f"{f[0]:06X}:{f[3]}" not in debt]
    scope = "" if "--all" in flags else f" sin registrar (de {len(found)})"
    print(f"{len(show)} filas más anchas que su caja{scope}")
    for at, where, box, n, limit, text in sorted(show, key=lambda f: -f[3])[:40]:
        print(f"  {at:06X} [{where}] {n:2d}/{limit} en {box.name}: {text!r}")
    return 1 if show else 0


if __name__ == "__main__":
    raise SystemExit(main())
