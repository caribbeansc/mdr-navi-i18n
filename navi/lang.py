"""Language packs: what a translation is, on disk.

A pack never holds the game's text. Each entry names a place in the ROM, a
fingerprint of the Japanese that was there when the line was written, and the
translation. The fingerprint is enough to notice that a line has moved or that
the pack was written against a different release, and useless for getting the
Japanese back.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

LANGS_DIR = Path(__file__).resolve().parent.parent / "langs"

FINGERPRINT_LENGTH = 12


def fingerprint(text: str) -> str:
    """A short, one-way name for a source line."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


@dataclass
class Entry:
    """One translated line."""

    key: str
    src: str
    t: str

    def to_json(self) -> dict:
        return {"key": self.key, "src": self.src, "t": self.t}

    @classmethod
    def from_json(cls, raw: dict) -> "Entry":
        return cls(key=raw["key"], src=raw["src"], t=raw["t"])


@dataclass
class Pack:
    """Everything one language has translated."""

    code: str
    name: str = ""
    english_name: str = ""
    credits: list[str] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    entries: dict[str, Entry] = field(default_factory=dict)
    path: Path | None = None
    #: The release this pack was loaded for, when it is not the canonical one.
    release: str = ""

    # -- disk ------------------------------------------------------------

    @classmethod
    def load(cls, code: str, root: Path | None = None,
             release: str = "") -> "Pack":
        """Read a pack, optionally as one particular release sees it.

        The pack is written against Kuwagata, which is what every key names.
        The other release is the same game with eleven scripts and a few name
        tables changed — the cover Medabot is a different one — so its own
        wording lives in ``langs/<code>/<release>/`` and is loaded on top.
        Everything else is shared, and stays a single translation.
        """
        root = (root or LANGS_DIR) / code
        meta_path = root / "lang.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"No language pack at {root}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pack = cls(
            code=meta.get("code", code),
            name=meta.get("name", code),
            english_name=meta.get("english_name", ""),
            credits=meta.get("credits", []),
            validation=meta.get("validation", {}),
            path=root,
            release=release if release.lower() not in ("", "kuwagata") else "",
        )
        for part in sorted(root.glob("*.json")):
            if part.name == "lang.json":
                continue
            pack._load_part(part)
        for part in sorted(root.glob("script/*.json")):
            pack._load_part(part)
        if pack.release:
            for part in sorted((root / pack.subdir).glob("*.json")):
                pack._load_part(part)
            for part in sorted((root / pack.subdir / "script").glob("*.json")):
                pack._load_part(part)
        return pack

    @property
    def subdir(self) -> str:
        """Where this release's own lines live inside the pack."""
        return self.release.lower()

    def _load_part(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw.get("entries", []):
            entry = Entry.from_json(item)
            self.entries[entry.key] = entry

    def save_part(self, name: str, entries: list[Entry]) -> Path:
        if self.path is None:
            raise ValueError("This pack has no directory")
        root = self.path / self.subdir if self.release else self.path
        path = root / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "part": name,
            "entries": [e.to_json() for e in sorted(entries, key=lambda e: e.key)],
        }
        path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
        return path

    def save_meta(self) -> Path:
        if self.path is None:
            raise ValueError("This pack has no directory")
        self.path.mkdir(parents=True, exist_ok=True)
        path = self.path / "lang.json"
        body = {
            "code": self.code,
            "name": self.name,
            "english_name": self.english_name,
            "validation": self.validation,
            "credits": self.credits,
        }
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return path

    # -- use -------------------------------------------------------------

    def get(self, key: str) -> Entry | None:
        return self.entries.get(key)

    def loose_sites(self) -> dict[int, str]:
        """Where this pack's loose lines are in Kuwagata, and what was there.

        The catalogue of another release follows this through the offset map
        to find strings its own scan worded differently, and only believes it
        where the fingerprint still matches — see :func:`navi.catalog.seeded`.
        """
        out: dict[int, str] = {}
        for key, entry in self.entries.items():
            head, _, rest = key.partition(":")
            if head != "str" or ":" in rest or not entry.src:
                continue          # a release's own line, named after its dump
            try:
                out[int(rest, 16)] = entry.src
            except ValueError:
                continue
        return out

    def translation_for(self, key: str, source: str) -> str | None:
        """The translation for a line, if the pack has one and it still fits.

        A mismatched fingerprint means the pack was written against different
        text; the build leaves the line alone rather than write the wrong words.
        """
        entry = self.entries.get(key)
        if entry is None or not entry.t:
            return None
        if entry.src and entry.src != fingerprint(source):
            return None
        return entry.t

    def stale(self, sources: dict[str, str]) -> list[str]:
        """Keys whose source text has changed since the translation was written."""
        out = []
        for key, entry in self.entries.items():
            source = sources.get(key)
            if source is None:
                out.append(key)
            elif entry.src and entry.src != fingerprint(source):
                out.append(key)
        return sorted(out)

    def __len__(self) -> int:
        return sum(1 for e in self.entries.values() if e.t)


def available(root: Path | None = None) -> list[str]:
    root = root or LANGS_DIR
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "lang.json").is_file())
