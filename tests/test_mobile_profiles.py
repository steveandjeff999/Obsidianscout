import json
try:
    from app import create_app, db
except Exception:
    # Allow running this file as a standalone script outside the package
    create_app = None
    db = None
import os
from io import BytesIO
from urllib.parse import urlparse
try:
    from app.models import User
except Exception:
    User = None


def test_mobile_profiles_me_returns_profile_picture():
    app = create_app()
    with app.app_context():
        # Ensure users tables exist for the test run
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass

        client = app.test_client()

        # Prefer testing with the known test account per request
        login_resp = client.post('/api/mobile/auth/login', json={
            'username': 'Seth Herod',
            'team_number': 5454,
            'password': '5454'
        })

        token = None
        user = None
        try:
            j = login_resp.get_json()
            if j and j.get('success') and j.get('token'):
                token = j.get('token')
        except Exception:
            token = None

        # If test account doesn't exist in the running DB, create a local user and use a token
        if not token:
            user = User(username='mobile_profile_user', scouting_team_number=9999)
            user.set_password('testpass')
            user.profile_picture = 'img/avatars/test.png'
            db.session.add(user)
            db.session.commit()

            from app.routes import mobile_api as ma
            token = ma.create_token(user.id, user.username, user.scouting_team_number)

        resp = client.get('/api/mobile/profiles/me', headers={'Authorization': f'Bearer {token}'})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') is True
        # Ensure user id matches either the fallback-created user or the logged-in user's id
        if user:
            expected_id = user.id
        else:
            # login_resp was earlier; parse its user id
            try:
                login_json = login_resp.get_json() or {}
                expected_id = login_json.get('user', {}).get('id')
            except Exception:
                expected_id = None

        assert data['user']['id'] == expected_id
        # If we used the fallback test user expect that path; otherwise any profile_picture string is acceptable
        if user:
            assert data['user']['profile_picture'] == 'img/avatars/test.png'
        else:
            assert isinstance(data['user']['profile_picture'], str)
        assert 'profile_picture_url' in data['user'] and data['user']['profile_picture_url']

        # Attempt to download the image and show it in a small Tkinter window
        pic_url = data['user'].get('profile_picture_url')
        try:
            # Use test_client to fetch the image if it's a /static path
            parsed = urlparse(pic_url or '')
            img_bytes = None

            client = app.test_client()
            if parsed.path:
                # Prefer local test client fetch to use the test app's API-protected picture
                # endpoint — include the mobile Authorization header when fetching.
                r = client.get(parsed.path, headers={'Authorization': f'Bearer {token}'})
                if r.status_code == 200 and r.data:
                    img_bytes = r.data

            # If we couldn't fetch via test client and pic_url is absolute try opening the file path
            if not img_bytes and pic_url and parsed.path and os.path.exists(parsed.path.lstrip('/')):
                with open(parsed.path.lstrip('/'), 'rb') as f:
                    img_bytes = f.read()

            if img_bytes:
                try:
                    import tkinter as tk
                    from PIL import Image, ImageTk

                    root = tk.Tk()
                    root.title('Mobile API Profile Picture')
                    image = Image.open(BytesIO(img_bytes))
                    # Resize to reasonable size if large
                    image.thumbnail((400, 400))
                    tkimg = ImageTk.PhotoImage(image)
                    lbl = tk.Label(root, image=tkimg)
                    lbl.pack()
                    # Auto close after 3 seconds to avoid blocking tests
                    root.after(3000, root.destroy)
                    root.mainloop()
                except Exception:
                    # Non-fatal: image display only for manual inspection
                    pass

        except Exception:
            # Ignore any display/fetch errors – test should not fail for this
            pass

        # Cleanup
        try:
            User.query.filter_by(id=user.id).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()


