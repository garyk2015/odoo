# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import requests
import json
import logging
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode
from werkzeug.utils import redirect


_logger = logging.getLogger(__name__)


class MicrosoftTeamsController(http.Controller):

    PKCE_SESSION_KEY = 'ms_teams_code_verifiers'

    @staticmethod
    def _generate_pkce_pair():
        """Return a (verifier, challenge) pair compliant with RFC 7636."""
        code_verifier = secrets.token_urlsafe(96)[:128]
        if len(code_verifier) < 43:
            code_verifier = (code_verifier + secrets.token_urlsafe(48))[:128]
        digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
        return code_verifier, code_challenge

    def _store_code_verifier(self, state, code_verifier):
        """Persist the verifier in the user's session keyed by OAuth state."""
        session = request.session
        store = dict(session.get(self.PKCE_SESSION_KEY) or {})
        if len(store) >= 5:
            first_key = next(iter(store))
            store.pop(first_key, None)
        store[state] = code_verifier
        session[self.PKCE_SESSION_KEY] = store

    def _pop_code_verifier(self, state):
        """Fetch and remove the stored verifier for the given state."""
        session = request.session
        store = dict(session.get(self.PKCE_SESSION_KEY) or {})
        code_verifier = store.pop(state, None)
        session[self.PKCE_SESSION_KEY] = store
        return code_verifier
    
    @http.route('/ms_teams/oauth/authorize', type='http', auth='user', website=True, cors="*")
    def oauth_authorize(self, **kw):
        """Initiate OAuth flow - redirect to Microsoft login"""
        
        state = kw.get('state')
        
        try:
            # Get company settings
            company = request.env.company
            if not all([company.sh_teams_client_id, company.sh_teams_tenant_id]):
                return request.render('sh_ms_teams_connector.auth_error', {
                    'error_message': 'Microsoft Teams credentials not configured in company settings'
                })
            if not state:
                state = json.dumps({
                    'user_id': request.env.user.id,
                    'timestamp': datetime.utcnow().isoformat()
                })

            # Build OAuth authorization URL
            base_url = (request.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
            redirect_uri = request.env.user.sh_redirect_url or f'{base_url}/ms_teams/oauth/callback'
            code_verifier, code_challenge = self._generate_pkce_pair()
            self._store_code_verifier(state, code_verifier)
            
            auth_params = {
                'client_id': company.sh_teams_client_id,
                'response_type': 'code',
                'redirect_uri': redirect_uri,
                'response_mode': 'query',
                'scope': 'https://graph.microsoft.com/OnlineMeetings.ReadWrite '
                        'https://graph.microsoft.com/Calendars.ReadWrite '
                        'https://graph.microsoft.com/User.Read '
                        'offline_access',
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256'
            }
            
            auth_url = f'https://login.microsoftonline.com/{company.sh_teams_tenant_id}/oauth2/v2.0/authorize?{urlencode(auth_params)}'
            
            _logger.info(f'Redirecting to Microsoft authorization URL for user {request.env.user.name}')
            
            # Redirect to Microsoft login
            return redirect(auth_url, code=302)
            
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error initiating OAuth: {error_msg}')
            return request.render('sh_ms_teams_connector.auth_error', {
                'error_message': error_msg
            })
    
    @http.route('/ms_teams/oauth/callback', type='http', auth='user', website=True, cors='*')
    def oauth_callback(self, **kw):
        """Handle OAuth callback from Microsoft"""
        
        # Get authorization code
        code = kw.get('code')
        state = kw.get('state')
        error = kw.get('error')
        error_description = kw.get('error_description')
        
        # Handle errors from Microsoft
        if error:
            _logger.error(f'OAuth error: {error} - {error_description}')
            request.env['sh.ms.teams.sync.log'].sudo().create({
                'operation_type': 'oauth',
                'status': 'error',
                'message': f"OAuth Error from Microsoft: {error} - {error_description}",
                'user_id': request.env.user.id
            })
            return request.render('sh_ms_teams_connector.auth_error', {
                'error_message': error_description or error
            })
        
        if not code:
            _logger.error('No authorization code received')
            return request.render('sh_ms_teams_connector.auth_error', {
                'error_message': 'No authorization code received from Microsoft'
            })
        
        try:
            # Parse state to get user context
            try:
                state_data = json.loads(state) if state else {}
            except json.JSONDecodeError:
                state_data = {}
                _logger.warning('Invalid OAuth state received: %s', state)

            user_id = state_data.get('user_id') or request.env.user.id
            code_verifier = self._pop_code_verifier(state)
            if not code_verifier:
                raise Exception(_('Your login session expired. Please start the Microsoft Teams connection again.'))
            
            # Get company settings
            company = request.env.company
            if not all([company.sh_teams_client_id, company.sh_teams_tenant_id]):
                raise Exception('Microsoft Teams credentials not configured in company settings')
            
            # Exchange authorization code for tokens
            base_url = (request.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
            user = request.env['res.users'].sudo().browse(user_id)
            if not user:
                raise Exception('Invalid user specified in OAuth state')

            redirect_uri = user.sh_redirect_url or f'{base_url}/ms_teams/oauth/callback'

            token_url = f'https://login.microsoftonline.com/{company.sh_teams_tenant_id}/oauth2/v2.0/token'

            token_data = {
                'client_id': company.sh_teams_client_id,
                'code': code,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
                'code_verifier': code_verifier,
                'client_secret': company.sh_teams_client_secret,
                'scope': 'https://graph.microsoft.com/OnlineMeetings.ReadWrite '
                        'https://graph.microsoft.com/Calendars.ReadWrite '
                        'https://graph.microsoft.com/User.Read '
                        'offline_access'
            }
            if company.sh_teams_client_secret:
                token_data['client_secret'] = company.sh_teams_client_secret
            
            _logger.info('Exchanging authorization code for tokens')
            response = requests.post(token_url, data=token_data, timeout=30)
            
            # Log response for debugging
            _logger.info(f'Token exchange response status: {response.status_code}')
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
                _logger.error(f'Token exchange failed: {error_msg}')
                request.env['sh.ms.teams.sync.log'].sudo().create({
                    'operation_type': 'oauth',
                    'status': 'error',
                    'message': f"Token exchange failed: {error_msg}",
                    'user_id': user.id
                })
                raise Exception(f'Token exchange failed: {error_msg}')
            
            token_response = response.json()
            
            # Verify we got the required tokens
            if 'access_token' not in token_response:
                raise Exception('No access token received from Microsoft')
            
            if 'refresh_token' not in token_response:
                _logger.warning('No refresh token received - offline_access scope may not be granted')
            
            # Store tokens in user record
            token_expiry = datetime.now() + timedelta(seconds=token_response.get('expires_in', 3600))
            
            user.write({
                'sh_teams_access_token': token_response['access_token'],
                'sh_teams_refresh_token': token_response.get('refresh_token'),
                'sh_teams_token_expiry': token_expiry
            })
            
            _logger.info(f'Successfully authenticated user {user.name} with Microsoft Teams')
            request.env['sh.ms.teams.sync.log'].sudo().create({
                'operation_type': 'oauth',
                'status': 'success',
                'message': 'Successfully authenticated with Microsoft Teams and received tokens.',
                'user_id': user.id
            })
            _logger.info(f'Token expires at: {token_expiry}')

            return redirect('/web')
            
        except requests.exceptions.RequestException as e:
            error_msg = f'Network error: {str(e)}'
            _logger.error(f'Error in OAuth callback: {error_msg}')
            return request.render('sh_ms_teams_connector.auth_error', {
                'error_message': error_msg
            })
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error in OAuth callback: {error_msg}')
            return request.render('sh_ms_teams_connector.auth_error', {
                'error_message': error_msg
            })
    
    @http.route('/ms_teams/disconnect', type='jsonrpc', auth='user')
    def disconnect_teams(self, **kw):
        """Disconnect Microsoft Teams account"""
        try:
            user_id = kw.get('user_id', request.env.user.id)
            user = request.env['res.users'].sudo().browse(user_id)
            
            user.write({
                'sh_teams_access_token': False,
                'sh_teams_refresh_token': False,
                'sh_teams_token_expiry': False
            })
            
            _logger.info(f'Disconnected Teams for user {user.name}')
            
            return {'success': True, 'message': 'Disconnected successfully'}
            
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error disconnecting Teams: {error_msg}')
            return {'success': False, 'error': error_msg}

    @http.route('/ms_teams/graph_webhook', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def graph_webhook(self, **kw):
        """Handle incoming webhook from Microsoft Graph (Validation and Notifications)"""
        validation_token = kw.get('validationToken')
        
        # 1. Validation Phase (Microsoft proving we own the URL)
        if validation_token:
            _logger.info("Received Graph Webhook validation request.")
            return request.make_response(validation_token, headers=[('Content-Type', 'text/plain')])
        
        # 2. Notification Phase
        try:
            data = json.loads(request.httprequest.data)
            for notification in data.get('value', []):
                change_type = notification.get('changeType')
                resource_data = notification.get('resourceData', {})
                event_id = resource_data.get('id')
                
                if not event_id:
                    continue

                if change_type == 'deleted':
                    # Find the Odoo event and delete it silently
                    events = request.env['calendar.event'].sudo().search([('sh_ms_calendar_event_id', '=', event_id)])
                    for event in events:
                        event_id_num = event.id
                        event_name = event.name
                        event_user_id = event.user_id.id or request.env.ref('base.user_admin').id
                        event.with_context(sh_teams_sync_inbound=True).unlink()
                        _logger.info(f"Webhook: Deleted Odoo event {event_id_num} because it was deleted in Microsoft Outlook.")
                        
                        request.env['sh.ms.teams.sync.log'].sudo().create({
                            'operation_type': 'webhook',
                            'status': 'success',
                            'message': f"Webhook: Instantly deleted Odoo event '{event_name}' because it was deleted in Microsoft.",
                            'user_id': event_user_id
                        })

        except Exception as e:
            _logger.error(f"Error processing Graph Webhook: {e}")
        
        # Always return 202 Accepted quickly per Microsoft docs
        return request.make_response('', status=202)
    

    @http.route('/ms_teams/refresh_token', type='jsonrpc', auth='user')
    def refresh_token(self, **kw):
        """Manually refresh access token"""
        try:
            user = request.env.user
            
            if not user.sh_teams_refresh_token:
                return {'success': False, 'error': 'No refresh token available'}
            
            company = request.env.company
            if not all([company.sh_teams_client_id, company.sh_teams_tenant_id]):
                return {'success': False, 'error': 'Teams credentials not configured'}
            
            base_url = (request.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
            redirect_uri = user.sh_redirect_url or f'{base_url}/ms_teams/oauth/callback'
            
            token_url = f'https://login.microsoftonline.com/{company.sh_teams_tenant_id}/oauth2/v2.0/token'
            
            token_data = {
                'client_id': company.sh_teams_client_id,
                'refresh_token': user.sh_teams_refresh_token,
                'redirect_uri': redirect_uri,
                'grant_type': 'refresh_token',
                'scope': 'https://graph.microsoft.com/OnlineMeetings.ReadWrite '
                        'https://graph.microsoft.com/Calendars.ReadWrite '
                        'https://graph.microsoft.com/User.Read '
                        'offline_access'
            }
            if company.sh_teams_client_secret:
                token_data['client_secret'] = company.sh_teams_client_secret
            
            response = requests.post(token_url, data=token_data, timeout=30)
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error_description', 'Token refresh failed')
                return {'success': False, 'error': error_msg}
            
            token_response = response.json()
            
            token_expiry = datetime.now() + timedelta(seconds=token_response.get('expires_in', 3600))
            
            user.sudo().write({
                'sh_teams_access_token': token_response['access_token'],
                'sh_teams_refresh_token': token_response.get('refresh_token', user.sh_teams_refresh_token),
                'sh_teams_token_expiry': token_expiry
            })
            
            _logger.info(f'Token refreshed for user {user.name}')
            
            return {
                'success': True,
                'token_expiry': token_expiry.strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error refreshing token: {error_msg}')
            return {'success': False, 'error': error_msg}
