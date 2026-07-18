import json

from models.attack import Attack


class AttackParser:

    @staticmethod
    def parse(data: dict) -> Attack:

        # Handle both v1 (flat fields) and v2 (nested objects) formats
        raw_attacker = data.get("attacker") or {}
        raw_defender = data.get("defender") or {}

        if raw_attacker:
            # V2 nested format
            attacker_id = raw_attacker.get("id")
            attacker_name = raw_attacker.get("name", "")
            attacker_level = raw_attacker.get("level")
            attacker_faction = raw_attacker.get("faction") or {}
            attacker_faction_id = attacker_faction.get("id")
            attacker_faction_name = attacker_faction.get("name", "")
        else:
            # V1 flat format
            attacker_id = data.get("attacker_id")
            attacker_name = data.get("attacker_name", "")
            attacker_level = data.get("attacker_level")
            attacker_faction_id = data.get("attacker_faction")
            attacker_faction_name = data.get("attacker_factionname", "")

        if raw_defender:
            # V2 nested format
            defender_id = raw_defender.get("id")
            defender_name = raw_defender.get("name", "")
            defender_level = raw_defender.get("level")
            defender_faction = raw_defender.get("faction") or {}
            defender_faction_id = defender_faction.get("id")
            defender_faction_name = defender_faction.get("name", "")
        else:
            # V1 flat format
            defender_id = data.get("defender_id")
            defender_name = data.get("defender_name", "")
            defender_level = data.get("defender_level")
            defender_faction_id = data.get("defender_faction")
            defender_faction_name = data.get("defender_factionname", "")

        modifiers = data.get("modifiers", {})

        # Handle both v1 (timestamp_started/ended) and v2 (started/ended) formats
        timestamp_started = data.get("started") or data.get("timestamp_started")
        timestamp_ended = data.get("ended") or data.get("timestamp_ended")

        return Attack(
            attack_id=data.get("id"),

            code=data.get("code", ""),

            timestamp_started=timestamp_started,
            timestamp_ended=timestamp_ended,

            attacker_id=attacker_id,
            attacker_name=attacker_name,
            attacker_level=attacker_level,
            attacker_faction_id=attacker_faction_id,
            attacker_faction_name=attacker_faction_name,

            defender_id=defender_id,
            defender_name=defender_name,
            defender_level=defender_level,
            defender_faction_id=defender_faction_id,
            defender_faction_name=defender_faction_name,

            result=data.get("result", ""),

            respect_gain=data.get("respect_gain", 0),
            respect_loss=data.get("respect_loss", 0),

            chain=data.get("chain", 0),

            is_interrupted=bool(data.get("is_interrupted")),
            is_stealthed=bool(data.get("stealthed") or data.get("is_stealthed")),
            is_raid=bool(data.get("raid") or data.get("is_raid")),
            is_ranked_war=bool(data.get("ranked_war") or data.get("is_ranked_war")),

            modifier_fair_fight=modifiers.get("fair_fight", 1),
            modifier_war=modifiers.get("war", 1),
            modifier_retaliation=modifiers.get("retaliation", 1),
            modifier_group=modifiers.get("group", 1),
            modifier_overseas=modifiers.get("overseas", 1),
            modifier_chain=modifiers.get("chain_bonus") or modifiers.get("chain", 1),
            modifier_warlord=modifiers.get("warlord_bonus") or modifiers.get("warlord", 1),

            finishing_hit_effects=json.dumps(
                data.get("finishing_hit_effects", [])
            ),
        )