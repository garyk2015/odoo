from odoo import models, fields, api, _
from odoo.addons.calendar.models.calendar_recurrence import weekday_to_field
from odoo.exceptions import UserError
import logging
import asyncio
from datetime import datetime, timezone, timedelta
import pytz
import msal
from msgraph.graph_service_client import GraphServiceClient
import time
import platform
from azure.core.credentials import AccessToken

# Monkey-patch platform.version, release, and uname to strip trailing newlines 
# which cause httpx header errors in msgraph SDK
_orig_platform_version = platform.version
platform.version = lambda: _orig_platform_version().strip()

_orig_platform_release = platform.release
platform.release = lambda: _orig_platform_release().strip()

_orig_platform_uname = platform.uname
def _patched_platform_uname():
    u = _orig_platform_uname()
    return platform.uname_result(
        u.system.strip() if hasattr(u, 'system') else u[0].strip(),
        u.node.strip() if hasattr(u, 'node') else u[1].strip(),
        u.release.strip() if hasattr(u, 'release') else u[2].strip(),
        u.version.strip() if hasattr(u, 'version') else u[3].strip(),
        u.machine.strip() if hasattr(u, 'machine') else u[4].strip()
    )
platform.uname = _patched_platform_uname

from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.generated.models.meeting_participants import MeetingParticipants
from msgraph.generated.models.meeting_participant_info import MeetingParticipantInfo
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.event import Event
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.location import Location
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.online_meeting_provider_type import OnlineMeetingProviderType
from msgraph.generated.models.patterned_recurrence import PatternedRecurrence
from msgraph.generated.models.recurrence_pattern import RecurrencePattern
from msgraph.generated.models.recurrence_pattern_type import RecurrencePatternType
from msgraph.generated.models.recurrence_range import RecurrenceRange
from msgraph.generated.models.recurrence_range_type import RecurrenceRangeType
from msgraph.generated.models.day_of_week import DayOfWeek
from msgraph.generated.models.week_index import WeekIndex

_logger = logging.getLogger(__name__)

GRAPH_SCOPES = [
    'https://graph.microsoft.com/OnlineMeetings.ReadWrite',
    'https://graph.microsoft.com/Calendars.ReadWrite',
    'https://graph.microsoft.com/User.Read',
]

DAY_FIELD_TO_GRAPH = {
    'mon': DayOfWeek.Monday,
    'tue': DayOfWeek.Tuesday,
    'wed': DayOfWeek.Wednesday,
    'thu': DayOfWeek.Thursday,
    'fri': DayOfWeek.Friday,
    'sat': DayOfWeek.Saturday,
    'sun': DayOfWeek.Sunday,
}

DAY_CODE_TO_GRAPH = {
    'MON': DayOfWeek.Monday,
    'TUE': DayOfWeek.Tuesday,
    'WED': DayOfWeek.Wednesday,
    'THU': DayOfWeek.Thursday,
    'FRI': DayOfWeek.Friday,
    'SAT': DayOfWeek.Saturday,
    'SUN': DayOfWeek.Sunday,
}

WEEK_INDEX_MAP = {
    '1': WeekIndex.First,
    '2': WeekIndex.Second,
    '3': WeekIndex.Third,
    '4': WeekIndex.Fourth,
    '-1': WeekIndex.Last,
}


