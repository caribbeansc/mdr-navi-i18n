"""Only the verified keys may read several boxes as one string.

Treating "text right after a segment" as a continuation looked reasonable and
broke two different things: an NPC's line was shown twice — the second time
with another character's portrait, because the neighbouring line belonged to
a different speaker — and, where the merged translation fitted in place, the
builder blanked the bytes of a line that was still live, which left a
player's save unfinishable.

So the merge is opt-in per key, and this keeps it that way: every other
string must report exactly the bytes its own box occupies.
"""

from navi.script import CHAIN_KEYS, read_scripts, read_strings
from navi.table import decode, load_japanese


def test_only_allowlisted_keys_are_read_as_chains(game_rom):
    charset = load_japanese()
    merged = []
    for script in read_scripts(game_rom):
        data = bytes(script.data)
        for text_at, (text, size) in read_strings(script, charset).items():
            single, single_end = decode(data, text_at, charset)
            # The reported SIZE is always the first box — that is what keeps
            # the builder from blanking a neighbour — so a chain shows up as
            # text that carries more than that one box.
            assert size == single_end - text_at, (
                f"script:{script.index:04d}:{text_at:04X} claims bytes beyond "
                "its own box; the builder would blank whatever follows")
            if text != single:
                merged.append(f"script:{script.index:04d}:{text_at:04X}")
    assert set(merged) <= CHAIN_KEYS, (
        "these keys merge boxes without being verified on screen: "
        f"{sorted(set(merged) - CHAIN_KEYS)}")


def test_every_allowlisted_key_exists_and_really_chains(game_rom):
    charset = load_japanese()
    seen = {}
    for script in read_scripts(game_rom):
        data = bytes(script.data)
        for text_at, (text, size) in read_strings(script, charset).items():
            key = f"script:{script.index:04d}:{text_at:04X}"
            if key in CHAIN_KEYS:
                single, _ = decode(data, text_at, charset)
                seen[key] = text != single
    missing = sorted(CHAIN_KEYS - set(seen))
    assert not missing, f"CHAIN_KEYS names lines this dump does not have: {missing}"
    flat = sorted(k for k, chained in seen.items() if not chained)
    assert not flat, f"listed as chains but only one box long: {flat}"
