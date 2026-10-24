from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def configure(database_url: str | None = None) -> Engine:
    """(Re)bind the engine. Tests call this with an in-memory URL."""
    global _engine, _SessionLocal
    url = database_url or get_settings().database_url
    kwargs: dict = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url == "sqlite://":
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - driver hook
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    return _engine or configure()


def create_all() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine())
    _relax_not_null("handoff_packets", "encounter_id")
    _add_missing_columns()


def _relax_not_null(table: str, column: str) -> None:
    """One-time rebuild for SQLite, which can't drop NOT NULL in place (pre-visit summaries may now exist
    before an appointment). Copies every row, keeps foreign keys pointing at the table name, and backs the
    database file up first. No-op when already nullable or on a fresh database."""
    import logging
    import shutil
    from datetime import datetime

    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateTable

    insp = inspect(engine())
    cols = {c["name"]: c for c in insp.get_columns(table)}
    if column not in cols or cols[column]["nullable"]:
        return
    db_path = engine().url.database
    if db_path and db_path != ":memory:":
        backup = db_path.removesuffix(".db") + f".backup-{datetime.now():%Y%m%d%H%M%S}.db"
        shutil.copy2(db_path, backup)
        logging.getLogger("curalink").warning("Upgrading %s.%s to nullable; backup saved to %s", table, column, backup)
    old = f"_{table}_pre_upgrade"
    keep = [c for c in cols if c in Base.metadata.tables[table].columns]
    with engine().connect() as conn:
        raw = conn.connection.driver_connection
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("PRAGMA legacy_alter_table=ON")  # don't rewrite other tables' references to the old name
        try:
            raw.execute("BEGIN")
            raw.execute(f'ALTER TABLE "{table}" RENAME TO "{old}"')
            raw.execute(str(CreateTable(Base.metadata.tables[table]).compile(engine())))
            names = ", ".join(f'"{c}"' for c in keep)
            raw.execute(f'INSERT INTO "{table}" ({names}) SELECT {names} FROM "{old}"')
            raw.execute(f'DROP TABLE "{old}"')
            raw.execute("COMMIT")
        except Exception:
            raw.execute("ROLLBACK")
            raise
        finally:
            raw.execute("PRAGMA legacy_alter_table=OFF")
            raw.execute("PRAGMA foreign_keys=ON")


def _add_missing_columns() -> None:
    """Additive-only upgrade for existing demo databases: add new columns as nullable.
    Never drops or rewrites data (code treats NULL as the column's default)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine())
    with engine().begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine().dialect)}'))
            for index in table.indexes:  # new indexes (e.g. the no-double-booking index) on existing tables
                index.create(conn, checkfirst=True)


def drop_all() -> None:
    from app import models  # noqa: F401

    Base.metadata.drop_all(engine())


def get_db() -> Iterator[Session]:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
