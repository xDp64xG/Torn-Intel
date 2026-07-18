from modules.armoury.parser import ArmouryParser


def test_parse_loaned_to_player_tracks_recipient_holder():
    event = {
        "timestamp": 1784300000,
        "news": '<a href="profiles.php?XID=111">Quartermaster</a> loaned 2x DSLR Camera to <a href="profiles.php?XID=222">Decsann</a> from the faction armory',
    }

    parsed = ArmouryParser.parse(9001, event)

    assert parsed is not None
    assert parsed["event_type"] == "loaned"
    assert parsed["player_id"] == 222
    assert parsed["player_name"] == "Decsann"
    assert parsed["item_name"] == "DSLR Camera"
    assert parsed["quantity"] == 2


def test_parse_retrieved_from_player_tracks_source_as_returned():
    event = {
        "timestamp": 1784300100,
        "news": '<a href="profiles.php?XID=333">JeffBezas</a> retrieved 1x DSLR Camera from <a href="profiles.php?XID=222">Decsann</a>',
    }

    parsed = ArmouryParser.parse(9002, event)

    assert parsed is not None
    assert parsed["event_type"] == "received"
    assert parsed["player_id"] == 222
    assert parsed["player_name"] == "Decsann"
    assert parsed["item_name"] == "DSLR Camera"
    assert parsed["quantity"] == 1
