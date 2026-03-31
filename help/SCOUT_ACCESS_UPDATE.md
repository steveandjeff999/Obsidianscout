# Scout Access Behavior

This page documents the current scout-role restrictions and expected behavior.

## Scout-Only Access Rules

- Scout-only users are redirected to the scouting page after login.
- Scout-only users cannot access the main dashboard or admin/analytics-only pages.
- Navigation is simplified so scouting actions are emphasized.
- If a scout-only user visits a restricted URL directly, they are redirected back to scouting with an access warning.

## Dashboard Behavior

- On scouting-related pages, scout-only users may see limited-access sections with disabled controls where editing or admin actions are not allowed.
- Users with `analytics` or `admin` roles continue to see full controls and full navigation.

## Testing with a Sample Scout User

Use the provided helper script:

```
python other/create_test_scout.py
```

Default test credentials created by the script:
- Username: `Scout User`
- Password: `scout123`

Verify the following after login:
1. Redirect goes to scouting pages.
2. Dashboard/admin-only links are hidden or blocked.
3. Restricted direct URLs redirect with a warning.

## Related Documentation

- See `USER_ROLES_AND_PERMISSIONS.md` for role definitions.
- See `user-navigation.md` for route-level navigation examples.
