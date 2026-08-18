"""Graphical patcher: pick your dump, pick a language, get a patched ROM.

A thin Tkinter shell over the same code ``navi.py build`` uses, so a player
who has never opened a terminal can translate their own cartridge dump. Built
into standalone Windows/macOS executables by ``.github/workflows/release.yml``
and published next to the IPS patches; running ``python gui.py`` from a
checkout works exactly the same.

The executable bundles this repository's code, ``langs/`` and ``data/`` —
never anything from the game. The user points it at their own Kuwagata or
Kabuto dump (told apart automatically), and the patched ROM is written next
to it. Nothing else is created: no configuration, no caches, no patch files.
"""
from __future__ import annotations

import json
import locale
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(BUNDLE_DIR))

SPANISH = (locale.getlocale()[0] or "").lower().startswith("es")


def tr(en: str, es: str) -> str:
    return es if SPANISH else en


def language_packs() -> list[tuple[str, str]]:
    """``(code, display name)`` for every pack the bundle ships."""
    from navi.lang import LANGS_DIR, available

    packs = []
    for code in available():
        try:
            meta = json.loads((LANGS_DIR / code / "lang.json").read_text("utf-8"))
            name = meta.get("name", code)
        except Exception:
            name = code
        packs.append((code, f"{name} ({code})"))
    return packs


def do_patch(rom_path: str | Path, code: str) -> Path:
    """The whole job: read the dump, build the translation, save the ROM.

    Mirrors ``navi.cli.cmd_build`` minus what a player does not need — the
    IPS patch, the leftovers scan, the save check — and writes the result
    next to the source dump. Raises on anything that must stop the build.
    """
    from navi.build import build as build_rom
    from navi.catalog import build as build_catalog
    from navi.lang import Pack
    from navi.rom import Rom
    from navi.table import load_latin
    from navi import validate as validate_mod

    rom = Rom.load(rom_path)
    print(tr(f"Medarot Navi {rom.release.name}, "
             f"{'known dump' if rom.is_known_dump else 'UNRECOGNISED dump'}",
             f"Medarot Navi {rom.release.name}, "
             f"{'dump conocido' if rom.is_known_dump else 'dump NO reconocido'}"))
    if not rom.is_known_dump:
        print(tr("  (not the SHA-1 on record; offsets may not line up)",
                 "  (no es el SHA-1 esperado; los offsets pueden no cuadrar)"))

    pack = Pack.load(code, release=rom.release.name)
    catalog = build_catalog(rom, seeds=pack.loose_sites())
    charset = load_latin()

    problems = validate_mod.check(catalog, pack, charset)
    blocking = [p for p in problems if p.kind in ("unencodable", "stale", "orphan")]
    if blocking:
        for problem in blocking[:10]:
            print(f"  {problem}")
        raise RuntimeError(tr(
            f"{len(blocking)} problems block this build; this pack does not "
            f"match your dump.",
            f"{len(blocking)} problemas bloquean el parcheo; este pack no "
            f"cuadra con tu dump."))

    report = build_rom(rom, catalog, pack, charset)
    print(report.summary())
    for key, why in report.skipped[:20]:
        print(f"  skipped {key}: {why}")

    source = Path(rom_path)
    out = source.parent / f"medarot-navi-{rom.release.name.lower()}-{pack.code}.gba"
    rom.save(out)
    print(tr(f"\nPatched ROM: {out}", f"\nROM parcheado: {out}"))
    return out


class LogSink:
    """File-like stdout replacement feeding the log widget through a queue."""

    def __init__(self, q: queue.Queue):
        self.q = q
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.q.put(line.replace("\r", ""))
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Medarot Navi Patcher")
        root.geometry("680x460")
        root.minsize(540, 380)

        self.q: queue.Queue = queue.Queue()
        self.busy = False

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text=tr("Game:", "Juego:"), width=8).pack(side="left")
        self.rom_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.rom_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text=tr("Your dump…", "Tu dump…"),
                   command=self.pick_rom).pack(side="left")

        hint = tr("Pick your own dump of メダロットnavi (Japan) — Kuwagata or "
                  "Kabuto, told apart automatically. The translated ROM is "
                  "written next to it; your original file is not touched.",
                  "Elige tu propio dump de メダロットnavi (Japón) — Kuwagata o "
                  "Kabuto, se distinguen solos. El ROM traducido se escribe al "
                  "lado; tu archivo original no se toca.")
        ttk.Label(frame, text=hint, foreground="#666",
                  wraplength=640).pack(fill="x", pady=(2, 6))

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text=tr("Language:", "Idioma:")).pack(side="left")
        self.lang_var = tk.StringVar()
        self.lang_box = ttk.Combobox(row2, textvariable=self.lang_var,
                                     state="readonly", width=24)
        self.lang_box.pack(side="left", padx=6)

        self.btn_patch = ttk.Button(
            row2, text=tr("Create patched ROM", "Crear ROM parcheado"),
            command=self.launch)
        self.btn_patch.pack(side="left", padx=4)

        self.log = tk.Text(frame, wrap="none", state="disabled", height=14,
                           background="#111", foreground="#ddd")
        self.log.pack(fill="both", expand=True)

        self.status = tk.StringVar(value=tr("Ready.", "Listo."))
        ttk.Label(frame, textvariable=self.status).pack(fill="x", pady=(6, 0))

        root.after(100, self.drain)
        self.load_packs()

    def load_packs(self) -> None:
        try:
            self.packs = language_packs()
            self.lang_box["values"] = [label for _, label in self.packs]
            if self.packs:
                self.lang_box.current(0)
        except Exception as exc:  # never die on startup
            self.q.put(f"!! {exc}")

    def pick_rom(self) -> None:
        path = filedialog.askopenfilename(
            title=tr("Your dump", "Tu dump"),
            filetypes=[("Game Boy Advance ROM", "*.gba"), ("All", "*.*")])
        if path:
            self.rom_var.set(path)

    def drain(self) -> None:
        try:
            while True:
                line = self.q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def launch(self) -> None:
        if self.busy:
            return
        rom = self.rom_var.get().strip()
        if not rom:
            messagebox.showinfo("Medarot Navi Patcher",
                                tr("Pick your .gba dump first.",
                                   "Primero elige tu dump .gba."))
            return
        self.busy = True
        self.btn_patch.state(["disabled"])
        self.status.set(tr("Patching…", "Parcheando…"))
        threading.Thread(target=self._run, args=(rom,), daemon=True).start()

    def _run(self, rom: str) -> None:
        sink = LogSink(self.q)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = sink
        out = None
        try:
            idx = self.lang_box.current()
            out = do_patch(rom, self.packs[idx][0] if idx >= 0 else "es")
        except Exception as exc:
            print(f"!! {type(exc).__name__}: {exc}")
        finally:
            sink.write("\n")
            sys.stdout, sys.stderr = old_out, old_err
            self.root.after(0, lambda: self._done(out))

    def _done(self, out: Path | None) -> None:
        self.busy = False
        self.btn_patch.state(["!disabled"])
        if out:
            self.status.set(tr("Done.", "Hecho."))
            self._reveal(out.parent)
        else:
            self.status.set(tr("Failed — see the log above.",
                               "Falló — revisa el registro."))

    @staticmethod
    def _reveal(path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
        except Exception:
            pass


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
