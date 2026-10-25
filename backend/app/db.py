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
    url = normalize_url(database_url or get_settings().database_url)
    if _engine is not None:
        _engine.dispose()
    kwargs: dict = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url.startswith("postgresql"):
        # Serverless-friendly: few connections per instance, verified before use (Neon closes idle ones).
        kwargs = {"pool_size": 3, "max_overflow": 2, "pool_pre_ping": True, "pool_recycle": 300}
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


def normalize_url(url: str) -> str:
    """Neon/Vercel give postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg (v3) driver name."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def is_postgres() -> bool:
    return engine().url.get_backend_name() == "postgresql"


def engine() -> Engine:
    return _engine or configure()


def create_all() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine())
    _relax_not_null("handoff_packets", "encounter_id")
    _relax_not_null("absence_cases", "requested_start", "requested_end")
    _add_missing_columns()


def _relax_not_null(table: str, *columns: str) -> None:
    """One-time rebuild for SQLite, which can't drop NOT NULL in place (pre-visit summaries may now exist
    before an appointment). Copies every row, keeps foreign keys pointing at the table name, and backs the
    database file up first. No-op when already nullable or on a fresh database."""
    import logging
    import shutil
    from datetime import datetime

    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateTable

    if engine().url.get_backend_name() != "sqlite":
        return  # only SQLite needs a table rebuild to relax NOT NULL (fresh Postgres schemas are created nullable)
    insp = inspect(engine())
    cols = {c["name"]: c for c in insp.get_columns(table)}
    if all(c not in cols or cols[c]["nullable"] for c in columns):
        return
    db_path = engine().url.database
    if db_path and db_path != ":memory:":
        backup = db_path.removesuffix(".db") + f".backup-{datetime.now():%Y%m%d%H%M%S}.db"
        shutil.copy2(db_path, backup)
        logging.getLogger("curalink").warning("Upgrading %s.%s to nullable; backup saved to %s", table, ",".join(columns), backup)
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
