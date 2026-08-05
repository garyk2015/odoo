# -*- coding: utf-8 -*-
# Copyright (C) Softhealer Technologies.
{
    'name': 'MS Teams - Appointment Integration',
    'version': '19.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Add MS Teams option to website appointments',
    'description': """This module bridges the Microsoft Teams connector with the Odoo Appointment module, allowing clients to book website appointments that automatically generate Microsoft Teams meetings.""",
    'author': 'Softhealer Technologies',
    'website': 'https://www.softhealer.com',
    'depends': ['sh_ms_teams_connector', 'appointment'],
    'data': [
    ],
    'auto_install': True,
    'installable': True,
    'license': 'OPL-1',
}
