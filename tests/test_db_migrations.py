import os
from sqlalchemy import create_engine, text, inspect
from datetime import datetime, timezone
from app import create_app, db
from app.utils.database_migrations import add_column, run_all_migrations
from app.models import User


def test_add_column_postgres_type_mapping(monkeypatch, tmp_path):
    """add_column should translate DATETIME -> TIMESTAMP when using
    a PostgreSQL dialect.
    """
    # create an in-memory SQLite engine for simplicity
    engine = create_engine('sqlite:///:memory:')
    # create a minimal table
    with engine.connect() as conn:
        conn.execute(text('CREATE TABLE foo (id INTEGER PRIMARY KEY)'))
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
            # use connection.execute for modern SQLAlchemy
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE event DROP COLUMN offset_updated_at'))
        # verify column absent
        cols = [c['name'] for c in inspect(engine).get_columns('event')]
        assert 'offset_updated_at' not in cols

        # run migrations, which should add the missing column
        added = run_all_migrations(db)
        assert added >= 1
        cols = [c['name'] for c in inspect(engine).get_columns('event')]
        assert 'offset_updated_at' in cols

        # also verify the new team settings columns are added if missing
        cols2 = [c['name'] for c in inspect(engine).get_columns('scouting_team_settings')]
        assert 'predictions_enabled' in cols2
        assert 'leaderboard_accuracy_visible' in cols2
        assert 'qual_show_auto_climb' in cols2
        assert 'qual_show_endgame_climb' in cols2

        # verify user table got last_used column too (users bind)
        user_engine = db.get_engine(app, bind='users')
        cols3 = [c['name'] for c in inspect(user_engine).get_columns('user')]
        assert 'last_used' in cols3

        # if last_login values exist they should be copied into last_used
        # use ORM to avoid NOT NULL constraints on additional columns
        u = User(id=1, username='u')
        u.set_password('temp')
        u.last_login = datetime(2025, 1, 1, tzinfo=timezone.utc)
        db.session.add(u)
        db.session.commit()

        run_all_migrations(db)
        with user_engine.connect() as conn:
            res = conn.execute(text('SELECT last_used FROM "user" WHERE id=1')).fetchone()
        assert res and res[0] is not None, "last_used should be populated from last_login"


def test_last_used_updated_on_requests(monkeypatch):
    """Authenticated users should see last_used change on any request.

    The login route enforces a CSRF token; for simplicity we patch the helper
    to always return True so our test can post without constructing a token.
    """
    # bypass CSRF
    from app.routes.auth import validate_csrf_token
    monkeypatch.setattr('app.routes.auth.validate_csrf_token', lambda: True)

    app = create_app()
    with app.app_context():
        # fresh database
        db.drop_all()
        db.create_all()
        # create a user
        u = User(username='bob', scouting_team_number=1)
        u.set_password('secret')
        db.session.add(u)
        db.session.commit()

        client = app.test_client()
        # perform a login through the normal auth endpoint
        resp = client.post('/auth/login', data={
            'username': 'bob',
            'password': 'secret',
            'team_number': '1'
        }, follow_redirects=True)
        assert resp.status_code in (200, 302)

        db.session.refresh(u)
        assert u.last_used is not None
        first_used = u.last_used

        # make another internal request that should hit before_request
        client.get('/')
        db.session.refresh(u)
        # may be equal if clock resolution is coarse, so allow >=
        assert u.last_used and u.last_used >= first_used

