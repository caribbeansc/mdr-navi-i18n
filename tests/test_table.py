"""Tests for navi/table.py: charset loading, encode/decode, layout metrics."""

import pytest

from navi.table import Charset, TableError, decode, encode, lines_of, visible_length

TBL = """\
# A tiny table in the same format as data/charset-latin.tbl.
01=A
02=B
03=C
09=,
13=a
17=b
50=[<3]
51=[note]
DB=
E040=語

GG=not hex, skipped
a line with no separator is skipped too
"""


@pytest.fixture
def charset(tmp_path):
    path = tmp_path / "charset-test.tbl"
    path.write_text(TBL, encoding="utf-8")
    return Charset.load(path)


# -- loading -------------------------------------------------------------


def test_load_reads_entries_and_takes_name_from_file(charset):
    assert charset.name == "charset-test"
    assert charset.decode[0x01] == "A"
    assert charset.encode["A"] == 0x01
    assert charset.decode[0x13] == "a"


def test_load_bare_db_means_space(charset):
    assert charset.decode[0xDB] == " "
    assert charset.encode[" "] == 0xDB


def test_load_two_byte_kanji_code(charset):
    assert charset.decode[0xE040] == "語"
    assert charset.encode["語"] == 0xE040


def test_load_skips_comments_and_malformed_lines(charset):
    # Neither the "GG=" line nor the separator-less line produced entries.
    assert "not hex, skipped" not in charset.encode
    assert len(charset.decode) == 10


def test_load_empty_table_raises(tmp_path):
    path = tmp_path / "empty.tbl"
    path.write_text("# nothing but comments\n", encoding="utf-8")
    with pytest.raises(TableError):
        Charset.load(path)


def test_multi_lists_spelled_tokens_longest_first(charset):
    assert set(charset.multi) == {"[<3]", "[note]"}
    assert charset.multi[0] == "[note]"  # longest first


# -- encode / decode -----------------------------------------------------


def test_round_trip_through_every_tag(charset):
    # Every simple tag and every argument tag; <END> terminates so it goes
    # last.  <CLEAR>, the other terminator, gets its own test below.
    text = (
        "AB<NL>a b<WAIT>[<3][note]語"
        "<DELAY:0102><SFX:03><FACE:04><FACE7:05>"
        "<YESNO><MUSIC><PLAYER><MEDABOT><X:E3>,C<END>"
    )
    data = encode(text, charset)
    back, end = decode(data, 0, charset)
    assert back == text
    assert end == len(data)


def test_round_trip_clear_terminates(charset):
    text = "AB<CLEAR>"
    data = encode(text, charset)
    back, end = decode(data, 0, charset)
    assert back == text
    assert end == len(data)
    # Anything after <CLEAR> belongs to the next string.
    back, end = decode(data + b"\x03\x00", 0, charset)
    assert back == text
    assert end == len(data)


def test_decode_stops_at_nul(charset):
    text, end = decode(b"\x01\x02\x00\x03", 0, charset)
    assert text == "AB"
    assert end == 3


def test_encode_kanji_takes_two_bytes(charset):
    assert encode("語", charset) == b"\xe0\x40"
    assert decode(b"\xe0\x40\x00", 0, charset) == ("語", 3)


def test_encode_space_via_db(charset):
    assert encode("a b", charset) == bytes([0x13, 0xDB, 0x17])


def test_encode_unknown_char_raises_naming_it(charset):
    with pytest.raises(TableError, match="'Q'"):
        encode("ABQ", charset)


def test_encode_unknown_tag_raises(charset):
    with pytest.raises(TableError, match="BOGUS"):
        encode("<BOGUS>", charset)


def test_encode_arg_tag_wants_exact_arg_length(charset):
    with pytest.raises(TableError, match="DELAY"):
        encode("<DELAY:01>", charset)  # needs two bytes, got one


def test_encode_malformed_tag_raises(charset):
    with pytest.raises(TableError, match="Malformed"):
        encode("<oops", charset)


# -- multi-character tokens ----------------------------------------------


def test_spelled_tokens_encode_to_one_byte(charset):
    assert encode("[<3]", charset) == b"\x50"
    assert encode("[note]", charset) == b"\x51"
    assert decode(b"\x50\x51\x00", 0, charset) == ("[<3][note]", 3)


def test_spelled_tokens_count_as_one_cell():
    assert visible_length("[<3]") == 1
    assert visible_length("[note]") == 1
    assert visible_length("A[<3]B[note]") == 4


# -- layout metrics ------------------------------------------------------


def test_visible_length_ignores_tags():
    assert visible_length("AB<NL>CD<DELAY:0102>E<END>") == 5
    assert visible_length("<FACE:01><WAIT>") == 0


def test_lines_of_splits_on_nl_wait_and_clear():
    assert lines_of("AB<NL>CD<WAIT>EF<CLEAR>GH") == ["AB", "CD", "EF", "GH"]


def test_lines_of_drops_non_breaking_tags():
    assert lines_of("A<FACE:01>B<NL>C<SFX:02>D") == ["AB", "CD"]


def test_lines_of_collapses_spelled_tokens():
    assert lines_of("[<3]<NL>x") == ["♥", "x"]
