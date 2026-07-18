from core.field import Field


class Model:

    table_name = ""

    @classmethod
    def fields(cls):

        return {
            name: value
            for name, value in vars(cls).items()
            if isinstance(value, Field)
        }

    @classmethod
    def column_names(cls):

        return list(cls.fields().keys())

    def to_dict(self):

        return {
            column: getattr(self, column)
            for column in self.column_names()
        }