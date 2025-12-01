from sqlalchemy import create_engine, inspect

def main():
    engine = create_engine('sqlite:///instance/users.db')
    ins = inspect(engine)
    print('Tables:', ins.get_table_names())
    try:
        cols = ins.get_columns('user')
        print('Columns for `user` table:')
        for c in cols:
            print(' -', c['name'])
    except Exception as e:
        print('Error inspecting `user` table:', e)

if __name__ == '__main__':
    main()
