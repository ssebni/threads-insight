"""Validated display values read from the signed-in profile's rendered DOM."""
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator
from google.cloud import firestore

from app.profile_followers import ProfileReading


class ProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile: ProfileReading
    views_label: str = Field(max_length=80)

    @model_validator(mode='after')
    def validate_snapshot(self):
        if not re.fullmatch(r'최근 조회수 (?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?(?:만|억)?회', self.views_label):
            raise ValueError('Invalid profile views label')
        if self.profile.observed_at < datetime.now(timezone.utc) - timedelta(minutes=5):
            raise ValueError('Profile snapshot is too old')
        return self


def save_snapshot(db, snapshot):
    # One commit keeps the two profile readings from the same collection together.
    base = db.collection('profile_insights')
    views = {
        'display_value': snapshot.views_label.removeprefix('최근 조회수 ').removesuffix('회'),
        'raw_label': snapshot.views_label,
        'source_url': snapshot.profile.source_url,
        'account_username': snapshot.profile.account_username,
        'observed_at': snapshot.profile.observed_at,
        'source': 'threads_profile_ui',
    }
    @firestore.transactional
    def commit(transaction):
        refs = [base.document('current_followers'), base.document('current_views')]
        previous = [ref.get(transaction=transaction) for ref in refs]
        if any(row.exists and row.to_dict().get('observed_at', snapshot.profile.observed_at)
               > snapshot.profile.observed_at for row in previous):
            raise ValueError('Newer profile reading already exists')
        transaction.set(refs[0], snapshot.profile.model_dump())
        transaction.set(refs[1], views)
        history_id = snapshot.profile.observed_at.isoformat().replace(':', '-')
        transaction.set(refs[0].collection('observations').document(history_id), snapshot.profile.model_dump())
        transaction.set(refs[1].collection('observations').document(history_id), views)
    commit(db.transaction())


def read_profile_views(db):
    row = db.collection('profile_insights').document('current_views').get(timeout=10)
    if not row.exists:
        return None
    value = row.to_dict()
    return value if value.get('source') == 'threads_profile_ui' else None
