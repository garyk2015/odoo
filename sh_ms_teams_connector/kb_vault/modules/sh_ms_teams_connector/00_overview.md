# Odoo Microsoft Teams Connector — Overview
Status: [ACTIVE]
Version: 19.0.1.0.1
Last Updated: 2026-06-05

## Purpose
This module solves the business problem of managing Microsoft Teams meetings and syncing events to Microsoft Outlook Calendar directly from the Odoo Calendar, providing seamless scheduling for remote work, virtual meetings, and business productivity.

## What It Achieves
- Automatically generates Microsoft Teams meeting links when a calendar event is created in Odoo.
- Synchronizes the event with Microsoft Outlook Calendar.
- Reflects any updates or deletions of Odoo events in Microsoft Teams.
- Provides manual or automatic sync controls via User preferences.
- Allows users to join Teams meetings directly from Odoo using the generated link.

## Key Concepts
- **OAuth 2.0 / MSAL**: Connects Odoo users to their Microsoft accounts via Microsoft Authentication Library, acquiring and refreshing access tokens.
- **Graph API**: Interacts with Azure Graph API endpoints to read/write Online Meetings and Calendar events.
- **Teams Sync**: Bi-directional integration where Odoo events are created, updated, or removed in the MS Graph backend.

## Module Map
[[01_architecture]] | [[02_data_flow]] | [[03_models]] | [[04_views_xml]] | [[05_owl_components]] | [[06_controllers]] | [[07_csv_data]] | [[08_dependencies]] | [[09_known_issues]]
