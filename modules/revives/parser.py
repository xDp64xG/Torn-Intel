import json

from models.revive import Revive


class ReviveParser:

    @staticmethod
    def parse(data: dict) -> Revive:

        last_action = data.get("target_last_action") or {}

        return Revive(
            revive_id=int(data.get("id") or 0),
            timestamp=int(data.get("timestamp") or 0),
            result=data.get("result", ""),
            chance=float(data.get("chance") or 0),
            reviver_id=int(data.get("reviver_id") or 0),
            reviver_name=data.get("reviver_name", ""),
            reviver_faction_id=int(data.get("reviver_faction") or 0),
            reviver_faction_name=data.get("reviver_factionname") or "",
            target_id=int(data.get("target_id") or 0),
            target_name=data.get("target_name", ""),
            target_faction_id=int(data.get("target_faction") or 0),
            target_faction_name=data.get("target_factionname") or "",
            target_hospital_reason=data.get("target_hospital_reason") or "",
            target_early_discharge=int(data.get("target_early_discharge") or 0),
            target_last_action_status=last_action.get("status", "") if isinstance(last_action, dict) else "",
            target_last_action_timestamp=int(last_action.get("timestamp") or 0) if isinstance(last_action, dict) else 0,
            raw_payload=json.dumps(data),
        )