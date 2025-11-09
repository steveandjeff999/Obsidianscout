"""
Simple helper to list User rows that match a given username.
Run from the project root inside the virtualenv:

& .\.venv\Scripts\python.exe tools\find_users_by_username.py "Seth Herod"

It will print user id, username, scouting_team_number, email, and roles.
"""
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/find_users_by_username.py \"Full Username\"")
        sys.exit(1)

    username = sys.argv[1]

    # Import the Flask app factory and User model
    try:
        from app import create_app, db
        from app.models import User
    except Exception as e:
        print("Error importing app or models:", e)
        sys.exit(2)

    app = create_app()

    with app.app_context():
        # Query users by exact username (case-sensitive as stored)
        users = User.query.filter_by(username=username).all()
        if not users:
            print(f"No users found with username: {username}")
            return

        print(f"Found {len(users)} user(s) with username '{username}':\n")
        for u in users:
            role_names = []
            try:
                role_names = [r.name for r in u.roles]
            except Exception:
                role_names = []
            print(f"id={u.id}  username={u.username!r}  scouting_team_number={u.scouting_team_number}  email={u.email!r}  roles={role_names}")

if __name__ == '__main__':
    main()
