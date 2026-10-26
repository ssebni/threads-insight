"""Validate observations read from the signed-in Threads UI; never guesses values.

python -m scripts.import_screen_followers --file PATH [--write]
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database import get_database


def post_identity(url):
    parsed = urlparse(url)
    match = re.fullmatch(r'/@([^/]+)/post/([A-Za-z0-9_-]+)/?', parsed.path)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.threads.com', 'threads.com', 'www.threads.net', 'threads.net') or not match or parsed.username:
        raise ValueError('Unrecognized Threads post URL')
    return match.groups()


class ScreenObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    post_url: str
    insights_url: str
    follows: int = Field(strict=True, ge=0, le=10**10)
    observed_at: datetime
    source: str = Field(pattern=r'^threads_insights_ui$')

    @field_validator('observed_at')
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is None or value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('Observation requires a valid timezone-aware timestamp')
        return value

    @model_validator(mode='after')
    def matching_urls(self):
        _, code = post_identity(self.post_url)
        parsed = urlparse(self.insights_url)
        if parsed.scheme != 'https' or parsed.hostname not in ('www.threads.com', 'threads.com') or parsed.path.rstrip('/') != '/insights/post/' + code or parsed.username:
            raise ValueError('Insight URL does not identify the same post')
        return self


class ScreenBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_username: str = Field(pattern=r'^[A-Za-z0-9_.]+$')
    items: list[ScreenObservation] = Field(min_length=1, max_length=200)
    errors: list[dict] = Field(default_factory=list)

    @model_validator(mode='after')
    def same_account(self):
        identities = [post_identity(row.post_url) for row in self.items]
        if any(user != self.account_username for user, _ in identities):
            raise ValueError('Account mismatch')
        if len({code for _, code in identities}) != len(identities):
            raise ValueError('Duplicate post in observation batch')
        return self


def import_readings(db, batch_input, write=False):
    posts = {}
    for snapshot in db.collection('threads_posts').stream(timeout=30):
        data = snapshot.to_dict()
        if data.get('permalink'):
            identity = post_identity(data['permalink'])
            if identity in posts:
                raise ValueError('Ambiguous post mapping')
            posts[identity] = snapshot.id
    prepared = []
    for row in batch_input.items:
        post_id = posts.get(post_identity(row.post_url))
        if not post_id:
            raise ValueError('Observed post is not in Firestore; run the official API sync first')
        prepared.append((db.collection('post_follower_insights').document(post_id), {
            **row.model_dump(), 'post_id': post_id,
        }))
    existing = {s.reference.path: s for s in db.get_all([r for r, _ in prepared], timeout=30)}
    batch, changed, skipped = db.batch(), 0, 0
    for ref, data in prepared:
        snapshot = existing[ref.path]
        previous = snapshot.to_dict() if snapshot.exists else None
        if previous and previous['observed_at'] >= data['observed_at']:
            if previous['observed_at'] == data['observed_at'] and previous['follows'] != data['follows']:
                raise ValueError('Conflicting reading at the same observation time')
            skipped += 1
            continue
        if snapshot.exists:
            batch.update(ref, data, option=db.write_option(last_update_time=snapshot.update_time))
        else:
            batch.create(ref, data)
        history_id = hashlib.sha256(data['observed_at'].isoformat().encode()).hexdigest()[:24]
        batch.create(ref.collection('observations').document(history_id), data)
        changed += 1
    if write and changed:
        batch.commit(timeout=30)
    if write:
        for snapshot in db.get_all([r for r, _ in prepared], timeout=30):
            expected = next(d for r, d in prepared if r.path == snapshot.reference.path)
            actual = snapshot.to_dict()
            if not actual or actual['observed_at'] < expected['observed_at']:
                raise RuntimeError('Read-back verification failed')
            if actual['observed_at'] == expected['observed_at'] and actual['follows'] != expected['follows']:
                raise RuntimeError('Read-back count mismatch')
    return {'observed_posts': len(prepared), 'saved' if write else 'would_save': changed,
            'unchanged_or_older': skipped, 'screen_failures': len(batch_input.errors), 'verified': write}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    with open(args.file, encoding='utf-8-sig') as source:
        data = ScreenBatch.model_validate(json.load(source))
    print(json.dumps(import_readings(get_database(), data, args.write)))


if __name__ == '__main__':
    main()
