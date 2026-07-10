# Models

## ResUsers (res.users)
Status: [ACTIVE]
Purpose: Stores user-specific Teams OAuth tokens and preferences.
Key Fields:
- `sh_teams_access_token`, `sh_teams_refresh_token`, `sh_teams_token_expiry`: Used to manage MS Graph API access.
- `sh_teams_meeting_auto_create`, `sh_teams_meeting_auto_write`, `sh_teams_meeting_auto_unlink`: Preferences controlling whether actions sync automatically.
Critical Methods:
- `action_teams_connect`: Initiates Teams OAuth connection.
- `action_teams_disconnect`: Disconnects Teams account.
See also: [[02_data_flow]]

## CalendarEvent (calendar.event)
Status: [ACTIVE]
Purpose: Intercepts calendar event lifecycles to sync with Teams.
Key Fields:
- `sh_teams_meeting_url`, `sh_teams_meeting_id`: Store Teams connection data.
- `sh_ms_calendar_event_id`: Outlook calendar event ID.
- `sh_is_teams_meeting`: Boolean flag indicating if it's a Teams meeting.
Critical Methods:
- `action_create_teams_meeting`, `_async_create_teams_meeting`: Creates online meeting and MS calendar event.
- `action_sync_with_teams`: Manual sync trigger.
- `action_delete_teams_meeting`, `_delete_teams_meeting`: Deletes MS resources.
See also: [[02_data_flow]]

## ResCompany (res.company)
Status: [ACTIVE]
Purpose: Stores global Azure app credentials.
Key Fields:
- `sh_teams_client_id`, `sh_teams_client_secret`, `sh_teams_tenant_id`: Microsoft App Credentials.

## ResConfigSettings (res.config.settings)
Status: [ACTIVE]
Purpose: Exposes company Azure credentials to the settings UI.
