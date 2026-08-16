"""Where your copy of the game is. One file, two keys, never committed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "navi.config.json"


@dataclass
class Config:
    rom: str = ""
    language: str = "es"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(rom=raw.get("rom", ""), language=raw.get("language", "es"))

    def save(self, path: Path | None = None) -> Path:
        path = path or CONFIG_PATH
        path.write_text(
            json.dumps({"rom": self.rom, "language": self.language}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @property
    def rom_path(self) -> Path | None:
        return Path(self.rom).expanduser() if self.rom else None

    def resolve_rom(self) -> Path:
        """The ROM to work on, looked for in the obvious places if unset."""
        if self.rom:
            path = self.rom_path
            if path and path.is_file():
                return path
            raise FileNotFoundError(f"navi.config.json points at {self.rom}, which is not there")
        candidates = sorted(ROOT.glob("*.gba"))
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise FileNotFoundError(
                "No .gba file found. Put your dump in the project folder, "
                "or run: python navi.py rom <path>"
            )
        raise FileNotFoundError(
            "Several .gba files here; pick one with: python navi.py rom <path>"
        )
