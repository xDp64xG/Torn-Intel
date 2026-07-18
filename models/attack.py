from core.model import Model
from core.field import Integer
from core.field import Real
from core.field import Text
from core.field import Boolean


class Attack(Model):

    table_name = "attacks"

    attack_id = Integer(primary=True)

    code = Text()

    timestamp_started = Integer()

    timestamp_ended = Integer()

    attacker_id = Integer()

    attacker_name = Text()

    attacker_level = Integer()

    attacker_faction_id = Integer()

    attacker_faction_name = Text()

    defender_id = Integer()

    defender_name = Text()

    defender_level = Integer()

    defender_faction_id = Integer()

    defender_faction_name = Text()

    result = Text()

    respect_gain = Real()

    respect_loss = Real()

    chain = Integer()

    is_interrupted = Boolean()

    is_stealthed = Boolean()

    is_raid = Boolean()

    is_ranked_war = Boolean()

    modifier_fair_fight = Real()

    modifier_war = Real()

    modifier_retaliation = Real()

    modifier_group = Real()

    modifier_overseas = Real()

    modifier_chain = Real()

    modifier_warlord = Real()

    finishing_hit_effects = Text()

    def __init__(self, **kwargs):

        for field in self.column_names():

            setattr(
                self,
                field,
                kwargs.get(field)
            )