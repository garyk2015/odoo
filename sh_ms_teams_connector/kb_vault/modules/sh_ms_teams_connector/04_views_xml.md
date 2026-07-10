# Views

## `res_config_settings.xml`
- Adds Microsoft Teams configuration fields (Client ID, Client Secret, Tenant ID) under Discuss/General Settings.

## `res_users_views.xml`
- Adds a "Microsoft Teams" page to the user preferences notebook.
- Displays connection status, tokens (readonly), auto-sync preferences, and buttons to Connect/Disconnect.
- Links to `[[03_models#res.users]]`.

## `calendar_event_views.xml`
- Inherits `calendar.view_calendar_event_form`.
- Adds a "Microsoft Teams" page to the notebook with fields like Join URL, sync status, and manual sync/delete buttons.
- Adds an icon/button in the header to jump directly into the Teams meeting (`sh_teams_meeting_url`).
- Links to `[[03_models#calendar.event]]`.

## `template.xml`
- Error page template `sh_ms_teams_connector.auth_error` for handling OAuth failures gracefully.
