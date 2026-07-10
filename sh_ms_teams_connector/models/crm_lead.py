# -*- coding: utf-8 -*-
# Copyright (C) Softhealer Technologies Pvt. Ltd.

from odoo import models, api, _

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def action_schedule_teams_meeting(self):
        self.ensure_one()
        
        # Prepare attendees
        partner_ids = []
        if self.partner_id:
            partner_ids.append(self.partner_id.id)
            
        action = self.env["ir.actions.actions"]._for_xml_id("calendar.action_calendar_event")
        action['context'] = {
            'default_name': _('Teams Meeting: %s', self.name),
            'default_partner_ids': partner_ids,
            'default_res_model': 'crm.lead',
            'default_res_id': self.id,
            'default_opportunity_id': self.id,
            'default_sh_is_teams_meeting': True,
        }
        action['target'] = 'new'
        action['views'] = [(self.env.ref('calendar.view_calendar_event_form').id, 'form')]
        return action
