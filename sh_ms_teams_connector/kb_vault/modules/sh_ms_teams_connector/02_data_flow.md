# Data Flow

## 1. Authentication Flow
- User clicks "Connect to Microsoft Teams" in their preferences -> triggers `[[03_models#res.users]] action_teams_connect`.
- Redirects to `[[06_controllers#/ms_teams/oauth/authorize]]`.
- User authenticates with Microsoft.
- Redirected back to `[[06_controllers#/ms_teams/oauth/callback]]` with authorization code.
- Controller exchanges code for `access_token` and `refresh_token` and stores in `res.users`.

## 2. Event Sync Flow
- User creates a calendar event in Odoo.
- `calendar.event` `create()` checks if `sh_teams_meeting_auto_create` is enabled.
- If enabled, calls `action_create_teams_meeting()`.
- Async function `_async_create_teams_meeting()` prepares `OnlineMeeting` and posts via Graph API.
- Also creates Microsoft Calendar Event via `_create_microsoft_calendar_event()`.
- Returns meeting join URL and ID, saving it to `calendar.event`.

## 3. Event Update/Deletion Flow
- User updates/deletes a calendar event.
- Overridden `write()` or `unlink()` intercepts the action.
- If auto-update/delete is enabled, triggers `_update_teams_meeting()` or `action_delete_teams_meeting()`.
- Async calls update/delete the OnlineMeeting and Calendar Event in Microsoft using Graph API.
