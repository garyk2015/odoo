# -*- coding: utf-8 -*-
import requests
from datetime import datetime
from odoo import models, fields, _
from odoo.exceptions import UserError
from .calender_event import TeamsRefreshTokenCredential

class ResUsersInbound(models.Model):
    _inherit = 'res.users'

    sh_ms_last_event_sync_at = fields.Datetime(string="Last Teams Sync", readonly=True)

    sh_ms_calendar_delta_link = fields.Char(string="Calendar Delta Link", readonly=True)

    def _cron_teams_delta_sync(self):
        """Cron job to sync events using Microsoft Graph Delta queries."""
        users = self.search([('sh_teams_connection_status', '=', 'connected')])
        for user in users:
            try:
                user.action_teams_sync_inbound(is_cron=True)
            except Exception as e:
                self.env['sh.ms.teams.sync.log'].create({
                    'operation_type': 'inbound',
                    'status': 'error',
                    'message': f"Delta sync cron failed for user {user.name}: {str(e)}",
                    'user_id': user.id
                })

    def action_teams_sync_inbound(self, is_cron=False):
        self.ensure_one()
        LogModel = self.env['sh.ms.teams.sync.log']
        if self.sh_teams_connection_status != 'connected':
            if is_cron: return
            error_msg = _("You are not connected to Microsoft Teams.")
            LogModel.create({'operation_type': 'inbound', 'status': 'error', 'message': error_msg, 'user_id': self.id})
            raise UserError(error_msg)

        credential = TeamsRefreshTokenCredential(self.env.company, self)
        token = credential.get_token('https://graph.microsoft.com/.default')
        if not token or not token.token:
            if is_cron: return
            error_msg = _("Failed to refresh Microsoft Graph token.")
            LogModel.create({'operation_type': 'inbound', 'status': 'error', 'message': error_msg, 'user_id': self.id})
            raise UserError(error_msg)

        headers = {
            'Authorization': f'Bearer {token.token}',
            'Content-Type': 'application/json'
        }

        # Initialize Delta URL
        target_cal_id = self.sh_target_ms_calendar_id.ms_calendar_id
        
        if self.sh_ms_calendar_delta_link:
            # If the calendar was changed recently, the old delta link is invalid. Clear it.
            if target_cal_id and target_cal_id not in self.sh_ms_calendar_delta_link:
                self.sh_ms_calendar_delta_link = False
            elif not target_cal_id and '/calendars/' in self.sh_ms_calendar_delta_link:
                self.sh_ms_calendar_delta_link = False
                
        select_fields = "?$select=id,subject,isOnlineMeeting,onlineMeeting,start,end,lastModifiedDateTime,isReminderOn,reminderMinutesBeforeStart,location,attendees&$expand=attachments"
        
        if self.sh_ms_calendar_delta_link:
            url = self.sh_ms_calendar_delta_link
        else:
            if target_cal_id:
                url = f"https://graph.microsoft.com/v1.0/me/calendars/{target_cal_id}/events/delta{select_fields}"
            else:
                url = f"https://graph.microsoft.com/v1.0/me/events/delta{select_fields}"
        
        events_data = []
        while url:
            try:
                response = requests.get(url, headers=headers)
                # Handle delta token expiration (HTTP 410 Gone or HTTP 400 Bad Request depending on API changes)
                if response.status_code in [410, 400]:
                    self.sh_ms_calendar_delta_link = False
                    target_cal_id = self.sh_target_ms_calendar_id.ms_calendar_id
                    
                    select_fields = "?$select=id,subject,isOnlineMeeting,onlineMeeting,start,end,lastModifiedDateTime,isReminderOn,reminderMinutesBeforeStart,location,attendees&$expand=attachments"
                    if target_cal_id:
                        url = f"https://graph.microsoft.com/v1.0/me/calendars/{target_cal_id}/events/delta{select_fields}"
                    else:
                        url = f"https://graph.microsoft.com/v1.0/me/events/delta{select_fields}"
                    continue
                
                response.raise_for_status()
                data = response.json()
                events_data.extend(data.get('value', []))
                
                if '@odata.nextLink' in data:
                    url = data['@odata.nextLink']
                elif '@odata.deltaLink' in data:
                    self.sh_ms_calendar_delta_link = data['@odata.deltaLink']
                    url = None
                else:
                    url = None
                    
            except Exception as e:
                error_msg = _("Error fetching delta events from Microsoft: %s") % str(e)
                LogModel.create({'operation_type': 'inbound', 'status': 'error', 'message': error_msg, 'user_id': self.id})
                if not is_cron:
                    raise UserError(error_msg)
                return

        CalendarEvent = self.env['calendar.event']
        IrAttachment = self.env['ir.attachment']
        created_count = 0
        updated_count = 0
        deleted_count = 0

        for ms_event in events_data:
            ms_id = ms_event.get('id')
            
            # Handle Deletion via Delta Sync
            if '@removed' in ms_event:
                existing_event = CalendarEvent.search([('sh_ms_calendar_event_id', '=', ms_id)], limit=1)
                if existing_event:
                    existing_event.with_context(sh_teams_sync_inbound=True).unlink()
                    deleted_count += 1
                continue
                
            # Filter for online meetings (delta endpoint doesn't support server-side $filter)
            if not ms_event.get('isOnlineMeeting'):
                continue
                
            subject = ms_event.get('subject', 'Teams Meeting')
            join_url = ms_event.get('onlineMeeting', {}).get('joinUrl') or ms_event.get('location', {}).get('displayName', '')
            
            start_str = ms_event.get('start', {}).get('dateTime')
            end_str = ms_event.get('end', {}).get('dateTime')
            if not start_str or not end_str:
                continue
                
            start_dt = datetime.fromisoformat(start_str.split('.')[0])
            end_dt = datetime.fromisoformat(end_str.split('.')[0])
            
            ms_last_modified_str = ms_event.get('lastModifiedDateTime')
            if ms_last_modified_str:
                ms_last_modified = datetime.fromisoformat(ms_last_modified_str.replace('Z', '+00:00')).replace(tzinfo=None)
            else:
                ms_last_modified = datetime.min

            # Process Reminders
            is_reminder_on = ms_event.get('isReminderOn', False)
            alarm_ids = []
            if is_reminder_on:
                reminder_minutes = ms_event.get('reminderMinutesBeforeStart', 15)
                alarm = self.env['calendar.alarm'].search([('duration', '=', reminder_minutes), ('interval', '=', 'minutes'), ('alarm_type', '=', 'notification')], limit=1)
                if not alarm:
                    alarm = self.env['calendar.alarm'].create({'name': f'{reminder_minutes} Minutes Notification', 'duration': reminder_minutes, 'interval': 'minutes', 'alarm_type': 'notification'})
                alarm_ids.append(alarm.id)

            existing_event = CalendarEvent.search([('sh_ms_calendar_event_id', '=', ms_id)], limit=1)
            
            # Microsoft Graph Delta Query completely strips the attendees array to save bandwidth.
            # We must fetch the individual event directly to get the attendees and RSVP status.
            ms_attendees = []
            try:
                full_event_url = f"https://graph.microsoft.com/v1.0/me/events/{ms_id}?$select=attendees&$expand=attachments"
                full_res = requests.get(full_event_url, headers=headers)
                if full_res.status_code == 200:
                    full_data = full_res.json()
                    ms_attendees = full_data.get('attendees', [])
                    ms_event['attachments'] = full_data.get('attachments', [])
            except Exception:
                pass
            
            partner_ids = []
            attendee_responses = {}
            
            for att in ms_attendees:
                email = att.get('emailAddress', {}).get('address')
                if not email:
                    continue
                email = email.lower()
                response = att.get('status', {}).get('response', 'none')
                
                # Map Microsoft status to Odoo state
                if response == 'accepted':
                    state = 'accepted'
                elif response == 'declined':
                    state = 'declined'
                elif response == 'tentativelyAccepted':
                    state = 'tentative'
                else:
                    state = 'needsAction'
                    
                attendee_responses[email] = state
                
                partner = self.env['res.partner'].search([('email', '=ilike', email)], limit=1)
                if not partner:
                    name = att.get('emailAddress', {}).get('name') or email
                    partner = self.env['res.partner'].create({'name': name, 'email': email})
                partner_ids.append(partner.id)
            
            vals = {
                'name': subject,
                'start': start_dt,
                'stop': end_dt,
                'sh_teams_meeting_url': join_url,
                'location': join_url,
                'videocall_location': join_url,
                'sh_is_teams_meeting': True,
                'sh_teams_sync_status': 'synced',
                'user_id': self.id,
                'alarm_ids': [(6, 0, alarm_ids)] if alarm_ids else [(5, 0, 0)],
            }
            
            if partner_ids:
                vals['partner_ids'] = [(6, 0, partner_ids)]

            if existing_event:
                if existing_event.write_date and ms_last_modified <= existing_event.write_date:
                    continue
                existing_event.with_context(sh_teams_sync_inbound=True).write(vals)
                odoo_event = existing_event
                updated_count += 1
            else:
                vals['sh_ms_calendar_event_id'] = ms_id
                vals['sh_teams_meeting_id'] = ms_id
                odoo_event = CalendarEvent.with_context(sh_teams_sync_inbound=True).create(vals)
                created_count += 1
                
            # Update Attendee RSVP Status in Odoo
            if attendee_responses and odoo_event.attendee_ids:
                for attendee in odoo_event.attendee_ids:
                    email = attendee.partner_id.email
                    if email and email.lower() in attendee_responses:
                        # Skip if state is already correct to prevent unnecessary writes
                        new_state = attendee_responses[email.lower()]
                        if attendee.state != new_state:
                            attendee.with_context(sh_teams_sync_inbound=True).write({'state': new_state})
                            
            # Process Attachments
            attachments = ms_event.get('attachments', [])
            for att in attachments:
                if att.get('@odata.type') == '#microsoft.graph.fileAttachment':
                    att_name = att.get('name')
                    content_bytes = att.get('contentBytes')
                    if att_name and content_bytes:
                        existing_att = IrAttachment.search([('res_model', '=', 'calendar.event'), ('res_id', '=', odoo_event.id), ('name', '=', att_name)], limit=1)
                        if not existing_att:
                            IrAttachment.create({'name': att_name, 'type': 'binary', 'datas': content_bytes, 'res_model': 'calendar.event', 'res_id': odoo_event.id})

        self.sh_ms_last_event_sync_at = fields.Datetime.now()
        
        success_msg = _('Delta Sync Complete! Created: %s, Updated: %s, Deleted: %s.') % (created_count, updated_count, deleted_count)
        LogModel.create({'operation_type': 'inbound', 'status': 'success', 'message': success_msg, 'user_id': self.id})

        if not is_cron:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Complete'),
                    'message': success_msg,
                    'type': 'success',
                    'sticky': False,
                }
            }
