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
