from app import create_app
from app.models import DatabaseChange
import sys

app = create_app()
with app.app_context():
    # Check what table names exist in database changes
    changes = DatabaseChange.query.limit(20).all()
    table_names = set()
    for change in changes:
        if hasattr(change, "table_name"):
            table_names.add(change.table_name)
        else:
            # Check if data contains table info
            try:
                import json
                data = json.loads(change.data) if isinstance(change.data, str) else change.data
                if isinstance(data, dict) and "table" in data:
                    table_names.add(data["table"])
            except:
                pass
    
    print(f"Found table names: {sorted(table_names)}")
    print(f"Total database changes: {DatabaseChange.query.count()}")
