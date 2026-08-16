"""Tests against the real cartridge dump, when one sits at the repo root."""

import pytest

import navi.catalog as catalog_mod

pytestmark = pytest.mark.game


@pytest.fixture(scope="module")
def game_catalog(game_rom):
    # Walks every script and pointer in the dump; takes about a minute.
    return catalog_mod.build(game_rom)


def test_release_identified_as_kuwagata(game_rom):
    assert game_rom.release.name == "Kuwagata"


def test_dump_matches_the_known_sha1(game_rom):
    assert game_rom.is_known_dump


def test_catalog_has_the_script_lines(game_catalog):
    assert len(game_catalog.of_kind("script")) >= 3000


def test_catalog_has_the_loose_strings(game_catalog):
    assert len(game_catalog.of_kind("loose")) >= 400
