"""
PostgreSQL-safe session helpers for Obsidian Scout.

When the app runs against SQLite with ``isolation_level=None`` (autocommit),
each statement is automatically committed.  Errors during flush/commit only
affect the single statement that failed — the session remains usable.

PostgreSQL uses standard ``READ COMMITTED`` transactions.  Once an error
occurs inside a PG transaction, **the entire transaction is poisoned** and
all subsequent SQL in that session will fail with
``InFailedSqlTransaction`` until a ``ROLLBACK`` is issued.

The functions in this module isolate risky operations inside SAVEPOINTs
(``session.begin_nested()``) so that a single failure doesn't destroy the
entire unit of work.

Usage example (replaces the bare ``try / except IntegrityError`` pattern):

    from app.utils.pg_session import safe_flush

    new_obj = MyModel(name="foo")
    db.session.add(new_obj)
    ok = safe_flush()
    if not ok:
        # The object was rolled back but the session is still usable
        existing = MyModel.query.filter_by(name="foo").first()
"""

from contextlib import contextmanager


def safe_flush(session=None):
    """Flush the session inside a SAVEPOINT.

    Returns ``True`` on success, ``False`` if an error occurred (the
    SAVEPOINT is automatically rolled back and the session stays usable).
    """
    if session is None:
        from app import db
        session = db.session

    nested = session.begin_nested()  # SAVEPOINT
    try:
        session.flush()
        nested.commit()  # Release the SAVEPOINT
        return True
    except Exception:
        # Roll back only the SAVEPOINT — outer transaction is unaffected
        try:
            nested.rollback()
        except Exception:
            pass
        return False


def safe_commit(session=None):
    """Commit the session, falling back to rollback on error.

    Returns ``True`` on success, ``False`` on failure (session is rolled
    back and remains usable for the next operation).
    """
    if session is None:
        from app import db
        session = db.session

    try:
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False


@contextmanager
def savepoint(session=None):
    """Context manager that wraps a block in a SAVEPOINT.

    On success the SAVEPOINT is released (committed).  On exception the
    SAVEPOINT is rolled back, the exception is suppressed, and the outer
    transaction / session remains usable.

    Usage::

        with savepoint():
            db.session.add(obj)
            db.session.flush()
        # If the above failed, session is still clean here
    """
    if session is None:
        from app import db
        session = db.session

    nested = session.begin_nested()
    try:
        yield nested
        # If caller didn't raise, commit the SAVEPOINT
        # (begin_nested auto-commits on __exit__ in SQLAlchemy 2.x, but
        # explicit commit is harmless and works on older versions too)
        try:
            nested.commit()
        except Exception:
            pass
    except Exception:
        # Roll back only the SAVEPOINT
        try:
            nested.rollback()
        except Exception:
            pass
