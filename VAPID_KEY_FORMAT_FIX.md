# VAPID Key Format Fix

## Error Fixed
```
Push error: Chrome Browser: ValueError: Could not deserialize key data. 
The data may be in an incorrect format, it may be encrypted with an 
unsupported algorithm, or it may be an unsupported key type (e.g. EC 
curves with explicit parameters). Details: ASN.1 parsing error: 
unexpected tag (got Tag { value: 13, constructed: true, class: Universal })
```

## Root Cause
The VAPID private key was being stored in **base64url encoded format**, but the `pywebpush` library expects the private key to be in **PEM format** (as a string).

### What Was Wrong
```python
# OLD - Incorrect format
private_key_b64 = base64.urlsafe_b64encode(private_bytes).decode('utf-8').rstrip('=')
keys = {
    'public_key': public_key_b64,
    'private_key': private_key_b64  # ❌ Base64url encoded - WRONG!
}
```

### What's Fixed Now
```python
# NEW - Correct format
private_key_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode('utf-8')  # Decode to string

keys = {
    'public_key': public_key_b64,      # Base64url for client
    'private_key': private_key_pem     # ✅ PEM format for pywebpush
}
```

## Changes Made

### 1. Fixed VAPID Key Generation (`app/utils/push_notifications.py`)

**Changes:**
- ✅ Private key now stored as PEM string (not base64url)
- ✅ Public key remains base64url (correct for client-side)
- ✅ Added debug logging to show generated key preview
- ✅ Removed unnecessary import

**Key Formats:**
- **Private Key**: PEM format string (starts with `-----BEGIN PRIVATE KEY-----`)
  - Used by pywebpush library to sign requests
  - Stored in `instance/vapid_keys.json`
  
- **Public Key**: Base64url encoded (no padding)
  - Sent to browser for subscription
  - Used by push service to verify signatures

### 2. Deleted Old Keys
- Removed `instance/vapid_keys.json` with incorrect format
- New keys will be auto-generated on next server start
- New keys will be in correct PEM format

## What Happens Next

1. **On Server Start:**
   - `get_vapid_keys()` is called
   - No keys found (we deleted the old ones)
   - New keys generated in correct format
   - Keys saved to `instance/vapid_keys.json`

2. **On Device Registration:**
   - Browser receives public key in base64url format ✅
   - Browser subscribes to push service ✅
   - Server stores subscription info ✅

3. **On Push Send:**
   - `pywebpush` uses private key in PEM format ✅
   - Push notification sent successfully ✅
   - No more ASN.1 parsing errors ✅

## Testing Steps

1. **Restart the server** (new VAPID keys will be generated)
2. **Go to notifications page**
3. **Click "Enable Push Notifications"**
4. **Grant permission** when browser asks
5. **Device should register successfully** (no error)
6. **Click "Test Push Notification"**
7. **Should receive push notification** (no error)

## Expected Console Output

On server start:
```
Generated new VAPID keys for push notifications
Public key: ABCDefgh12345678...
```

On device registration:
```
✅ Push notifications enabled successfully!
```

On push send (no errors):
```
Sending push to user 1: 1 active devices
  ✓ Sent to device: Chrome Browser
```

## Technical Details

### PEM Format Example
```
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg...
-----END PRIVATE KEY-----
```

### Base64url Format Example
```
BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx...
```

### Why Two Different Formats?

1. **Private Key (PEM)**:
   - Standard format for cryptographic keys
   - Includes metadata and structure
   - pywebpush expects this format
   - Never sent to client

2. **Public Key (Base64url)**:
   - Compact format for transmission
   - Raw key bytes encoded
   - Web Push API expects this format
   - Sent to browser for subscription

## Files Modified

1. ✅ `app/utils/push_notifications.py` - Fixed VAPID key generation
2. ✅ Deleted `instance/vapid_keys.json` - Removed incorrect keys

## Related Documentation

- Web Push Protocol: https://datatracker.ietf.org/doc/html/rfc8291
- VAPID Specification: https://datatracker.ietf.org/doc/html/rfc8292
- pywebpush library: https://github.com/web-push-libs/pywebpush

## Prevention

This error won't happen again because:
- ✅ Private key stored in correct PEM format
- ✅ Public key stored in correct base64url format
- ✅ Added preview logging for verification
- ✅ Format matches pywebpush expectations
