from core.model import Model
from core.field import Integer
from core.field import Text


class CrimeSlot(Model):

    table_name = "crime_slots"

    slot_key = Text(primary=True)

    crime_id = Integer()

    crime_name = Text()

    status = Text()

    difficulty = Integer()

    slot_position = Text()

    user_id = Integer()

    user_name = Text()

    checkpoint_pass_rate = Integer()

    required_item_id = Integer()

    required_item_name = Text()

    item_is_available = Integer()

    item_is_reusable = Integer()

    updated_at = Integer()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )


class CrimeCprStat(Model):

    table_name = "crime_cpr_stats"

    cpr_key = Text(primary=True)

    user_id = Integer()

    user_name = Text()

    crime_level = Integer()

    position = Text()

    cpr = Integer()

    best_cpr = Integer()

    updated_at = Integer()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )


class CrimeMember(Model):

    table_name = "crime_members"

    user_id = Integer(primary=True)

    user_name = Text()

    position = Text()

    is_in_oc = Integer()

    status_state = Text()

    status_description = Text()

    last_action = Integer()

    updated_at = Integer()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )


class CrimeSlotHistory(Model):

    table_name = "crime_slot_history"

    history_key = Text(primary=True)

    crime_id = Integer()

    crime_name = Text()

    status = Text()

    difficulty = Integer()

    slot_position = Text()

    user_id = Integer()

    user_name = Text()

    checkpoint_pass_rate = Integer()

    required_item_id = Integer()

    required_item_name = Text()

    updated_at = Integer()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )


class CrimeDelayEvent(Model):

    table_name = "crime_delay_events"

    delay_id = Integer(primary=True)

    crime_id = Integer()

    crime_name = Text()

    difficulty = Integer()

    status = Text()

    started_at = Integer()

    last_seen_at = Integer()

    resolved_at = Integer()

    duration_seconds = Integer()

    resolution = Text()

    delaying_user_ids = Text()

    delaying_user_names = Text()

    delaying_states = Text()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )


class CrimeDelayNotification(Model):

    table_name = "crime_delay_notifications"

    notification_id = Integer(primary=True)

    event_type = Text()

    delay_id = Integer()

    crime_id = Integer()

    crime_name = Text()

    difficulty = Integer()

    started_at = Integer()

    resolved_at = Integer()

    duration_seconds = Integer()

    delaying_user_ids = Text()

    delaying_user_names = Text()

    delaying_states = Text()

    resolution = Text()

    created_at = Integer()

    discord_posted_at = Integer()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )
