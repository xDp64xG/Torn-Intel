"""
modules/rankedwars/parser.py

Parse ranked war API responses into RankedWar models.

API response structure:
{
    "rankedwars": {
        "war_id": {
            "factions": {
                "faction_id": {
                    "name": "Faction Name",
                    "score": 5965,
                    "chain": 3  # chain number active during this war
                },
                ...
            },
            "war": {
                "start": 1781956800,
                "end": 1781969561,
                "target": 5800,
                "winner": 49431
            }
        },
        ...
    }
}

Flatten to: one row per war, storing our_faction info and opponent info separately.
"""

from models.rankedwar import RankedWar


def parse(data, our_faction_id=None, synced_at=None):
    """
    Parse ranked wars API response into RankedWar models.
    
    Args:
        data: API response dict {rankedwars: {war_id: {...}}}
        our_faction_id: Our faction ID (used to decide which is "our" vs "opponent")
        synced_at: Unix timestamp for when this was synced (defaults to now)
    
    Returns:
        List of RankedWar model instances.
    """
    
    import time
    
    if synced_at is None:
        synced_at = int(time.time())
    
    wars = []
    
    # Extract rankedwars dict if it exists
    rankedwars_dict = data.get("rankedwars", {})
    if not rankedwars_dict:
        # If no rankedwars key, assume data is the wars dict itself
        rankedwars_dict = data if isinstance(data, dict) else {}
    
    for war_id_str, war_data in rankedwars_dict.items():
        try:
            war_id = int(war_id_str)
        except (ValueError, TypeError):
            # Skip non-integer keys
            continue
        
        factions = war_data.get("factions", {})
        war_info = war_data.get("war", {})
        
        faction_ids = list(factions.keys())
        
        if len(faction_ids) != 2:
            # Malformed or incomplete war data
            continue
        
        faction1_id = int(faction_ids[0])
        faction2_id = int(faction_ids[1])
        
        faction1_data = factions[str(faction1_id)]
        faction2_data = factions[str(faction2_id)]
        
        war_start = war_info.get("start")
        war_end = war_info.get("end")
        war_target = war_info.get("target")
        war_winner = war_info.get("winner")
        
        # Determine which faction is "ours"
        if our_faction_id and faction1_id == our_faction_id:
            # Faction 1 is us
            our_f_id = faction1_id
            our_f_name = faction1_data.get("name")
            our_score = faction1_data.get("score", 0)
            our_chain = faction1_data.get("chain", 0)
            
            opp_f_id = faction2_id
            opp_f_name = faction2_data.get("name")
            opp_score = faction2_data.get("score", 0)
            opp_chain = faction2_data.get("chain", 0)
        
        elif our_faction_id and faction2_id == our_faction_id:
            # Faction 2 is us
            our_f_id = faction2_id
            our_f_name = faction2_data.get("name")
            our_score = faction2_data.get("score", 0)
            our_chain = faction2_data.get("chain", 0)
            
            opp_f_id = faction1_id
            opp_f_name = faction1_data.get("name")
            opp_score = faction1_data.get("score", 0)
            opp_chain = faction1_data.get("chain", 0)
        
        else:
            # our_faction_id not set or doesn't match, just use first as ours
            our_f_id = faction1_id
            our_f_name = faction1_data.get("name")
            our_score = faction1_data.get("score", 0)
            our_chain = faction1_data.get("chain", 0)
            
            opp_f_id = faction2_id
            opp_f_name = faction2_data.get("name")
            opp_score = faction2_data.get("score", 0)
            opp_chain = faction2_data.get("chain", 0)
        
        war = RankedWar(
            war_id=war_id,
            our_faction_id=our_f_id,
            our_faction_name=our_f_name,
            opponent_faction_id=opp_f_id,
            opponent_faction_name=opp_f_name,
            our_score=our_score,
            opponent_score=opp_score,
            our_chain=our_chain,
            opponent_chain=opp_chain,
            war_start=war_start,
            war_end=war_end,
            war_target=war_target,
            war_winner_id=war_winner,
            synced_at=synced_at,
        )
        
        wars.append(war)
    
    return wars
