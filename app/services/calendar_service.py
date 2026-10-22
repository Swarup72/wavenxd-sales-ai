import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.common import utc_now


def _escape_ics_text(text: str) -> str:
    """Escapes commas, semicolons, backslashes, and newlines per RFC 5545 §3.3.11."""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return text


def _fold_ics_line(line: str, max_length: int = 75) -> str:
    """Folds lines longer than max_length using CRLF + space per RFC 5545 §3.1."""
    if len(line.encode("utf-8")) <= max_length:
        return line

    parts: list[str] = []
    current = ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > max_length:
            parts.append(current)
            current = " " + char
        else:
            current = candidate
    if current:
        parts.append(current)
    return "\r\n".join(parts)


def generate_ics_calendar(
    customer_name: str,
    company_name: str,
    application: str | None,
    event_start: datetime,
    duration_minutes: int = 30,
    notes: str | None = None,
) -> str:
    """
    Generates a RFC 5545 compliant iCalendar (.ics) string for consultation appointment import.
    Transparently states that this invitation draft requires user addition to their personal calendar.
    """
    # Ensure event_start is timezone-aware
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)
    else:
        event_start = event_start.astimezone(timezone.utc)

    event_end = event_start + timedelta(minutes=duration_minutes)
    uid = f"{uuid.uuid4()}@wavenxd.com"
    dtstamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    dtstart = event_start.strftime("%Y%m%dT%H%M%SZ")
    dtend = event_end.strftime("%Y%m%dT%H%M%SZ")

    summary = f"WaveNxD Technical Consultation — {company_name}"
    description_lines = [
        f"WaveNxD Ultrasonic Spray & Atomization Consultation",
        f"Participant: {customer_name} ({company_name})",
        f"Target Application: {application or 'General Precision Atomization'}",
    ]
    if notes:
        description_lines.append(f"Customer Notes: {notes}")
    description_lines.extend([
        "",
        "Please import this .ics file into your calendar. A WaveNxD sales engineer will join at the scheduled time.",
        "WaveNxD Technologies Pvt. Ltd. | sales@wavenxd.com | www.wavenxd.com",
    ])
    description = "\n".join(description_lines)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WaveNxD Technologies//AI Sales Consultation//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_escape_ics_text(summary)}",
        f"DESCRIPTION:{_escape_ics_text(description)}",
        f"LOCATION:{_escape_ics_text('WaveNxD Virtual Consultation Room / Video Call')}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    folded_lines = [_fold_ics_line(l) for l in lines]
    return "\r\n".join(folded_lines) + "\r\n"


def generate_google_calendar_url(
    customer_name: str,
    company_name: str,
    application: str | None,
    event_start: datetime,
    duration_minutes: int = 30,
) -> str:
    """Generates an explicit, URL-encoded Google Calendar event creation link."""
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)
    else:
        event_start = event_start.astimezone(timezone.utc)

    event_end = event_start + timedelta(minutes=duration_minutes)
    start_str = event_start.strftime("%Y%m%dT%H%M%SZ")
    end_str = event_end.strftime("%Y%m%dT%H%M%SZ")

    title = f"WaveNxD Technical Consultation — {company_name}"
    details = (
        f"WaveNxD Technical Consultation for {customer_name} ({company_name}).\n"
        f"Application: {application or 'Precision Atomization'}\n"
        "WaveNxD Technologies Pvt. Ltd. — sales@wavenxd.com"
    )

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_str}/{end_str}",
        "details": details,
        "location": "WaveNxD Virtual Consultation",
    }
    return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"
