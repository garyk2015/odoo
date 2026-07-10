# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import logging
from urllib.parse import urlencode

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    sh_teams_access_token = fields.Char(string='Teams Access Token', readonly=True, copy=False)
    sh_teams_refresh_token = fields.Char(string='Teams Refresh Token', readonly=True, copy=False)
    sh_teams_token_expiry = fields.Datetime(string='Token Expiry', readonly=True, copy=False)
    sh_teams_connection_status = fields.Selection([
        ('not_connected', 'Not Connected'),
        ('connected', 'Connected')
    ], string='Connection Status', compute='_compute_teams_connection_status', store=True)
    sh_redirect_url = fields.Char(string='Redirect Url', compute='_compute_redirect_url')

    sh_teams_meeting_auto_create = fields.Boolean("Auto Create")
    sh_teams_meeting_auto_write = fields.Boolean("Auto Update")
    sh_teams_meeting_auto_unlink = fields.Boolean("Auto Delete")

    sh_ms_teams_calendar_ids = fields.One2many('sh.ms.teams.calendar', 'user_id', string='Microsoft Calendars')
    sh_target_ms_calendar_id = fields.Many2one('sh.ms.teams.calendar', string='Target Sync Calendar', domain="[('user_id', '=', id)]")

    sh_ms_subscription_id = fields.Char(string='Graph Subscription ID', readonly=True)
    sh_ms_subscription_expiry = fields.Datetime(string='Subscription Expiry', readonly=True)

    def _compute_redirect_url(self):
        """Computes the redirect URL for OAuth authentication based on the integration type."""
        base_url = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        callback_path = '/ms_teams/oauth/callback'
        for record in self:
            record.sh_redirect_url = f"{base_url}{callback_path}" if base_url else callback_path

    @api.depends('sh_teams_refresh_token', 'sh_teams_access_token')
    def _compute_teams_connection_status(self):
        for user in self:
            if user.sh_teams_refresh_token and user.sh_teams_access_token:
                user.sh_teams_connection_status = 'connected'
            else:
                user.sh_teams_connection_status = 'not_connected'

    def action_fetch_ms_calendars(self):
        self.ensure_one()
        if self.sh_teams_connection_status != 'connected':
            raise UserError(_("You are not connected to Microsoft Teams."))

        from .calender_event import TeamsRefreshTokenCredential
        import requests
        
        credential = TeamsRefreshTokenCredential(self.env.company, self)
        token = credential.get_token('https://graph.microsoft.com/.default')
        if not token or not token.token:
            raise UserError(_("Failed to refresh Microsoft Graph token."))

        headers = {
            'Authorization': f'Bearer {token.token}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get('https://graph.microsoft.com/v1.0/me/calendars', headers=headers)
            response.raise_for_status()
            calendars_data = response.json().get('value', [])
        except Exception as e:
            raise UserError(_("Error fetching calendars from Microsoft: %s") % str(e))

        CalendarModel = self.env['sh.ms.teams.calendar']
        
        for cal in calendars_data:
            existing = CalendarModel.search([('ms_calendar_id', '=', cal['id']), ('user_id', '=', self.id)])
            if not existing:
                CalendarModel.create({
                    'name': cal.get('name', 'Unknown Calendar'),
                    'ms_calendar_id': cal['id'],
                    'user_id': self.id
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Calendars Fetched'),
                'message': _('Successfully fetched %s calendars from Microsoft.') % len(calendars_data),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_teams_subscribe_webhook(self):
        self.ensure_one()
        if self.sh_teams_connection_status != 'connected':
            raise UserError(_("You are not connected to Microsoft Teams."))

        from .calender_event import TeamsRefreshTokenCredential
        import requests
        from datetime import datetime, timedelta

        credential = TeamsRefreshTokenCredential(self.env.company, self)
        token = credential.get_token('https://graph.microsoft.com/.default')
        if not token or not token.token:
            raise UserError(_("Failed to refresh Microsoft Graph token."))

        headers = {
            'Authorization': f'Bearer {token.token}',
            'Content-Type': 'application/json'
        }

        base_url = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        notification_url = f"{base_url}/ms_teams/graph_webhook"

        # Subscription max life for events is 4230 minutes (almost 3 days). We set it for 2 days.
        expiry_time = datetime.utcnow() + timedelta(days=2)

        # Resource depends on if they chose a specific calendar or default
        if self.sh_target_ms_calendar_id:
            resource = f"/me/calendars/{self.sh_target_ms_calendar_id.ms_calendar_id}/events"
        else:
            resource = "/me/events"

        payload = {
            "changeType": "deleted",
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiry_time.isoformat() + "Z",
            "clientState": "odoo_teams_connector"
        }

        response = None
        try:
            response = requests.post('https://graph.microsoft.com/v1.0/subscriptions', headers=headers, json=payload)
            response.raise_for_status()
            sub_data = response.json()
            
            self.sh_ms_subscription_id = sub_data.get('id')
            
            # Graph returns expiry with Z
            exp_str = sub_data.get('expirationDateTime', '').replace('Z', '+00:00')
            if exp_str:
                self.sh_ms_subscription_expiry = datetime.fromisoformat(exp_str).replace(tzinfo=None)

            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'webhook',
                'status': 'success',
                'message': f"Successfully subscribed to Graph Webhooks (ID: {self.sh_ms_subscription_id})",
                'user_id': self.id
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Webhook Subscribed'),
                    'message': _('Successfully connected to Microsoft Push Notifications! Deletes will now happen automatically.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            error_msg = str(e)
            if response is not None and hasattr(response, 'text'):
                error_msg += f" - {response.text}"
            
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'webhook',
                'status': 'error',
                'message': f"Failed to subscribe to Webhooks: {error_msg}",
                'user_id': self.id
            })
            raise UserError(_("Error creating Webhook Subscription: %s") % error_msg)

    @api.model
    def _cron_renew_teams_webhooks(self):
        """Automatically renews Graph subscriptions for all users before they expire."""
        from .calender_event import TeamsRefreshTokenCredential
        import requests
        from datetime import datetime, timedelta

        users = self.search([('sh_ms_subscription_id', '!=', False)])
        for user in users:
            try:
                credential = TeamsRefreshTokenCredential(self.env.company, user)
                token = credential.get_token('https://graph.microsoft.com/.default')
                if not token or not token.token:
                    continue

                headers = {
                    'Authorization': f'Bearer {token.token}',
                    'Content-Type': 'application/json'
                }
                
                # Renew for another 2 days
                expiry_time = datetime.utcnow() + timedelta(days=2)
                payload = {
                    "expirationDateTime": expiry_time.isoformat() + "Z"
                }

                url = f"https://graph.microsoft.com/v1.0/subscriptions/{user.sh_ms_subscription_id}"
                response = requests.patch(url, headers=headers, json=payload)
                
                if response.status_code in (200, 204):
                    sub_data = response.json()
                    exp_str = sub_data.get('expirationDateTime', '').replace('Z', '+00:00')
                    if exp_str:
                        user.sh_ms_subscription_expiry = datetime.fromisoformat(exp_str).replace(tzinfo=None)
                    
                    self.env['sh.ms.teams.sync.log'].create({
                        'operation_type': 'webhook',
                        'status': 'success',
                        'message': f"Webhook: Auto-renewed subscription {user.sh_ms_subscription_id}",
                        'user_id': user.id
                    })
                elif response.status_code == 404:
                    # Subscription doesn't exist anymore on Microsoft end. Recreate it.
                    user.action_teams_subscribe_webhook()
                
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Cron: Failed to renew Graph webhook for {user.name}: {e}")

    def action_teams_connect(self):
        """Initiate Teams OAuth connection"""
        self.ensure_one()
        
        # Verify company settings are configured
        company = self.env.company
        if not all([company.sh_teams_client_id, company.sh_teams_tenant_id]):
            raise UserError(_(
                'Please configure Microsoft Teams credentials (Client ID and Tenant ID) '
                'in Company Settings first.'
            ))
        
        # Build state parameter
        state_payload = {
            'user_id': self.id,
            'timestamp': fields.Datetime.now().isoformat()
        }
        state = json.dumps(state_payload)
        
        # Return action to redirect to authorization endpoint
        action_url = '/ms_teams/oauth/authorize'
        if state:
            action_url = f"{action_url}?{urlencode({'state': state})}"

        return {
            'type': 'ir.actions.act_url',
            'url': action_url,
            'target': 'self',
        }

    def action_teams_disconnect(self):
        """Disconnect Teams account"""
        self.ensure_one()
        
        self.sudo().write({
            'sh_teams_access_token': False,
            'sh_teams_refresh_token': False,
            'sh_teams_token_expiry': False,
            'sh_teams_meeting_auto_create': False,
            'sh_teams_meeting_auto_write': False,
            'sh_teams_meeting_auto_unlink': False,
        })
        
        self.env['sh.ms.teams.sync.log'].create({
            'operation_type': 'oauth',
            'status': 'warning',
            'message': 'User disconnected from Microsoft Teams and revoked tokens.',
            'user_id': self.id
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Microsoft Teams account disconnected successfully'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_teams_refresh_token(self):
        """Manually refresh the access token"""
        self.ensure_one()
        
        if not self.sh_teams_refresh_token:
            raise UserError(_('No refresh token available. Please reconnect your account.'))
        
        # This would typically be called automatically, but can be triggered manually
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Info'),
                'message': _('Token refresh is handled automatically when needed'),
                'type': 'info',
                'sticky': False,
            }
        }
