from app import create_app, db
from sqlalchemy import text

def update_database():
    """Add team_event association table if it doesn't exist"""
    app = create_app()
    with app.app_context():
        # Check if the table already exists
        inspector = db.inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        if 'team_event' not in existing_tables:
            print("Creating 'team_event' association table...")
            # Create the team_event association table
            with db.engine.connect() as conn:
                conn.execute(text('''
                    CREATE TABLE team_event (
                        team_id INTEGER NOT NULL,
                        event_id INTEGER NOT NULL,
                        PRIMARY KEY (team_id, event_id),
                        FOREIGN KEY (team_id) REFERENCES team (id),
                        FOREIGN KEY (event_id) REFERENCES event (id)
                    )
                '''))
                conn.commit()
            print("Table created successfully!")
        else:
            print("'team_event' table already exists")
            
        print("Database update complete!")

if __name__ == "__main__":
    update_database()