# Alliance Membership Constraints

## One Active Alliance Rule

Starting with this update, teams can only be **active** in one alliance at a time. This constraint was implemented to prevent configuration conflicts and ensure a clear data flow.

### How It Works

1. **Multiple Memberships Allowed**: Teams can still be members of multiple scouting alliances
2. **Single Active Alliance**: Only one alliance can be "active" for a team at any given time
3. **Automatic Switching**: When a team activates a different alliance, any currently active alliance is automatically deactivated
4. **Clear Status Indicators**: The dashboard and alliance views clearly show which alliance is currently active

### User Experience Changes

#### Dashboard
- Shows which alliance is currently active with green highlighting and "ACTIVE" badge
- Displays status message at the top indicating active alliance or no active alliance

#### Alliance View
- Warning message explains the one-active-alliance constraint
- Alliance mode toggle automatically handles switching between alliances
- Informative messages when switching from one alliance to another

#### Invitation Process
- Teams cannot accept invitations to join new alliances while they have an active alliance
- Clear error message explains the constraint and suggests deactivating current alliance first

### Inline help icons
Small question-mark help icons have been added across the Scouting Alliances UI next to key headings and controls. Hover or tap these icons to see concise contextual guidance. You can hide these inline help icons from the Settings page using **Show inline help icons** if you prefer a cleaner UI.

### Benefits

1. **Prevents Confusion**: Teams always know which alliance configuration they're using
2. **Avoids Data Conflicts**: No mixed configurations from multiple alliances
3. **Clear State Management**: Simplified alliance status tracking
4. **Better User Experience**: Clear visual indicators and helpful messaging

### Migration

- Existing teams with multiple active alliances will continue to work
- When they next activate an alliance, the constraint will take effect
- No data loss or configuration changes for existing setups

### Technical Implementation

- Database constraint ensures only one `TeamAllianceStatus` record per team
- Backend validation prevents conflicting alliance activations
- Frontend shows clear status and provides helpful error messages
- Automatic deactivation when switching alliances

This constraint improves the overall alliance system by providing clarity and preventing configuration conflicts while maintaining the flexibility for teams to participate in multiple alliances.
