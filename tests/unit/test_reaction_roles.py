from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.discord_bot_service import _normalize_emoji_key, _normalize_reaction_entry, _parse_reaction_pairs


def test_parse_reaction_pairs_reads_multiple_bindings():
    pairs = _parse_reaction_pairs("\U0001f52b=<@&111>, \U0001f48a => <@&222>\n<:loot:333444555>:987654321098765432")

    assert pairs == [
        ("\U0001f52b", "<@&111>"),
        ("\U0001f48a", "<@&222>"),
        ("<:loot:333444555>", "987654321098765432"),
    ]


def test_parse_reaction_pairs_flags_entries_without_a_role():
    assert _parse_reaction_pairs("\U0001f52b") == [("\U0001f52b", None)]


def test_normalize_emoji_key_matches_static_and_animated_custom_emoji():
    assert _normalize_emoji_key("<:loot:333>") == _normalize_emoji_key("<a:loot:333>") == "333"
    assert _normalize_emoji_key("\U0001f52b") == "\U0001f52b"


def test_normalize_reaction_entry_reads_modes_and_legacy_entries():
    assert _normalize_reaction_entry({"mode": "toggle", "bindings": {"333": {"role_id": 1}}}) == (
        "toggle",
        {"333": {"role_id": 1}},
    )
    assert _normalize_reaction_entry({"333": 1}) == ("keep", {"333": 1})
    assert _normalize_reaction_entry(None) == ("keep", {})
