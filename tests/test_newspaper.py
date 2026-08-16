"""The opening newspaper's six areas must not tread on each other.

Every area is erased before its Spanish is drawn, and they are erased in the
order the table lists them, so a rectangle that reaches into its neighbour
wipes out text that is already on the page. That is not hypothetical: the
girl's caption looks like it runs to x 63 because the ``left.b`` column
crosses behind it, and a rectangle drawn that wide erased the last two
letters of the column's word after they had been drawn — silently, since the
column still read as a word.

The width checks below are the same ones the build makes; the build answers
an over-long line by leaving that area Japanese, and this keeps the pack at
zero of those.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from navi import font as font_mod
from navi.gfx import NEWSPAPER_AREAS, Typesetter
from navi.table import Charset

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKS = sorted(p for p in (REPO_ROOT / "langs").iterdir() if p.is_dir())


def newspaper(pack: Path) -> dict:
    path = pack / "gfx.json"
    if not path.exists():
        return {}
    texts = json.loads(path.read_text("utf-8")).get("newspaper") or {}
    return {key: [value] if isinstance(value, str) else list(value)
            for key, value in texts.items()}


def test_no_two_areas_share_a_pixel():
    items = list(NEWSPAPER_AREAS.items())
    for index, (name, (x, y, w, h, _)) in enumerate(items):
        for other, (ox, oy, ow, oh, _) in items[index + 1:]:
            assert not (x < ox + ow and ox < x + w
                        and y < oy + oh and oy < y + h), f"{name} meets {other}"


def test_every_area_is_on_the_page():
    for name, (x, y, w, h, _) in NEWSPAPER_AREAS.items():
        assert 0 <= x and x + w <= 240, name
        assert 0 <= y and y + h <= 160, name


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p.name)
def test_pack_only_names_areas_that_exist(pack: Path):
    for key in newspaper(pack):
        assert key in NEWSPAPER_AREAS, key


@pytest.mark.game
@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p.name)
def test_every_line_fits_its_area(pack: Path, game_rom):
    texts = newspaper(pack)
    if not texts:
        pytest.skip(f"{pack.name} has no newspaper")
    charset = Charset.load(REPO_ROOT / "data" / "charset-latin.tbl")
    built, _ = font_mod.build_font(game_rom, charset)
    setter = Typesetter(game_rom, charset, built)
    for key, lines in texts.items():
        x, y, w, h, rotated = NEWSPAPER_AREAS[key]
        along, across = (h, w) if rotated else (w, h)
        stack = len(lines) * font_mod.GLYPH_HEIGHT + len(lines) - 1
        assert stack <= across, f"{key}: {len(lines)} lines need {stack}px"
        for line in lines:
            span = setter.measure(line)
            assert span <= along, f"{key}: {line!r} is {span}px, {along}px fit"
