import os
from itsdangerous import URLSafeTimedSerializer
from flask import current_app


def _get_serializer():
    secret = current_app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY') or 'dev-secret'
    return URLSafeTimedSerializer(secret)


def generate_reset_token(email):
    s = _get_serializer()
    return s.dumps({'email': email})


def verify_reset_token(token, max_age=3600):
    s = _get_serializer()
    try:
        data = s.loads(token, max_age=max_age)
        return data.get('email')
    except Exception:
        return None
