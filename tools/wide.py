#!/usr/bin/env python3
"""Which rows are wider than the box that draws them.

  python3 tools/wide.py             # rows not yet recorded as debt
  python3 tools/wide.py --lang en   # another pack; every pack has its own debt
  python3 tools/wide.py --all       # every over-wide row, worst first
  python3 tools/wide.py --update    # record the current set as the debt

A line is not too long on its own: it is too long for its box. navi/boxes.py
says which box draws which range and how many columns each one really paints,
every width measured in the emulator with an A-Z-0-9 ruler. This walks the
pack against that.

langs/<code>/wide.json is DEBT, not a list of exceptions — it should shrink to
zero. Run --update only after shortening a batch, never to silence one.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from navi.boxes import box_for                      # noqa: E402
from navi.table import rows_by_box                  # noqa: E402

def sites(pack: Path) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    gfx = json.loads((pack / "gfx.json").read_text("utf-8"))
    for key, entry in gfx["extra_strings"].items():
        for site in entry.get("sites", []):
            out[int(str(site), 16)] = (entry.get("t", ""), f"extra:{key}")
    for entry in json.loads((pack / "menus.json").read_text("utf-8"))["entries"]:
        if entry["key"].startswith("str:") and entry.get("t"):
            out[int(entry["key"][4:], 16)] = (entry["t"], entry["key"])
    return out


#: What a pack's debt file says when it has none yet.
EMPTY = ("Rows still wider than the box that draws them, as OFFSET:COLUMNS. "
         "This is DEBT, not a list of exceptions: it must shrink to zero, and "
         "tests/test_control_codes.py fails on anything not in it so a new one "
         "cannot be added quietly. The widths themselves live in navi/boxes.py, "
         "measured in the emulator with a ruler. Regenerate after shortening a "
         "batch: python3 tools/wide.py --update.")


def main() -> int:
    argv = sys.argv[1:]
    code = "es"
    if "--lang" in argv:
        at = argv.index("--lang")
        code = argv[at + 1] if at + 1 < len(argv) else "es"
        del argv[at:at + 2]
    flags = {a for a in argv if a.startswith("--")}
    pack = ROOT / "langs" / code
    debt_path = pack / "wide.json"
    found = []
    for at, (text, where) in sorted(sites(pack).items()):
        box = box_for(at)
        if box.columns is None:
            continue
        for row in rows_by_box(text):
            limit = box.columns if row.first_in_box else box.later_rows
            if limit is not None and len(row.text) > limit:
                found.append((at, where, box, len(row.text), limit, row.text))

    if "--update" in flags:
        comment = (json.loads(debt_path.read_text("utf-8"))["comment"]
                   if debt_path.is_file() else EMPTY)
        debt_path.write_text(json.dumps(
            {"comment": comment,
             "known": sorted({f"{at:06X}:{n}" for at, _, _, n, _, _ in found})},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"deuda registrada: {len(found)} filas")
        return 0

    debt = set(json.loads(debt_path.read_text("utf-8"))["known"]
               if debt_path.is_file() else [])
    show = found if "--all" in flags else [
        f for f in found if f"{f[0]:06X}:{f[3]}" not in debt]
    scope = "" if "--all" in flags else f" sin registrar (de {len(found)})"
    print(f"{len(show)} filas más anchas que su caja{scope}")
    for at, where, box, n, limit, text in sorted(show, key=lambda f: -f[3])[:40]:
        print(f"  {at:06X} [{where}] {n:2d}/{limit} en {box.name}: {text!r}")
    return 1 if show else 0


if __name__ == "__main__":
    raise SystemExit(main())
