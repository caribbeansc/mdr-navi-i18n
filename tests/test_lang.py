"""Tests for navi/lang.py: fingerprints, packs on disk, staleness."""

import pytest

from navi.lang import FINGERPRINT_LENGTH, Entry, Pack, available, fingerprint


# -- fingerprint ---------------------------------------------------------


def test_fingerprint_is_stable():
    # sha256 truncated: these values must never change between runs or
    # machines, or every pack's src fields would go stale at once.
    assert fingerprint("abc") == "ba7816bf8f01"
    assert fingerprint("こんにちは") == "125aeadf27b0"


def test_fingerprint_length_and_alphabet():
    fp = fingerprint("メダロット")
    assert len(fp) == FINGERPRINT_LENGTH == 12
    assert set(fp) <= set("0123456789abcdef")


def test_fingerprint_distinguishes_texts():
    assert fingerprint("A") != fingerprint("B")
    assert fingerprint("") != fingerprint(" ")


# -- disk round trip -----------------------------------------------------


@pytest.fixture
def pack_dir(tmp_path):
    pack = Pack(
        code="es",
        name="Español",
        english_name="Spanish",
        credits=["JC"],
        validation={"max_row": 32},
        path=tmp_path / "es",
    )
    pack.save_meta()
    pack.save_part(
        "strings",
        [
            Entry(key="str:0000AA", src=fingerprint("こんにちは"), t="Hola"),
            Entry(key="str:0000BB", src=fingerprint("さようなら"), t="Adiós"),
        ],
    )
    pack.save_part(
        "script/0001",
        [Entry(key="script:0001:0004", src=fingerprint("メダロット"), t="Medabot")],
    )
    return tmp_path


def test_pack_round_trip(pack_dir):
    pack = Pack.load("es", root=pack_dir)
    assert pack.code == "es"
    assert pack.name == "Español"
    assert pack.english_name == "Spanish"
    assert pack.credits == ["JC"]
    assert pack.validation == {"max_row": 32}
    assert set(pack.entries) == {"str:0000AA", "str:0000BB", "script:0001:0004"}
    assert pack.get("str:0000AA") == Entry(
        key="str:0000AA", src=fingerprint("こんにちは"), t="Hola"
    )
    assert pack.get("script:0001:0004").t == "Medabot"
    assert len(pack) == 3  # every entry has a translation


def test_pack_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Pack.load("nope", root=tmp_path)


def test_available_lists_only_real_packs(pack_dir):
    (pack_dir / "not-a-pack").mkdir()
    assert available(root=pack_dir) == ["es"]


def test_save_part_without_directory_raises():
    with pytest.raises(ValueError):
        Pack(code="es").save_part("strings", [])


# -- translation_for -----------------------------------------------------


def make_pack(*entries: Entry) -> Pack:
    return Pack(code="es", entries={e.key: e for e in entries})


def test_translation_for_returns_current_translation():
    pack = make_pack(Entry(key="k", src=fingerprint("こんにちは"), t="Hola"))
    assert pack.translation_for("k", "こんにちは") == "Hola"


def test_translation_for_refuses_stale_source():
    pack = make_pack(Entry(key="k", src=fingerprint("こんにちは"), t="Hola"))
    assert pack.translation_for("k", "こんばんは") is None


def test_translation_for_refuses_empty_translation():
    pack = make_pack(Entry(key="k", src=fingerprint("こんにちは"), t=""))
    assert pack.translation_for("k", "こんにちは") is None


def test_translation_for_unknown_key_is_none():
    assert make_pack().translation_for("k", "こんにちは") is None


def test_translation_for_without_fingerprint_trusts_the_entry():
    pack = make_pack(Entry(key="k", src="", t="Hola"))
    assert pack.translation_for("k", "anything at all") == "Hola"


# -- stale ---------------------------------------------------------------


def test_stale_lists_changed_and_vanished_keys():
    pack = make_pack(
        Entry(key="b:changed", src=fingerprint("old text"), t="x"),
        Entry(key="c:current", src=fingerprint("same text"), t="y"),
        Entry(key="a:vanished", src=fingerprint("gone"), t="z"),
    )
    sources = {
        "b:changed": "new text",
        "c:current": "same text",
        # a:vanished has no source any more
    }
    assert pack.stale(sources) == ["a:vanished", "b:changed"]


def test_stale_ignores_entries_without_fingerprint():
    pack = make_pack(Entry(key="k", src="", t="Hola"))
    assert pack.stale({"k": "totally different"}) == []
    # ... unless the source line is gone entirely.
    assert pack.stale({}) == ["k"]
