# -*- coding: utf-8 -*-
# Copyright (C) Softhealer Technologies.

from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sh_teams_client_id = fields.Char(
        related='company_id.sh_teams_client_id',
        string='Microsoft Client ID',
        readonly=False
    )
    sh_teams_client_secret = fields.Char(
        related='company_id.sh_teams_client_secret',
        string='Microsoft Client Secret',
        readonly=False
    )
    sh_teams_tenant_id = fields.Char(
        related='company_id.sh_teams_tenant_id',
        string='Microsoft Tenant ID',
        readonly=False
    )