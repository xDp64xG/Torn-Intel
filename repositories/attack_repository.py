"""
Repository for Attack model.
"""

from repositories.base_repository import Repository
from models.attack import Attack


class AttackRepository(Repository):

    def __init__(self, database):
        super().__init__(database, Attack)

    ##########################################################

    def exists(self, attack_id: int) -> bool:

        return (
            self.query()
            .where("attack_id", attack_id)
            .first()
            is not None
        )

    ##########################################################

    def latest_attack(self):

        rows = self.db.select("""
            SELECT attack_id
            FROM attacks
            ORDER BY attack_id DESC
            LIMIT 1
        """)

        if rows:
            return rows[0]["attack_id"]

        return None

    ##########################################################

    def by_chain(self, chain):

        return (
            self.query()
            .where("chain", chain)
            .all()
        )

    ##########################################################

    def by_attacker(self, attacker_id):

        return (
            self.query()
            .where("attacker_id", attacker_id)
            .all()
        )

    ##########################################################

    def by_defender(self, defender_id):

        return (
            self.query()
            .where("defender_id", defender_id)
            .all()
        )

    ##########################################################

    def by_result(self, result):

        return (
            self.query()
            .where("result", result)
            .all()
        )