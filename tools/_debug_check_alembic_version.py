from sqlalchemy import create_engine, text

def check(dbpath):
    e = create_engine(f"sqlite:///instance/{dbpath}")
    with e.connect() as conn:
        res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"))
        print('alembic_version exists:', bool(res.fetchone()))
        try:
            rows = conn.execute(text('SELECT * FROM alembic_version')).fetchall()
            print('alembic rows:', rows)
        except Exception as ex:
            print('error reading alembic_version:', ex)

if __name__ == '__main__':
    check('users.db')
    check('misc.db')
    check('scouting.db')
    check('pages.db')
    check('apis.db')
    check('embeddings.db')
    check('instance.db')
