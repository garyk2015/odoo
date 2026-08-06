# -*- coding: utf-8 -*-
# Copyright (C) Softhealer Technologies Pvt. Ltd.

from odoo import models, fields

class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    videocall_source = fields.Selection(
        selection_add=[('ms_teams', 'Microsoft Teams')],
        ondelete={'ms_teams': 'set null'}
    )

    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get('sh_teams_sync_inbound'):
            return records
            
        for record in records:
            if record.videocall_source == 'ms_teams' and not record.sh_is_teams_meeting:
                record.with_context(sh_teams_silent_fail=True).action_create_teams_meeting()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('sh_teams_sync_inbound'):
            return res

        if 'videocall_source' in vals:
            for record in self:
                if record.videocall_source == 'ms_teams' and not record.sh_is_teams_meeting:
                    record.with_context(sh_teams_silent_fail=True).action_create_teams_meeting()
        return res


