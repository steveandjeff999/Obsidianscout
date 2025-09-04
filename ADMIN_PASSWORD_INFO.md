# Admin Password Information

## Superadmin Account
- **Username**: superadmin
- **Password**: JSHkimber1911
- **Team Number**: 0
- **Must Change Password**: No (password already changed from default)

## Common Login Issues

### Issue: "Invalid username, password, or team number"
**Causes:**
- Wrong password (most common)
- Wrong team number
- Account deactivated
- Username typo

**Solutions:**
1. Verify the password is exactly: `JSHkimber1911`
2. Verify team number is: `0`
3. Check if account is active in user management
4. Wait 15 minutes if account is temporarily locked

### Issue: Login temporarily blocked
**Cause:** Too many failed login attempts (10+ in 15 minutes)
**Solution:** Wait 15 minutes or run the cleanup script

### Issue: Redirected to change password
**Cause:** Account flagged for mandatory password change
**Solution:** Complete the password change process

## Troubleshooting Steps

1. **Verify Credentials**: Use exactly `superadmin` / `JSHkimber1911` / `0`
2. **Check Account Status**: Ensure account is active
3. **Clear Failed Attempts**: Run `python clear_failed_logins.py superadmin`
4. **Check Brute Force Protection**: Run `python debug_brute_force.py`
5. **Reset Password**: Use user management interface if needed

## Password Security Notes

- The password `JSHkimber1911` was set by an administrator
- It's different from the default `password` mentioned in documentation
- This is intentional for security purposes
- Consider changing to a more secure password through the UI
