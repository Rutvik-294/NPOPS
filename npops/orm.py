"""NPOPS ORM — a tiny ActiveRecord-style layer over sqlite3.

Table classes declare columns declaratively; the metaclass builds DDL,
and instances get attribute<->row mapping, save/delete, and a query API
with parameterized SQL (no string interpolation of values).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager


class Database:
    _local = threading.local()

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            import os
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def execute(self, sql: str, params=()):
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def create_all(self, *models):
        for m in models:
            self.conn.executescript(m.ddl())
        self.conn.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        r = self.conn.execute(sql, params).fetchone()
        return dict(r) if r else None


_db: Database | None = None


def set_db(db: Database):
    global _db
    _db = db
    db._lock = db._lock  # no-op, keep API stable


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialized; call set_db()")
    return _db


FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SQL_RESERVED = {"order", "group", "index", "table", "check", "values", "unique"}


class Column:
    def __init__(self, sql_type: str = "TEXT", pk: bool = False,
                 null: bool = True, unique: bool = False, default=None,
                 index: bool = False, fk: tuple | None = None):
        self.sql_type = sql_type
        self.pk = pk
        self.null = null
        self.unique = unique
        self.default = default
        self.index = index
        self.fk = fk  # (table, column)


class ModelMeta(type):
    def __new__(mcs, name, bases, ns):
        cls = super().__new__(mcs, name, bases, ns)
        if ns.get("abstract") or name == "Model":
            return cls
        table = ns.get("__tablename__", name.lower())
        cls.__tablename__ = table
        cols: dict[str, Column] = {}
        for k, v in ns.items():
            if isinstance(v, Column):
                if not FIELD_RE.match(k) or k in SQL_RESERVED:
                    raise ValueError(f"Illegal column name: {k}")
                cols[k] = v
        cls._columns = cols
        return cls


class Model(metaclass=ModelMeta):
    abstract = True

    def __init__(self, **kwargs):
        for name, col in self._columns.items():
            if name in kwargs:
                setattr(self, name, kwargs[name])
            elif col.default is not None:
                setattr(self, name,
                        col.default() if callable(col.default) else col.default)
            else:
                setattr(self, name, None)

    @classmethod
    def ddl(cls) -> str:
        parts, idx = [], []
        for name, col in cls._columns.items():
            decl = f"  {name} {col.sql_type}"
            if col.pk:
                decl += " PRIMARY KEY"
            if not col.null and not col.pk:
                decl += " NOT NULL"
            if col.unique:
                decl += " UNIQUE"
            if col.fk:
                decl += f" REFERENCES {col.fk[0]}({col.fk[1]})"
            if col.default is not None and not callable(col.default):
                decl += f" DEFAULT {col.default!r}"
            parts.append(decl)
            if col.index:
                idx.append(f"CREATE INDEX IF NOT EXISTS ix_{cls.__tablename__}_{name}"
                           f" ON {cls.__tablename__}({name});")
        return f"CREATE TABLE IF NOT EXISTS {cls.__tablename__} (\n" + \
            ",\n".join(parts) + "\n);\n" + "\n".join(idx)

    @classmethod
    def from_row(cls, row: dict):
        return cls(**row)

    @classmethod
    def get(cls, pk) -> "Model | None":
        pk_col = next(n for n, c in cls._columns.items() if c.pk)
        row = get_db().one(f"SELECT * FROM {cls.__tablename__} WHERE {pk_col}=?",
                           (pk,))
        return cls.from_row(row) if row else None

    @classmethod
    def all(cls, where: str = "", params=(), order: str = "",
            limit: int | None = None) -> list["Model"]:
        sql = f"SELECT * FROM {cls.__tablename__}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [cls.from_row(r) for r in get_db().query(sql, params)]

    @classmethod
    def count(cls, where: str = "", params=()) -> int:
        sql = f"SELECT COUNT(*) c FROM {cls.__tablename__}"
        if where:
            sql += f" WHERE {where}"
        return get_db().one(sql, params)["c"]

    def insert(self):
        db = get_db()
        names = list(self._columns)
        vals = [getattr(self, n) for n in names]
        if any(v is None for n, v in zip(names, vals) if self._columns[n].pk):
            names = [n for n in names if not self._columns[n].pk]
            vals = [getattr(self, n) for n in names]
        sql = (f"INSERT INTO {self.__tablename__} ({', '.join(names)}) "
               f"VALUES ({', '.join('?' for _ in names)})")
        with db.tx():
            cur = db.execute(sql, vals)
        pk_col = next(n for n, c in self._columns.items() if c.pk)
        if self._columns[pk_col].sql_type == "INTEGER":
            setattr(self, pk_col, cur.lastrowid)
        return self

    def update(self):
        db = get_db()
        pk_col = next(n for n, c in self._columns.items() if c.pk)
        names = [n for n in self._columns if n != pk_col]
        vals = [getattr(self, n) for n in names] + [getattr(self, pk_col)]
        sql = (f"UPDATE {self.__tablename__} SET "
               f"{', '.join(f'{n}=?' for n in names)} WHERE {pk_col}=?")
        with db.tx():
            db.execute(sql, vals)
        return self

    def save(self):
        pk_col = next(n for n, c in self._columns.items() if c.pk)
        if getattr(self, pk_col) is None:
            return self.insert()
        return self.update()

    def delete(self):
        db = get_db()
        pk_col = next(n for n, c in self._columns.items() if c.pk)
        with db.tx():
            db.execute(f"DELETE FROM {self.__tablename__} WHERE {pk_col}=?",
                       (getattr(self, pk_col),))

    def to_dict(self) -> dict:
        return {n: getattr(self, n) for n in self._columns}


class JsonColumn(Column):
    """A TEXT column transparently (de)serialized to Python objects."""
    pass


def _json_get(self, name):
    raw = getattr(self, f"_{name}", None)
    return json.loads(raw) if raw else None


def _json_set(self, name, value):
    setattr(self, f"_{name}", json.dumps(value))
