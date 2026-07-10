# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ShMsTeamsSyncLog(models.Model):
    _name = 'sh.ms.teams.sync.log'
    _description = 'Microsoft Teams Sync Log'
    _order = 'create_date desc'

    name = fields.Char(string='Reference', required=True, default='New')
    operation_type = fields.Selection([
        ('inbound', 'Inbound Sync (Microsoft to Odoo)'),
        ('outbound', 'Outbound Sync (Odoo to Microsoft)'),
        ('oauth', 'OAuth Authentication'),
        ('webhook', 'Webhook Callback'),
    ], string='Operation Type', required=True)
    
    status = fields.Selection([
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Status', required=True)
    
    message = fields.Text(string='Message / Details')
    
    user_id = fields.Many2one('res.users', string='Triggered By', default=lambda self: self.env.user)
    
    calendar_event_id = fields.Many2one('calendar.event', string='Related Event')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                op_type = vals.get('operation_type', 'sync').upper()
                vals['name'] = f'TEAMS/{op_type}/{fields.Datetime.now().strftime("%Y%m%d/%H%M%S")}'
        return super().create(vals_list)
