"""Spreadsheets, for the people who would rather work in one."""

from __future__ import annotations

import csv
from pathlib import Path

from .catalog import Catalog
from .lang import Pack

FIELDS = ("key", "where", "japanese", "translation", "note")


def write_csv(path: Path, catalog: Catalog, pack: Pack, pending_only: bool = False,
              prefix: str | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for line in sorted(catalog.lines.values(), key=lambda l: l.key):
            if prefix and not line.key.startswith(prefix):
                continue
            entry = pack.get(line.key)
            translation = entry.t if entry else ""
            if pending_only and translation:
                continue
            writer.writerow({
                "key": line.key,
                "where": f"{line.kind} @{line.offset:06X}",
                "japanese": line.text,
                "translation": translation,
                "note": "",
            })
            written += 1
    return written


def read_csv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("key") or "").strip()
            text = (row.get("translation") or "").strip()
            if key:
                out[key] = text
    return out
