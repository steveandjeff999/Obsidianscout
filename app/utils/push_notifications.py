"""
Web Push Notification Service
Handles sending push notifications to user devices using Web Push Protocol
"""
import json
import base64
from pywebpush import webpush, WebPushException
from flask import current_app
from app import db
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization


def get_vapid_keys():
    """Get or generate VAPID keys for web push"""
    import os
    
    vapid_file = os.path.join(current_app.instance_path, 'vapid_keys.json')
    
    # Try to load existing keys
    if os.path.exists(vapid_file):
        try:
            with open(vapid_file, 'r') as f:
                keys = json.load(f)
                if 'public_key' in keys and 'private_key' in keys:
                    return keys
        except Exception as e:
            print(f"Error loading VAPID keys: {e}")
            # Delete corrupted file
            try:
                os.remove(vapid_file)
                print("Deleted corrupted VAPID keys file")
            except:
                pass
    
    # Generate new keys using py_vapid (the correct library for pywebpush)
    try:
        from py_vapid import Vapid
        
        # Generate new VAPID instance
        vapid = Vapid()
        vapid.generate_keys()
        
        # Get keys in the correct format
        # Private key as base64url string (for pywebpush)
        private_key = vapid.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        private_key_str = base64.urlsafe_b64encode(private_key).decode('utf-8').rstrip('=')
        
        # Public key as base64url string (for client and server)
        # Get raw public key bytes in X962 uncompressed point format
        public_key_bytes = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        public_key_b64 = base64.urlsafe_b64encode(public_key_bytes).decode('utf-8').rstrip('=')
        
        keys = {
            'public_key': public_key_b64,
            'private_key': private_key_str
        }
        
        # Save keys
        os.makedirs(os.path.dirname(vapid_file), exist_ok=True)
        with open(vapid_file, 'w') as f:
            json.dump(keys, f, indent=2)
        
        print("Generated new VAPID keys for push notifications")
        print(f"Public key: {public_key_b64[:20]}...")
        return keys
        
    except ImportError as ie:
        print(f"Warning: Required library not installed: {ie}")
        print("Install with: pip install pywebpush py-vapid")
        return {'public_key': '', 'private_key': ''}
    except Exception as e:
        import traceback
        print(f"Error generating VAPID keys: {e}")
        traceback.print_exc()
        return {'public_key': '', 'private_key': ''}


def send_push_notification(device_token, title, message, data=None):
    """
    Send push notification to a single device
    
    Args:
        device_token: DeviceToken model instance
        title: Notification title
        message: Notification message body
        data: Optional dict of additional data to send
        
    Returns:
        (success: bool, error_message: str or None)
    """
    try:
        vapid_keys = get_vapid_keys()
        
        if not vapid_keys.get('private_key'):
            return False, "VAPID keys not configured"
        
        # Validate device token data
        if not device_token.endpoint:
            return False, "Device endpoint is missing"
        if not device_token.p256dh_key:
            return False, "Device p256dh key is missing"
        if not device_token.auth_key:
            return False, "Device auth key is missing"
        
        # Build notification payload
        payload = {
            'title': str(title)[:100],  # Limit title length
            'body': str(message)[:500],  # Limit message length
            'icon': '/static/img/icon-192.png',
            'badge': '/static/img/badge-72.png',
            'data': data or {},
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Ensure payload is JSON serializable
        try:
            payload_json = json.dumps(payload)
        except (TypeError, ValueError) as json_err:
            return False, f"Payload not JSON serializable: {json_err}"
        
        # Prepare subscription info
        subscription_info = {
            'endpoint': device_token.endpoint,
            'keys': {
                'p256dh': device_token.p256dh_key,
                'auth': device_token.auth_key
            }
        }
        
        # Send push notification
        # pywebpush expects the private key in DER format as bytes or base64url string
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload_json,
                vapid_private_key=vapid_keys['private_key'],
                vapid_claims={
                    'sub': 'mailto:noreply@obsidianscout.app'
                }
            )
        except Exception as webpush_error:
            # If the key format is wrong, try to regenerate
            print(f"Webpush call failed: {webpush_error}")
            if 'deserialize' in str(webpush_error).lower() or 'invalid' in str(webpush_error).lower():
                print("VAPID key format issue detected. Deleting keys to force regeneration.")
                import os
                vapid_file = os.path.join(current_app.instance_path, 'vapid_keys.json')
                if os.path.exists(vapid_file):
                    os.remove(vapid_file)
                return False, "VAPID key error - keys regenerated, please try again"
            raise
        
        # Update device token success timestamp
        device_token.last_success = datetime.now(timezone.utc)
        device_token.failure_count = 0
        db.session.commit()
        
        return True, None
        
    except WebPushException as e:
        error_msg = str(e)
        print(f"WebPushException for device {device_token.device_name}: {error_msg}")
        
        # Handle specific errors
        if '404' in error_msg or '410' in error_msg:
            # Device endpoint no longer valid - mark as inactive
            device_token.is_active = False
            device_token.failure_count += 1
            try:
                db.session.commit()
            except Exception as commit_ex:
                print(f"Error committing device deactivation: {commit_ex}")
                db.session.rollback()
            return False, "Device endpoint expired (410/404)"
        else:
            # Other error - increment failure count
            device_token.failure_count += 1
            if device_token.failure_count >= 5:
                device_token.is_active = False
                print(f"Device {device_token.device_name} deactivated after 5 failures")
            try:
                db.session.commit()
            except Exception as commit_ex:
                print(f"Error committing failure count: {commit_ex}")
                db.session.rollback()
            return False, f"WebPushException: {error_msg}"
            
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"Push notification error for device {device_token.device_name}: {error_msg}")
        traceback.print_exc()
        
        device_token.failure_count += 1
        if device_token.failure_count >= 5:
            device_token.is_active = False
            print(f"Device {device_token.device_name} deactivated after 5 failures")
        try:
            db.session.commit()
        except Exception as commit_ex:
            print(f"Error committing failure count: {commit_ex}")
            db.session.rollback()
        return False, error_msg


