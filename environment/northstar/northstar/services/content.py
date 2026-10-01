"""Administratively managed homepage content."""

from __future__ import annotations

from sqlalchemy.orm import Session

from northstar.models import SiteSettings
from northstar.services import ValidationError

MAX_ANNOUNCEMENT_LENGTH = 500


def get_site_settings(db: Session) -> SiteSettings:
    settings = db.get(SiteSettings, 1)
    if settings is None:  # the migration inserts it; recreate if a test truncated it
        settings = SiteSettings(id=1, announcement_text="", announcement_active=False)
        db.add(settings)
        db.flush()
    return settings


def active_announcement(db: Session) -> str | None:
    settings = get_site_settings(db)
    text = settings.announcement_text.strip()
    return text if settings.announcement_active and text else None


def update_announcement(db: Session, text: str, active: bool) -> SiteSettings:
    text = (text or "").strip()
    if len(text) > MAX_ANNOUNCEMENT_LENGTH:
        raise ValidationError({"announcement_text": f"Keep the announcement under {MAX_ANNOUNCEMENT_LENGTH} characters."})
    if active and not text:
        raise ValidationError({"announcement_text": "Enter announcement text before showing it."})
    settings = get_site_settings(db)
    settings.announcement_text = text
    settings.announcement_active = active
    db.flush()
    return settings
