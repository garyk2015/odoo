# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json
import logging

_logger = logging.getLogger(__name__)

class ShTeamsWebhook(models.Model):
    _name = 'sh.teams.webhook'
    _description = 'Microsoft Teams Webhook'

    name = fields.Char('Name', required=True, help="E.g., General Channel")
    webhook_url = fields.Char('Webhook URL', required=True)
    active = fields.Boolean('Active', default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def action_test_webhook(self):
        self.ensure_one()
        success = self.send_adaptive_card(
            title="Test Notification from Odoo",
            message="Your Teams Webhook is configured correctly! You will now receive Adaptive Cards from Odoo.",
            url_button_text="Open Odoo",
            url=self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        )
        if success:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Test notification sent successfully.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            raise UserError(_("Failed to send notification. Please check your Webhook URL."))

    def send_adaptive_card(self, title, message, url_button_text=None, url=None, facts=None):
        """
        Send an Adaptive Card to the Teams Webhook.
        :param title: The title of the card
        :param message: The main body text
        :param url_button_text: Text for the action button
        :param url: URL for the action button
        :param facts: A list of dicts [{'title': 'Status', 'value': 'Won'}]
        """
        self.ensure_one()
        if not self.webhook_url:
            return False

        # Build Adaptive Card JSON
        body = [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True
            },
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True
            }
        ]

        if facts:
            body.append({
                "type": "FactSet",
                "facts": facts
            })

        card_content = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.2",
            "body": body
        }

        if url and url_button_text:
            card_content["actions"] = [
                {
                    "type": "Action.OpenUrl",
                    "title": url_button_text,
                    "url": url
                }
            ]

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card_content
                }
            ]
        }

        try:
            headers = {'Content-Type': 'application/json'}
            response = requests.post(self.webhook_url, data=json.dumps(payload), headers=headers, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            _logger.error(f"Error sending Teams Adaptive Card: {str(e)}")
            return False
