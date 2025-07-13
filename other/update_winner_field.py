from app import create_app, db
from sqlalchemy import text

def update_database():
    """Add winner column to Match table if it doesn't exist"""
    app = create_app()
    with app.app_context():
        # Check if we need to add the winner column
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('match')]
        
        if 'winner' not in columns:
            print("Adding 'winner' column to Match table...")
            # Add the column to the table - use the newer SQLAlchemy approach
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE match ADD COLUMN winner VARCHAR(10)'))
                conn.commit()
            print("Column added successfully!")
        else:
            print("'winner' column already exists in Match table")
            
        print("Database update complete!")

if __name__ == "__main__":
    update_database()