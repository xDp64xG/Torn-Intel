"""
core/field.py
"""


class Field:

    def __init__(
        self,
        sql_type,
        primary=False,
        nullable=True,
        default=None
    ):

        self.sql_type = sql_type
        self.primary = primary
        self.nullable = nullable
        self.default = default

    def build(self, name):

        sql = f"{name} {self.sql_type}"

        if self.primary:
            sql += " PRIMARY KEY"

        if not self.nullable:
            sql += " NOT NULL"

        if self.default is not None:
            sql += f" DEFAULT {repr(self.default)}"

        return sql
class Integer(Field):

    def __init__(self, **kwargs):
        super().__init__("INTEGER", **kwargs)


class Real(Field):

    def __init__(self, **kwargs):
        super().__init__("REAL", **kwargs)


class Text(Field):

    def __init__(self, **kwargs):
        super().__init__("TEXT", **kwargs)


class Boolean(Field):

    def __init__(self, **kwargs):
        super().__init__("INTEGER", **kwargs)