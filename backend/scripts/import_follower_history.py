"""Import exact daily follower totals read from the account insights chart."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.database import get_database


class DailyTotal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: date
    followers_count: int = Field(strict=True, ge=0)


class HistoryBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_username: Literal['nibetsi.zip']
    source_url: Literal['https://www.threads.com/insights']
    source: Literal['threads_account_insights_ui']
    observed_at: datetime
    items: list[DailyTotal] = Field(min_length=1, max_length=366)

    @model_validator(mode='after')
    def validate_batch(self):
        if not self.observed_at.tzinfo or self.observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('Invalid observation time')
        if len({row.date for row in self.items}) != len(self.items):
            raise ValueError('Duplicate date')
        if any(row.date > datetime.now(timezone.utc).date() for row in self.items):
            raise ValueError('Future date')
        return self


def import_history(db, data, write=False):
    batch, changed, skipped = db.batch(), 0, 0
    refs = [db.collection('follower_daily').document(row.date.isoformat()) for row in data.items]
    existing = {s.id: s for s in db.get_all(refs, timeout=30)}
    for row, ref in zip(data.items, refs):
        snapshot = existing[ref.id]
        previous = snapshot.to_dict() if snapshot.exists else None
        if previous and previous.get('observed_at') and previous['observed_at'] >= data.observed_at:
            skipped += 1
            continue
        payload = {'date': row.date.isoformat(), 'followers_count': row.followers_count,
                   'observed_at': data.observed_at, 'source': data.source,
                   'source_url': data.source_url, 'account_username': data.account_username}
        if snapshot.exists:
            batch.update(ref, payload, option=db.write_option(last_update_time=snapshot.update_time))
        else:
            batch.create(ref, payload)
        changed += 1
    if write and changed:
        batch.commit(timeout=30)
    if write:
        results = {s.id: s.to_dict() for s in db.get_all(refs, timeout=30)}
        for row in data.items:
            actual = results[row.date.isoformat()]
            if actual['observed_at'] == data.observed_at and actual['followers_count'] != row.followers_count:
                raise RuntimeError('Read-back mismatch')
    return {'saved' if write else 'would_save': changed, 'unchanged_or_newer': skipped, 'verified': write}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    with open(args.file, encoding='utf-8-sig') as source:
        payload = HistoryBatch.model_validate(json.load(source))
    print(json.dumps(import_history(get_database(), payload, args.write)))
