# Controllers

## /ms_teams/oauth/authorize [GET]
Status: [ACTIVE]
Auth: user
Called by: `[[03_models#res.users]] action_teams_connect`
Returns: Redirects to Microsoft Login for OAuth 2.0 PKCE flow.

## /ms_teams/oauth/callback [GET]
Status: [ACTIVE]
Auth: user
Called by: Microsoft OAuth Redirect
Returns: Exchanges authorization code for access/refresh tokens, stores them in `res.users`, and redirects to `/web`. Or renders `sh_ms_teams_connector.auth_error` on failure.

## /ms_teams/disconnect [JSONRPC]
Status: [ACTIVE]
Auth: user
Called by: JS or user action (though mainly model method is used).
Returns: Success dict after unsetting tokens.

## /ms_teams/refresh_token [JSONRPC]
Status: [ACTIVE]
Auth: user
Called by: Manual refresh requests.
Returns: Expiry data after exchanging refresh token for a new access token.
