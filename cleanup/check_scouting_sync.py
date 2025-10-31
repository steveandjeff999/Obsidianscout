#!/usr/bin/env python3
"""Check scouting data sync status"""

from app import create_app, db

def main():
    app = create_app()
    with app.app_context():
        print('Checking scouting data sync...')
        
        # Check scouting_data table
        result = db.session.execute(db.text('SELECT COUNT(*) FROM scouting_data'))
        scouting_count = result.scalar()
        print(f'scouting_data entries: {scouting_count}')
        
        # Check pit_scouting_data table  
        result = db.session.execute(db.text('SELECT COUNT(*) FROM pit_scouting_data'))
        pit_count = result.scalar()
        print(f'pit_scouting_data entries: {pit_count}')
        
        # Check teams
        result = db.session.execute(db.text('SELECT COUNT(*) FROM team'))
        team_count = result.scalar()
        print(f'team entries: {team_count}')
        
        # Check matches
        result = db.session.execute(db.text('SELECT COUNT(*) FROM match'))
        match_count = result.scalar()
        print(f'match entries: {match_count}')
        
        # Verify Universal Sync is tracking these tables
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        important_tables = ['scouting_data', 'pit_scouting_data', 'team', 'match', 'user_roles']
        print('\nUniversal Sync table tracking:')
        for table in important_tables:
            tracked = table in tables
            status = " Tracked" if tracked else " Missing"
            print(f'  {table}: {status}')
            
        # Check if there are recent changes being tracked
        result = db.session.execute(db.text('SELECT COUNT(*) FROM database_changes WHERE timestamp > datetime("now", "-1 hour")'))
        recent_changes = result.scalar()
        print(f'\nRecent database changes (last hour): {recent_changes}')

if __name__ == '__main__':
    main()
