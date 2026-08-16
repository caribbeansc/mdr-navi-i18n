"""Tests for navi/script.py: bounds from the master table, and the walker."""

from navi.script import read_scripts, read_strings, script_bounds, script_table
from navi.table import load_japanese


def test_script_bounds_dedupes_and_sizes(synth):
    bounds = script_bounds(synth.rom)
    assert bounds == [
        (synth.script_a, synth.script_a_len),
        (synth.script_b, synth.script_b_len),
    ]


def test_script_table_keeps_duplicates(synth):
    assert script_table(synth.rom) == list(synth.table_entries)


def test_walker_finds_straight_line_text(synth):
    scripts = read_scripts(synth.rom)
    assert len(scripts) == 2
    a = scripts[0]
    assert a.index == 0
    assert a.offset == synth.script_a
    assert a.subscripts == 1
    assert a.text_offsets() == sorted(synth.a_sites)


def test_walker_follows_jumps_and_branches(synth):
    b = read_scripts(synth.rom)[1]
    # 53 sits behind an 0x03 jump; 58 and 61 behind an 0x0A four-way branch.
    assert b.text_offsets() == sorted(synth.b_sites)
    # The branch names target 41 twice; the duplicate must not double the site.
    assert len(b.sites) == len(synth.b_sites)


def test_walker_records_pointer_sites(synth):
    scripts = read_scripts(synth.rom)
    for script, expected in zip(scripts, (synth.a_sites, synth.b_sites)):
        found = {site.text_at: site.pointer_at for site in script.sites}
        assert found == {at: ptr for at, (ptr, _) in expected.items()}


def test_read_strings_returns_text_and_byte_length(synth):
    charset = load_japanese()
    scripts = read_scripts(synth.rom)

    assert read_strings(scripts[0], charset) == {
        25: ("アイウエオカキ<END>", 8),
        33: ("サシス<END>", 4),
    }
    assert read_strings(scripts[1], charset) == {
        49: ("カキク<END>", 4),
        53: ("タチツテ<END>", 5),
        58: ("ナニ<END>", 3),
        61: ("ハヒフ", 4),   # 0x00-terminated: no tag, terminator still counted
    }
