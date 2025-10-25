"""
Standalone notification daemon.

Run this as a separate process (system service or supervised background job) to
ensure notifications are scheduled and processed even if the web server is not
serving requests or users are not visiting the site.

Example (PowerShell):
& .\.venv\Scripts\Activate.ps1; python .\scripts\notification_daemon.py

This runs the existing notification worker loop in the foreground. It's a simple
way to guarantee the scheduler runs independently of web requests.
"""
import signal
import sys
from app import create_app
from app.utils.notification_worker import notification_worker


def main():
    app = create_app()

    # Run the notification worker loop in the main thread so the process stays alive.
    # This function will not return as it contains an infinite loop.
    try:
        print("Starting standalone notification daemon...")
        notification_worker(app)
    except KeyboardInterrupt:
        print("Notification daemon interrupted, exiting")
        sys.exit(0)


if __name__ == '__main__':
    main()
