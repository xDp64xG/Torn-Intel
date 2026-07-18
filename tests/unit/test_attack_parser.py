import json
import pytest
from pathlib import Path
from modules.attacks.parser import AttackParser
from models.attack import Attack


@pytest.fixture
def attack_data():
    """Load attack fixture from JSON"""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "attacks.json"
    data = json.loads(fixture_path.read_text())
    return data["attacks"][0]  # Get first attack


def test_parser_reads_attack(attack_data):
    """Test that parser correctly parses real attack data"""
    parsed = AttackParser.parse(attack_data)
    
    assert isinstance(parsed, Attack)
    assert parsed.attack_id == attack_data["id"]
    assert parsed.attacker_id == attack_data["attacker"]["id"]
    assert parsed.defender_id == attack_data["defender"]["id"]
    assert parsed.result == attack_data["result"]
    assert parsed.chain == attack_data["chain"]


def test_parser_handles_nested_objects(attack_data):
    """Test that parser correctly flattens nested attacker/defender objects"""
    parsed = AttackParser.parse(attack_data)
    
    # Check attacker flattening
    assert parsed.attacker_name == attack_data["attacker"]["name"]
    assert parsed.attacker_level == attack_data["attacker"]["level"]
    assert parsed.attacker_faction_id == attack_data["attacker"]["faction"]["id"]
    assert parsed.attacker_faction_name == attack_data["attacker"]["faction"]["name"]
    
    # Check defender flattening
    assert parsed.defender_name == attack_data["defender"]["name"]
    assert parsed.defender_level == attack_data["defender"]["level"]
    assert parsed.defender_faction_id == attack_data["defender"]["faction"]["id"]
    assert parsed.defender_faction_name == attack_data["defender"]["faction"]["name"]


def test_parser_handles_modifiers(attack_data):
    """Test that parser correctly extracts modifiers"""
    parsed = AttackParser.parse(attack_data)
    
    modifiers = attack_data.get("modifiers", {})
    assert parsed.modifier_fair_fight == modifiers.get("fair_fight", 1)
    assert parsed.modifier_war == modifiers.get("war", 1)
    assert parsed.modifier_retaliation == modifiers.get("retaliation", 1)
    assert parsed.modifier_group == modifiers.get("group", 1)
    assert parsed.modifier_overseas == modifiers.get("overseas", 1)
    assert parsed.modifier_chain == modifiers.get("chain", 1)
    assert parsed.modifier_warlord == modifiers.get("warlord", 1)