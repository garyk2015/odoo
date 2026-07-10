# -*- coding: utf-8 -*-
from odoo import models, fields

class ShMsTeamsCalendar(models.Model):
    _name = 'sh.ms.teams.calendar'
    _description = 'Microsoft Teams Calendar'

    name = fields.Char(string='Calendar Name', required=True)
    ms_calendar_id = fields.Char(string='Microsoft Calendar ID', required=True)
    user_id = fields.Many2one('res.users', string='Odoo User', required=True, ondelete='cascade')

    _sql_constraints = [
        ('ms_calendar_id_uniq', 'unique (ms_calendar_id, user_id)', 'This calendar is already synced for this user!')
    ]
