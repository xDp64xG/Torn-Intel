from utils.logger import Logger


class SchemaBuilder:

    def __init__(self, database, logger):

        self.db = database
        self.logger = logger

    def create(self, model):

        columns = []

        for name, field in model.fields().items():

            columns.append(
                field.build(name)
            )

        sql = f"""
        CREATE TABLE IF NOT EXISTS
        {model.table_name}
        (
            {",".join(columns)}
        )
        """

        self.logger.info(
            f"Creating table {model.table_name}"
        )

        self.db.execute(sql)

        self.db.commit()