class TeamsRefreshTokenCredential:
    """Minimal TokenCredential wrapper around MSAL refresh token flow."""

    def __init__(self, company, user):
        if not user.sh_teams_refresh_token:
            raise UserError(_('Please connect your Microsoft account in your user preferences.'))

        authority = f'https://login.microsoftonline.com/{company.sh_teams_tenant_id}'

        self._client_app = msal.ConfidentialClientApplication(
            client_id=company.sh_teams_client_id,
            authority=authority,
            client_credential=company.sh_teams_client_secret,
        )
        self._refresh_token = user.sh_teams_refresh_token
        self._user = user.sudo()

    def _flatten_scopes(self, scopes):
        resolved_scopes = []
        for scope in scopes:
            if isinstance(scope, (list, tuple, set)):
                resolved_scopes.extend(scope)
            else:
                resolved_scopes.append(scope)
        return resolved_scopes or GRAPH_SCOPES

    def get_token(self, *scopes, **kwargs):  # Azure SDK contract
        scope_list = self._flatten_scopes(scopes)
        token_result = self._client_app.acquire_token_by_refresh_token(
            refresh_token=self._refresh_token,
            scopes=scope_list,
        )

        if 'access_token' not in token_result:
            error_msg = token_result.get('error_description') or token_result.get('error') or _('Unknown error')
            raise UserError(_('Failed to authenticate with Microsoft: %s') % error_msg)

        expires_in = int(token_result.get('expires_in', 3600))
        expires_on = int(time.time()) + expires_in
        new_refresh = token_result.get('refresh_token')

        vals = {
            'sh_teams_access_token': token_result['access_token'],
            'sh_teams_token_expiry': datetime.now() + timedelta(seconds=expires_in),
        }
        if new_refresh:
            vals['sh_teams_refresh_token'] = new_refresh
            self._refresh_token = new_refresh

        self._user.write(vals)

        return AccessToken(token_result['access_token'], expires_on)


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    sh_teams_meeting_url = fields.Char(string='Teams Meeting Link', readonly=True)
    sh_teams_meeting_id = fields.Char(string='Teams Meeting ID', readonly=True)
    sh_ms_calendar_event_id = fields.Char(string='MS Calendar Event ID', readonly=True)
    sh_is_teams_meeting = fields.Boolean(string='Teams Meeting', default=False,readonly=True)
    sh_teams_sync_status = fields.Selection([
        ('pending', 'Pending'),
        ('synced', 'Synced'),
        ('error', 'Error')
    ], string='Teams Sync Status', default='pending')
    sh_teams_error_message = fields.Text(string='Teams Error Message')

    def _get_graph_client(self, user=None):
        """Get authenticated Microsoft Graph client using stored refresh token"""
        company = self.env.company
        user = (user or self.env.user).sudo()

        if not all([company.sh_teams_client_id, company.sh_teams_client_secret, company.sh_teams_tenant_id]):
            raise UserError(_('Please configure Microsoft Teams credentials in Settings.'))

        if not user.sh_teams_refresh_token:
            raise UserError(_('User %s is not connected to Microsoft Teams.') % (user.name or _('Unknown')))

        try:
            credential = TeamsRefreshTokenCredential(company, user)
            graph_client = GraphServiceClient(credentials=credential, scopes=GRAPH_SCOPES)

            _logger.info('Microsoft Graph client created successfully')
            return graph_client

        except Exception as e:
            _logger.error(f'Error creating Graph client: {str(e)}')
            raise UserError(_('Failed to authenticate with Microsoft: %s') % str(e))

    def action_create_teams_meeting(self):
        """Create a Teams meeting for this calendar event"""
        self.ensure_one()
        
        try:
            result = asyncio.run(self._async_create_teams_meeting())

            if result and result.join_web_url:
                _logger.info(f'Teams meeting created successfully: {result.id}')
                
                self.sudo().write({
                    'sh_teams_meeting_url': result.join_web_url,
                    'sh_teams_meeting_id': result.id,
                    'sh_is_teams_meeting': True,
                    'sh_teams_sync_status': 'synced',
                    'sh_teams_error_message': False,
                    'location': result.join_web_url,
                    'videocall_location': result.join_web_url,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Teams meeting created successfully!'),
                        'type': 'success',
                        'sticky': False,
                        'next': {
                            'type': 'ir.actions.client',
                            'tag': 'reload',
                        },                    
                    }
                }
            else:
                raise UserError(_('Failed to create Teams meeting: No response from server'))
                
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error creating Teams meeting: {error_msg}')
            self.sudo().write({
                'sh_teams_sync_status': 'error',
                'sh_teams_error_message': error_msg
            })
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'error',
                'message': f"Error creating Teams meeting: {error_msg}",
                'calendar_event_id': self.id,
                'user_id': self.env.user.id
            })
            raise UserError(_('Error creating Teams meeting: %s') % error_msg)

    async def _async_create_teams_meeting(self):
        """Async helper that performs Graph calls for meeting creation."""
        graph_client = self._get_graph_client()
        
        # Prepare online meeting object
        online_meeting = self._prepare_online_meeting()

        # Create the online meeting using Graph SDK
        _logger.info(f'Creating Teams meeting for event: {self.name}')
        result = await graph_client.me.online_meetings.post(online_meeting)

        if result and result.join_web_url:
            # Also create calendar event in Microsoft Calendar within same loop
            await self._create_microsoft_calendar_event(graph_client, result)

        return result

    def _prepare_online_meeting(self):
        """Prepare OnlineMeeting object for Teams meeting creation"""
        online_meeting = OnlineMeeting()
        online_meeting.subject = self.name
        online_meeting.start_date_time = self._utc_datetime(self.start)
        online_meeting.end_date_time = self._utc_datetime(self.stop)
        online_meeting.participants = self._prepare_meeting_participants()
        
        _logger.info(f'Prepared online meeting object for: {self.name}')
        return online_meeting

    def _prepare_meeting_participants(self):
        """Prepare MeetingParticipants payload ensuring removals propagate."""
        participants = MeetingParticipants()
        attendee_infos = []

        for partner in self.partner_ids:
            if partner.email:
                participant_info = MeetingParticipantInfo()

                # Create identity set
                identity_set = IdentitySet()
                identity = Identity()
                identity.display_name = partner.name
                identity_set.user = identity

                participant_info.identity = identity_set
                participant_info.upn = partner.email
                attendee_infos.append(participant_info)

        participants.attendees = attendee_infos
        return participants

    def _prepare_calendar_event_attendees(self):
        """Return Attendee payload list for Microsoft calendar events."""
        attendees = []
        for partner in self.partner_ids:
            if partner.email:
                attendee = Attendee()
                email_address = EmailAddress()
                email_address.address = partner.email
                email_address.name = partner.name
                attendee.email_address = email_address
                attendee.type = AttendeeType.Required
                attendees.append(attendee)
        return attendees

    def _get_event_timezone_name(self):
        """Determine timezone configured in Odoo for the event/user."""
        return (
            self.env.context.get('tz')
            or self.event_tz
            or getattr(self.recurrence_id, 'event_tz', False)
            or self.user_id.tz
            or self.env.user.tz
            or self.env.company.resource_calendar_id.tz
            or 'UTC'
        )

    def _graph_datetime(self, dt, tz_name=None):
        """Return datetime string localized in requested timezone for Graph."""
        if not dt:
            return None

        tz_name = tz_name or self._get_event_timezone_name()
        try:
            target_tz = pytz.timezone(tz_name)
        except Exception:
            target_tz = pytz.UTC
            tz_name = 'UTC'

        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        else:
            dt = dt.astimezone(pytz.UTC)

        localized_dt = dt.astimezone(target_tz)
        return localized_dt.strftime('%Y-%m-%dT%H:%M:%S')

    def _utc_datetime(self, dt):
        """Return Graph-friendly UTC datetime string."""
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        utc_dt = dt.astimezone(timezone.utc)
        return utc_dt

    def _localize_datetime(self, dt, tz_name):
        """Return datetime localized to requested timezone."""
        if not dt:
            return None
        try:
            target_tz = pytz.timezone(tz_name)
        except Exception:
            target_tz = pytz.UTC
        if dt.tzinfo is None:
            localized = pytz.UTC.localize(dt)
        else:
            localized = dt.astimezone(pytz.UTC)
        return localized.astimezone(target_tz)

    def _is_recurrence_master(self):
        """Return True if this record represents the recurrence master."""
        if not self.recurrency or not self.recurrence_id:
            return False
        base_event = self.recurrence_id.base_event_id
        return not base_event or base_event == self

    def _build_graph_recurrence(self, tz_name, localized_start):
        """Build PatternedRecurrence payload from Odoo recurrence fields."""
        if not self._is_recurrence_master():
            return None
        recurrence = self.recurrence_id
        pattern = self._build_graph_recurrence_pattern(recurrence, localized_start)
        range_vals = self._build_graph_recurrence_range(recurrence, tz_name, localized_start)
        if not pattern or not range_vals:
            return None
        graph_recurrence = PatternedRecurrence()
        graph_recurrence.pattern = pattern
        graph_recurrence.range = range_vals
        return graph_recurrence

    def _build_graph_recurrence_pattern(self, recurrence, localized_start):
        """Translate Odoo recurrence pattern to Graph RecurrencePattern."""
        if not recurrence or not localized_start:
            return None
        pattern = RecurrencePattern()
        pattern.interval = max(recurrence.interval or 1, 1)
        freq = recurrence.rrule_type or 'weekly'

        if freq == 'daily':
            pattern.type = RecurrencePatternType.Daily
        elif freq == 'weekly':
            pattern.type = RecurrencePatternType.Weekly
            week_days = self._get_graph_week_days(recurrence)
            if not week_days:
                week_days = [self._fallback_day_enum(localized_start)]
            pattern.days_of_week = week_days
            pattern.first_day_of_week = DayOfWeek.Monday
        elif freq == 'monthly':
            if recurrence.month_by == 'day':
                pattern.type = RecurrencePatternType.RelativeMonthly
                day_enum = self._map_weekday_code(recurrence.weekday) or self._fallback_day_enum(localized_start)
                pattern.days_of_week = [day_enum]
                pattern.index = self._map_week_index(recurrence.byday) or WeekIndex.First
            else:
                pattern.type = RecurrencePatternType.AbsoluteMonthly
                pattern.day_of_month = recurrence.day or localized_start.day
        elif freq == 'yearly':
            if recurrence.month_by == 'day':
                pattern.type = RecurrencePatternType.RelativeYearly
                day_enum = self._map_weekday_code(recurrence.weekday) or self._fallback_day_enum(localized_start)
                pattern.days_of_week = [day_enum]
                pattern.index = self._map_week_index(recurrence.byday) or WeekIndex.First
                pattern.month = localized_start.month
            else:
                pattern.type = RecurrencePatternType.AbsoluteYearly
                pattern.day_of_month = recurrence.day or localized_start.day
                pattern.month = localized_start.month
        else:
            return None

        return pattern

    def _build_graph_recurrence_range(self, recurrence, tz_name, localized_start):
        """Translate recurrence range definition to Graph representation."""
        if not recurrence or not localized_start:
            return None
        range_vals = RecurrenceRange()
        range_vals.recurrence_time_zone = tz_name
        range_vals.start_date = localized_start.date()

        end_type = recurrence.end_type or 'forever'
        if end_type == 'end_date' and recurrence.until:
            range_vals.type = RecurrenceRangeType.EndDate
            range_vals.end_date = recurrence.until
        elif end_type == 'count':
            range_vals.type = RecurrenceRangeType.Numbered
            range_vals.number_of_occurrences = max(recurrence.count or 1, 1)
        else:
            range_vals.type = RecurrenceRangeType.NoEnd
        return range_vals

    def _get_graph_week_days(self, recurrence):
        """Return selected Weekdays as Graph enum list."""
        if not recurrence:
            return []
        days = []
        for field_name, day_enum in DAY_FIELD_TO_GRAPH.items():
            if getattr(recurrence, field_name):
                days.append(day_enum)
        return days

    def _map_weekday_code(self, code):
        """Map Odoo weekday string (MON) to Graph DayOfWeek enum."""
        if not code:
            return None
        return DAY_CODE_TO_GRAPH.get(code.upper())

    def _map_week_index(self, value):
        """Convert recurrence byday numbering to Graph WeekIndex."""
        if not value:
            return None
        return WEEK_INDEX_MAP.get(str(value))

    def _fallback_day_enum(self, localized_start):
        """Return default day enum based on event start."""
        if not localized_start:
            return DayOfWeek.Monday
        fallback_field = weekday_to_field(localized_start.weekday())
        return DAY_FIELD_TO_GRAPH.get(fallback_field, DayOfWeek.Monday)

    async def _create_microsoft_calendar_event(self, graph_client, meeting_info):
        """Create event in Microsoft Calendar using Graph SDK"""
        try:
            # Create Event object
            event = Event()
            event.subject = self.name
            
            # Set body with meeting link
            body = ItemBody()
            body.content_type = BodyType.Html
            description = self.description or ''
            body.content = f'{description}'
            event.body = body
            
            # Set start time
            tz_name = self._get_event_timezone_name() or 'UTC'
            localized_start = self._localize_datetime(self.start, tz_name)
            start = DateTimeTimeZone()
            start.date_time = self._graph_datetime(self.start, tz_name)
            start.time_zone = tz_name
            event.start = start
            
            # Set end time
            end = DateTimeTimeZone()
            end.date_time = self._graph_datetime(self.stop, tz_name)
            end.time_zone = tz_name
            event.end = end
            
            # Set location
            location = Location()
            location.display_name = 'Microsoft Teams Meeting'
            event.location = location
            
            # Set attendees (always push list to reflect removals)
            event.attendees = self._prepare_calendar_event_attendees()
            
            # Mark as online meeting
            event.is_online_meeting = True
            event.online_meeting_provider = OnlineMeetingProviderType.TeamsForBusiness
            # event.online_meeting_url = meeting_info.join_web_url

            recurrence = self._build_graph_recurrence(tz_name, localized_start)
            if recurrence:
                event.recurrence = recurrence
            
            # Create the calendar event
            _logger.info('Creating calendar event in Microsoft Calendar')
            target_calendar_id = self.env.user.sh_target_ms_calendar_id.ms_calendar_id
            if target_calendar_id:
                result = await graph_client.me.calendars.by_calendar_id(target_calendar_id).events.post(event)
            else:
                result = await graph_client.me.events.post(event)
            
            if result and result.id:
                self.sudo().write({'sh_ms_calendar_event_id': result.id})
                _logger.info(f'Calendar event created with ID: {result.id}')
                self.env['sh.ms.teams.sync.log'].create({
                    'operation_type': 'outbound',
                    'status': 'success',
                    'message': f"Successfully created Teams meeting (ID: {result.id})",
                    'calendar_event_id': self.id,
                    'user_id': self.env.user.id
                })
            
        except Exception as e:
            _logger.warning(f'Failed to create calendar event: {str(e)}')
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'error',
                'message': f"Failed to push to Microsoft Calendar: {str(e)}",
                'calendar_event_id': self.id,
                'user_id': self.env.user.id
            })

    def action_sync_with_teams(self):
        """Sync calendar events with Microsoft Teams"""
        for event in self:
            if event.sh_is_teams_meeting and event.sh_teams_meeting_id:
                event._update_teams_meeting()
            elif not event.sh_is_teams_meeting:
                event.action_create_teams_meeting()

    def _update_teams_meeting(self):
        """Update existing Teams meeting"""
        self.ensure_one()
        
        try:
            result = asyncio.run(self._async_update_teams_meeting())
            
            if result:
                self.sudo().write({
                    'sh_teams_sync_status': 'synced',
                    'sh_teams_meeting_url': result.join_web_url,
                    'sh_teams_meeting_id': result.id or self.sh_teams_meeting_id,
                    'sh_is_teams_meeting': True,
                    'sh_teams_error_message': False,
                    'location': result.join_web_url or self.location,
                })
                _logger.info(f'Teams meeting updated successfully: {self.sh_teams_meeting_id}')
            else:
                raise UserError(_('Failed to update Teams meeting'))
                
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error updating Teams meeting: {error_msg}')
            self.sudo().write({
                'sh_teams_sync_status': 'error',
                'sh_teams_error_message': error_msg
            })
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'error',
                'message': f"Error updating Teams meeting: {error_msg}",
                'calendar_event_id': self.id,
                'user_id': self.env.user.id
            })

    async def _async_update_teams_meeting(self):
        """Async helper that performs Graph calls for meeting updates."""
        graph_client = self._get_graph_client()
        
        # Prepare updated meeting data
        online_meeting = self._prepare_online_meeting()
        
        # Update the online meeting
        _logger.info(f'Updating Teams meeting: {self.sh_teams_meeting_id}')
        result = await graph_client.me.online_meetings.by_online_meeting_id(
            self.sh_teams_meeting_id
        ).patch(online_meeting)
        
        # Also update calendar event if exists
        if result and self.sh_ms_calendar_event_id:
            await self._update_microsoft_calendar_event(graph_client)

        return result

    async def _update_microsoft_calendar_event(self, graph_client):
        """Update existing calendar event in Microsoft Calendar"""
        try:
            event = Event()
            event.subject = self.name
            
            # Set body
            body = ItemBody()
            body.content_type = BodyType.Html
            description = self.description or ''
            body.content = f'{description}'
            event.body = body
            
            tz_name = self._get_event_timezone_name() or 'UTC'
            localized_start = self._localize_datetime(self.start, tz_name)

            # Set start time
            start = DateTimeTimeZone()
            start.date_time = self._graph_datetime(self.start, tz_name)
            start.time_zone = tz_name
            event.start = start
            
            # Set end time
            end = DateTimeTimeZone()
            end.date_time = self._graph_datetime(self.stop, tz_name)
            end.time_zone = tz_name
            event.end = end
            
            # Update attendees even if empty so removals propagate
            event.attendees = self._prepare_calendar_event_attendees()

            recurrence = self._build_graph_recurrence(tz_name, localized_start)
            if recurrence:
                event.recurrence = recurrence
            
            # Update the event
            _logger.info(f'Updating calendar event: {self.sh_ms_calendar_event_id}')
            await graph_client.me.events.by_event_id(
                self.sh_ms_calendar_event_id
            ).patch(event)
            
            _logger.info(f'Calendar event updated: {self.sh_ms_calendar_event_id}')
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'success',
                'message': f"Successfully updated Teams meeting (ID: {self.sh_ms_calendar_event_id})",
                'calendar_event_id': self.id,
                'user_id': self.env.user.id
            })
            
        except Exception as e:
            _logger.warning(f'Failed to update calendar event: {str(e)}')
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'error',
                'message': f"Failed to push update to Microsoft Calendar: {str(e)}",
                'calendar_event_id': self.id,
                'user_id': self.env.user.id
            })



    def action_delete_teams_meeting(self):
        """Delete Teams meeting when event is deleted"""
        events_to_cleanup = self._get_events_for_teams_cleanup()
        processed_meetings = set()
        for event in events_to_cleanup:
            meeting_id = event.sh_teams_meeting_id
            if not meeting_id or meeting_id in processed_meetings:
                continue
            processed_meetings.add(meeting_id)
            try:
                asyncio.run(event._delete_teams_meeting())
                event.sudo().write({
                    'sh_teams_meeting_id':False,
                    'sh_teams_meeting_url':False,
                    'sh_is_teams_meeting':False,
                    'sh_teams_error_message':False,
                    'sh_teams_sync_status':'pending',
                    'sh_ms_calendar_event_id':False,
                    'location':False
                })
            except Exception as e:
                _logger.warning(f'Failed to delete Teams meeting: {str(e)}')
                self.env['sh.ms.teams.sync.log'].create({
                    'operation_type': 'outbound',
                    'status': 'error',
                    'message': f"Failed to delete Teams meeting for event '{event.name}': {str(e)}",
                    'user_id': self.env.user.id
                })

    def unlink(self):
        # Prevent non-organizers from deleting the event
        for record in self:
            if not self.env.su and not self._context.get('sh_teams_sync_inbound') and record.user_id and record.user_id != self.env.user:
                raise UserError(_("You cannot delete a calendar event organized by another user."))

        if self.env.user.sh_teams_meeting_auto_unlink:
            self.action_delete_teams_meeting()
        return super().unlink()

    def _get_events_for_teams_cleanup(self):
        """Return recordset of events whose Teams resources must be deleted."""
        events = self.filtered(lambda e: e.sh_is_teams_meeting and e.sh_teams_meeting_id)
        recurrences = self.mapped('recurrence_id').filtered(lambda r: r.base_event_id and r.base_event_id.sh_is_teams_meeting)
        base_events = recurrences.mapped('base_event_id')
        return (events | base_events).filtered(lambda e: e.sh_teams_meeting_id)

    async def _delete_teams_meeting(self):
        """Delete Teams meeting from Microsoft"""
        self.ensure_one()
        
        try:
            graph_client = self._get_graph_client()
            
            # Delete online meeting
            if self.sh_teams_meeting_id and not self.sh_teams_meeting_id.startswith('AAMk'):
                try:
                    _logger.info(f'Deleting Teams meeting: {self.sh_teams_meeting_id}')
                    await graph_client.me.online_meetings.by_online_meeting_id( 
                        self.sh_teams_meeting_id
                    ).delete()
                except Exception as e:
                    _logger.warning(f'Failed to delete online meeting {self.sh_teams_meeting_id}: {str(e)}')
            
            # Delete calendar event if exists
            if self.sh_ms_calendar_event_id:
                try:
                    _logger.info(f'Deleting calendar event: {self.sh_ms_calendar_event_id}')
                    await graph_client.me.events.by_event_id(
                        self.sh_ms_calendar_event_id
                    ).delete()
                except Exception as e:
                    _logger.warning(f'Failed to delete calendar event: {str(e)}')
            
            _logger.info(f'Teams meeting deleted: {self.sh_teams_meeting_id}')
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'success',
                'message': f"Successfully deleted Teams meeting (ID: {self.sh_teams_meeting_id})",
                'user_id': self.env.user.id
            })
            
        except Exception as e:
            _logger.warning(f'Failed to delete Teams meeting: {str(e)}')
            self.env['sh.ms.teams.sync.log'].create({
                'operation_type': 'outbound',
                'status': 'error',
                'message': f"Failed to push deletion to Microsoft Calendar: {str(e)}",
                'user_id': self.env.user.id
            })
            raise


    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get('sh_teams_sync_inbound'):
            return records
            
        if self.env.user.sh_teams_meeting_auto_create:
            for record in records:
                record.action_create_teams_meeting()
        return records

    def write(self, vals):
        # Fields that only the organizer should be allowed to change
        restricted_fields = {
            'name', 'start', 'stop', 'allday', 'start_date', 'stop_date',
            'sh_is_teams_meeting', 'sh_teams_meeting_url', 'sh_teams_meeting_id', 
            'location', 'description'
        }
        
        # Check if any restricted fields are being modified
        if restricted_fields.intersection(vals.keys()):
            for record in self:
                # If the event has an organizer and it's not the current user
                if not self.env.su and not self._context.get('sh_teams_sync_inbound') and record.user_id and record.user_id != self.env.user:
                    raise UserError(_("You cannot modify the core details of an event organized by another user."))

        res = super().write(vals)
        if {'sh_teams_meeting_url','sh_teams_meeting_id','sh_is_teams_meeting','sh_teams_sync_status','sh_teams_error_message','location'}.intersection(vals.keys()):
            return res

        if self.env.context.get('sh_teams_sync_inbound'):
            return res

        if self.env.user.sh_teams_meeting_auto_write:
            for record in self:
                # Make auto update only if any teams meeting created from this record
                if record.sh_is_teams_meeting and record.sh_teams_meeting_id:
                    record._update_teams_meeting()
        return res
