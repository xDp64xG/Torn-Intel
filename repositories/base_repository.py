from core.query import Query


class Repository:

    def __init__(self, database, model):

        self.db = database
        self.model = model
        self.table = model.table_name

    ####################################################

    def query(self):

        return Query(
            self.db,
            self.table
        )

    ####################################################

    def all(self):

        return self.query().all()

    ####################################################

    def first(self):

        return self.query().first()

    ####################################################

    def where(self, column, value):

        return self.query().where(column, value)

    ####################################################

    def count(self):

        rows = self.db.select(
            f"SELECT COUNT(*) total FROM {self.table}"
        )

        return rows[0]["total"]
    

    ####################################################

    def insert(self, model):

        self.db.insert(
            self.table,
            model.to_dict()
        )