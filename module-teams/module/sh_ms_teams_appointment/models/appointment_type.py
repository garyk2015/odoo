# -*- coding: utf-8 -*-
# Copyright (C) Softhealer Technologies.

from odoo import models, fields

class AppointmentType(models.Model):
    _inherit = 'appointment.type'

    event_videocall_source = fields.Selection(
        selection_add=[('ms_teams', 'Microsoft Teams')],
        ondelete={'ms_teams': 'set null'}
    )
