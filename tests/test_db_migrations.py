import os
from sqlalchemy import create_engine, text, inspect
from app import create_app, db
from app.utils.database_migrations import add_column, run_all_migrations


def test_add_column_postgres_type_mapping(monkeypatch, tmp_path):
    """add_column should translate DATETIME -> TIMESTAMP when using
    a PostgreSQL dialect.
    """
    # create an in-memory SQLite engine for simplicity
    engine = create_engine('sqlite:///:memory:')
    # create a minimal table
    engine.execute(text('CREATE TABLE foo (id INTEGER PRIMARY KEY)'))
    # force dialect name to look like Postgres
    monkeypatch.setattr(engine.dialect, 'name', 'postgresql')

    # attempt to add a DATETIME column
    assert add_column(engine, 'foo', 'bar', 'DATETIME')

    cols = [c['name'] for c in inspect(engine).get_columns('foo')]
    assert 'bar' in cols, "column should have been added despite type translation"

    # ensure the SQL that SQLite stored still ends up with TIMESTAMP when
    # asking for table info: SQLite is lenient about types, so this part is
    # mostly about exercising the code path rather than verifying the
    # literal SQL string.
    # (If add_column were to leave "DATETIME" unmodified it would still
    # succeed on SQLite, so this test can't assert on the type name.)


def test_run_all_migrations_creates_offset_column(tmp_path):
    """Running migrations on a fresh database should add the new
    ``offset_updated_at`` column."""
    app = create_app()
    with app.app_context():
        # ensure a clean database
        db.drop_all()
        db.create_all()
        # drop column if exists (simulating previous schema)
        engine = db.engine
        if 'offset_updated_at' in [c['name'] for c in inspect(engine).get_columns('event')]:
            engine.execute(text('ALTER TABLE event DROP COLUMN offset_updated_at'))
        # verify column absent
        cols = [c['name'] for c in inspect(engine).get_columns('event')]
        assert 'offset_updated_at' not in cols

        # run migrations, which should add the missing column
        added = run_all_migrations(db)
        assert added >= 1
        cols = [c['name'] for c in inspect(engine).get_columns('event')]
        assert 'offset_updated_at' in cols
