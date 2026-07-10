# Architecture

- **Backend Integration**: Python backend uses `msal` and `msgraph-sdk` to connect to Azure Graph API.
- **Authentication**: Custom OAuth callback implementation in the `MicrosoftTeamsController` controller for managing OAuth 2.0 PKCE flow.
- **Event Management**: Overrides Odoo's `calendar.event` model (`create`, `write`, `unlink`) to trigger API calls that create, update, or delete Microsoft Teams online meetings and Outlook Calendar events concurrently.

## Entry Points
- User connecting/disconnecting their Microsoft account via User Settings.
- User creating, updating, or deleting a `calendar.event` in Odoo.
- Auto-sync preferences toggling the above actions automatically or manually.

See: [[03_models]], [[06_controllers]]
