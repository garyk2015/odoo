# -*- coding: utf-8 -*-
# Copyright (C) Softhealer Technologies.

from odoo import models, fields, api
from odoo.http import request
from odoo.exceptions import UserError

class ResCompany(models.Model):
    _inherit = 'res.company'

    sh_teams_client_id = fields.Char(string='Microsoft Client ID')
    sh_teams_client_secret = fields.Char(string='Microsoft Client Secret')
    sh_teams_tenant_id = fields.Char(string='Microsoft Tenant ID')

    sh_user_target_ms_calendar_id = fields.Many2one(
        'sh.ms.teams.calendar', 
        string='Target Sync Calendar',
        compute='_compute_sh_user_target_calendar',
        inverse='_inverse_sh_user_target_calendar',
        domain="[('user_id', '=', uid)]"
    )

    sh_user_ms_last_event_sync_at = fields.Datetime(
        string='Last Teams Sync',
        compute='_compute_sh_user_last_sync'
    )

    sh_user_teams_sync_log_ids = fields.One2many(
        'sh.ms.teams.sync.log',
        compute='_compute_sh_user_teams_sync_log_ids',
        string='Sync Logs'
    )

    def _compute_sh_user_teams_sync_log_ids(self):
        for company in self:
            logs = self.env['sh.ms.teams.sync.log'].search([('user_id', '=', self.env.user.id)])
            company.sh_user_teams_sync_log_ids = logs

    def _compute_sh_user_last_sync(self):
        for company in self:
            company.sh_user_ms_last_event_sync_at = self.env.user.sh_ms_last_event_sync_at

    def _compute_sh_user_target_calendar(self):
        for company in self:
            company.sh_user_target_ms_calendar_id = self.env.user.sh_target_ms_calendar_id

    def _inverse_sh_user_target_calendar(self):
        for company in self:
            self.env.user.sh_target_ms_calendar_id = company.sh_user_target_ms_calendar_id

    def action_teams_sync_inbound(self):
        self.ensure_one()
        # Ensure the user has the credentials configured before attempting sync
        if self.env.user.sh_teams_connection_status != 'connected':
            raise UserError('Your Microsoft Teams account is not connected. Please connect it from your user preferences first.')
        return self.env.user.action_teams_sync_inbound()

    def action_fetch_ms_calendars(self):
        self.ensure_one()
        if self.env.user.sh_teams_connection_status != 'connected':
            raise UserError('Your Microsoft Teams account is not connected. Please connect it from your user preferences first.')
        return self.env.user.action_fetch_ms_calendars()

    def action_teams_subscribe_webhook(self):
        self.ensure_one()
        if self.env.user.sh_teams_connection_status != 'connected':
            raise UserError('Your Microsoft Teams account is not connected. Please connect it from your user preferences first.')
        return self.env.user.action_teams_subscribe_webhook()
