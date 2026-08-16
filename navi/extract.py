"""Writing the catalogue out where a translator can work on it.

Everything this produces lands in ``work/``, which is never committed: it holds
the game's own text, next to whatever translation exists so far.
"""

from __future__ import annotations

import json
from pathlib import Path

from .catalog import Catalog
from .lang import Pack
from .rom import Rom

WORK = Path(__file__).resolve().parent.parent / "work"


def dump(rom: Rom, catalog: Catalog, pack: Pack | None = None,
         out: Path | None = None) -> Path:
    """Write the whole catalogue as JSON, Japanese and translation side by side."""
    out = out or WORK / rom.release.name.lower()
    out.mkdir(parents=True, exist_ok=True)

    by_part: dict[str, list[dict]] = {}
    for line in sorted(catalog.lines.values(), key=lambda l: l.key):
        part = f"script_{line.script:04d}" if line.kind == "script" else "loose"
        record = {
            "key": line.key,
            "at": f"{line.offset:06X}",
            "jp": line.text,
            "src": line.src,
        }
        if pack is not None:
            entry = pack.get(line.key)
            record["t"] = entry.t if entry else ""
        by_part.setdefault(part, []).append(record)

    for part, records in by_part.items():
        path = out / f"{part}.json"
        path.write_text(
            json.dumps({"part": part, "entries": records}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )

    index = {
        "release": rom.release.name,
        "sha1": rom.sha1,
        "lines": len(catalog),
        "parts": {part: len(records) for part, records in sorted(by_part.items())},
    }
    (out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def text_report(catalog: Catalog, pack: Pack | None = None, limit: int = 0) -> str:
    """A flat listing, for reading in a terminal."""
    rows = []
    for line in sorted(catalog.lines.values(), key=lambda l: l.key):
        translated = pack.get(line.key).t if pack and pack.get(line.key) else ""
        rows.append(f"{line.key}\n  jp: {line.text}\n  {pack.code if pack else 'xx'}: {translated}")
        if limit and len(rows) >= limit:
            break
    return "\n".join(rows)