def send_push_to_user(user_id, title, message, data=None):
    """
    Send push notification to all active devices for a user
    
    Args:
        user_id: User ID
        title: Notification title
        message: Notification message body
        data: Optional dict of additional data
        
    Returns:
        (success_count: int, failed_count: int, errors: list)
    """
    from app.models_misc import DeviceToken
    
    try:
        devices = DeviceToken.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
        
        print(f"Sending push to user {user_id}: {len(devices)} active devices")
        
        if not devices:
            return 0, 0, ["No active devices found"]
        
        success_count = 0
        failed_count = 0
        errors = []
        
        for device in devices:
            try:
                success, error = send_push_notification(device, title, message, data)
                if success:
                    success_count += 1
                    print(f"   Sent to device: {device.device_name}")
                else:
                    failed_count += 1
                    error_msg = f"{device.device_name or 'Unknown'}: {error}"
                    errors.append(error_msg)
                    print(f"   Failed for device {device.device_name}: {error}")
            except Exception as device_ex:
                failed_count += 1
                error_msg = f"{device.device_name or 'Unknown'}: Exception: {type(device_ex).__name__}"
                errors.append(error_msg)
                print(f"   Exception for device {device.device_name}: {device_ex}")
        
        return success_count, failed_count, errors
        
    except Exception as e:
        import traceback
        print(f"Error in send_push_to_user for user {user_id}: {e}")
        traceback.print_exc()
        return 0, 0, [f"Fatal error: {type(e).__name__}: {str(e)}"]


def register_device(user_id, endpoint, p256dh_key, auth_key, user_agent=None, device_name=None):
    """
    Register or update a device for push notifications
    
    Args:
        user_id: User ID
        endpoint: Push notification endpoint URL
        p256dh_key: Encryption key
        auth_key: Auth secret
        user_agent: Optional user agent string
        device_name: Optional friendly device name
        
    Returns:
        DeviceToken model instance
    """
    from app.models_misc import DeviceToken
    
    # Check if device already exists
    device = DeviceToken.query.filter_by(endpoint=endpoint).first()
    
    if device:
        # Update existing device
        device.user_id = user_id
        device.p256dh_key = p256dh_key
        device.auth_key = auth_key
        device.user_agent = user_agent
        device.is_active = True
        device.failure_count = 0
        device.updated_at = datetime.now(timezone.utc)
        if device_name:
            device.device_name = device_name
    else:
        # Create new device
        device = DeviceToken(
            user_id=user_id,
            endpoint=endpoint,
            p256dh_key=p256dh_key,
            auth_key=auth_key,
            user_agent=user_agent,
            device_name=device_name or _generate_device_name(user_agent),
            is_active=True,
            failure_count=0
        )
        db.session.add(device)
    
    db.session.commit()
    return device


def _generate_device_name(user_agent):
    """Generate a friendly device name from user agent string"""
    if not user_agent:
        return "Unknown Device"
    
    ua = user_agent.lower()
    
    # Check for common browsers
    if 'chrome' in ua and 'edg' not in ua:
        browser = 'Chrome'
    elif 'firefox' in ua:
        browser = 'Firefox'
    elif 'safari' in ua and 'chrome' not in ua:
        browser = 'Safari'
    elif 'edg' in ua:
        browser = 'Edge'
    else:
        browser = 'Browser'
    
    # Check for common platforms
    if 'windows' in ua:
        platform = 'Windows'
    elif 'mac' in ua:
        platform = 'Mac'
    elif 'linux' in ua:
        platform = 'Linux'
    elif 'android' in ua:
        platform = 'Android'
    elif 'iphone' in ua or 'ipad' in ua:
        platform = 'iOS'
    else:
        platform = 'Device'
    
    return f"{browser} on {platform}"


def cleanup_inactive_devices():
    """Remove devices that have failed too many times"""
    from app.models_misc import DeviceToken
    
    # Remove devices with 10+ failures that are inactive
    deleted = DeviceToken.query.filter(
        DeviceToken.is_active == False,
        DeviceToken.failure_count >= 10
    ).delete()
    
    db.session.commit()
    return deleted
