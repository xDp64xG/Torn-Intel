import json

from core.model import Model
from core.field import Integer
from core.field import Real
from core.field import Text


class Revive(Model):

    table_name = "revives"

    revive_id = Integer(primary=True)
    timestamp = Integer()
    result = Text()
    chance = Real()
    reviver_id = Integer()
    reviver_name = Text()
    reviver_faction_id = Integer()
    reviver_faction_name = Text()
    target_id = Integer()
    target_name = Text()
    target_faction_id = Integer()
    target_faction_name = Text()
    target_hospital_reason = Text()
    target_early_discharge = Integer()
    target_last_action_status = Text()
    target_last_action_timestamp = Integer()
    raw_payload = Text()

    def __init__(self, **kwargs):

        for field in self.column_names():
            setattr(self, field, kwargs.get(field))


class ReviveRequest(Model):

    table_name = "revive_requests"

    request_id = Text(primary=True)
    requested_timestamp = Integer()
    created_at = Integer()
    requester_id = Integer()
    requester_name = Text()
    target_id = Integer()
    target_name = Text()
    source = Text()
    status = Text()
    fulfilled_revive_id = Integer()
    revived_timestamp = Integer()
    fulfilled_at = Integer()
    fulfilled_by_id = Integer()
    fulfilled_by_name = Text()
    matched_at = Integer()
    notified_at = Integer()
    notes = Text()
    raw_payload = Text()

    def __init__(self, **kwargs):

        payload = kwargs.get("raw_payload")
        if payload is not None and not isinstance(payload, str):
            kwargs["raw_payload"] = json.dumps(payload)

        for field in self.column_names():
            setattr(self, field, kwargs.get(field))