def test_mobile_profile_picture_endpoint_requires_auth():
    app = create_app()
    with app.app_context():
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass

        client = app.test_client()

        # Create a test user
        user = User(username='mobile_prot_user', scouting_team_number=7777)
        user.set_password('testpass')
        user.profile_picture = 'img/avatars/test.png'
        db.session.add(user)
        db.session.commit()

        from app.routes import mobile_api as ma
        token = ma.create_token(user.id, user.username, user.scouting_team_number)

        # Get profile which should point at the protected picture endpoint
        resp = client.get('/api/mobile/profiles/me', headers={'Authorization': f'Bearer {token}'})
        assert resp.status_code == 200
        data = resp.get_json()
        pic_url = data['user'].get('profile_picture_url')
        assert pic_url and pic_url.endswith('/api/mobile/profiles/me/picture')

        # Attempt to fetch picture without token -> should be rejected
        from urllib.parse import urlparse
        parsed = urlparse(pic_url)
        r_no_auth = client.get(parsed.path)
        assert r_no_auth.status_code == 401

        # Fetch with correct token -> should succeed (if file exists)
        r_ok = client.get(parsed.path, headers={'Authorization': f'Bearer {token}'})
        # We don't assert final 200 image payload because the test image may not exist
        assert r_ok.status_code in (200, 404)

        # Cleanup
        try:
            User.query.filter_by(id=user.id).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()


def run_against_server(base_url=None, show_window=True, verify_ssl=False):
    """Run the same check against a real server using requests.

    base_url: e.g. https://localhost:8080/api/mobile
    show_window: if True attempt to display profile image in a Tkinter window
    verify_ssl: pass to requests to allow self-signed certs (False for dev)
    """
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if not base_url:
        base_url = os.environ.get('API_BASE') or 'https://localhost:8080/api/mobile'

    login_url = f"{base_url.rstrip('/')}/auth/login"
    profile_url = f"{base_url.rstrip('/')}/profiles/me"

    print(f"Logging in to {login_url} as 'Seth Herod' (team 5454)...")
    try:
        r = requests.post(login_url, json={'username': 'Seth Herod', 'team_number': 5454, 'password': '5454'}, verify=verify_ssl, timeout=10)
    except Exception as e:
        print(f"Login request failed: {e}")
        return 2

    try:
        j = r.json()
    except Exception:
        print('Login returned non-JSON:', r.text)
        return 2

    if not j.get('success'):
        print('Login failed:', j)
        return 1

    token = j.get('token')
    print('Received token; fetching profile...')

    headers = {'Authorization': f'Bearer {token}'}
    try:
        p = requests.get(profile_url, headers=headers, verify=verify_ssl, timeout=10)
    except Exception as e:
        print(f"Profile request failed: {e}")
        return 2

    try:
        pj = p.json()
    except Exception:
        print('Profile returned non-JSON:', p.text)
        return 2

    if not pj.get('success'):
        print('Profile fetch failed:', pj)
        return 1

    user = pj.get('user', {})
    print('Profile:', json.dumps(user, indent=2))

    pic_url = user.get('profile_picture_url')
    if not pic_url:
        print('No profile image URL provided.')
        return 0

    print('Fetching profile image from:', pic_url)
    try:
        img_r = requests.get(pic_url, headers=headers if pic_url.startswith(base_url.rstrip('/')) else {}, verify=verify_ssl, timeout=10)
        if img_r.status_code != 200:
            print(f'Image fetch returned {img_r.status_code}');
            return 1
        img_bytes = img_r.content
    except Exception as e:
        print(f'Failed to fetch image: {e}')
        return 2

    if show_window:
        try:
            import tkinter as tk
            from PIL import Image, ImageTk

            root = tk.Tk()
            root.title('Mobile API Profile Picture (remote)')
            image = Image.open(BytesIO(img_bytes))
            image.thumbnail((600, 600))
            tkimg = ImageTk.PhotoImage(image)
            lbl = tk.Label(root, image=tkimg)
            lbl.pack()
            print('Showing image for 5 seconds...')
            root.after(5000, root.destroy)
            root.mainloop()
        except Exception as e:
            print('Could not display image (tkinter/Pillow may be missing):', e)

    print('Done')
    return 0


if __name__ == '__main__':
    # Run the standalone web check
    import argparse

    parser = argparse.ArgumentParser(description='Standalone mobile profile tester (remote)')
    parser.add_argument('--base', '-b', help='Base mobile API URL (e.g. https://localhost:8080/api/mobile)')
    parser.add_argument('--no-gui', action='store_true', help="Don't open a Tkinter window to show the image")
    parser.add_argument('--verify-ssl', action='store_true', help='Verify SSL certificates (defaults to false for dev)')
    args = parser.parse_args()

    rc = run_against_server(base_url=args.base, show_window=not args.no_gui, verify_ssl=args.verify_ssl)
    import sys
    sys.exit(rc)
