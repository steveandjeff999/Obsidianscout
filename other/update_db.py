from app import create_app, db
from sqlalchemy import Column, String
from app.models import Event

def update_database():
    """Add code column to Event table if it doesn't exist"""
    app = create_app()
    with app.app_context():
        # Check if we need to add the code column
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('event')]
        
        if 'code' not in columns:
            print("Adding 'code' column to Event table...")
            # Add the column to the table
            db.engine.execute('ALTER TABLE event ADD COLUMN code VARCHAR(20) UNIQUE')
            print("Column added successfully!")
        else:
            print("'code' column already exists in Event table")
            
        print("Database update complete!")

if __name__ == "__main__":
    update_database()