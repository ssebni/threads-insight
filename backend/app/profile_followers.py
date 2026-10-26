"""Current profile follower observations are separate from daily historical totals."""
from datetime import datetime,timedelta,timezone
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,ValidationError,model_validator

class ProfileReading(BaseModel):
    model_config=ConfigDict(extra='forbid')
    account_username:Literal['nibetsi.zip']
    source_url:Literal['https://www.threads.com/@nibetsi.zip']
    source:Literal['threads_profile_ui']
    followers_count:int=Field(strict=True,ge=0)
    observed_at:datetime

    @model_validator(mode='after')
    def valid_time(self):
        if self.observed_at.tzinfo is None or self.observed_at>datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ValueError('Invalid profile observation time')
        return self


def read_profile_followers(db):
    snapshot=db.collection('profile_insights').document('current_followers').get(timeout=10)
    if not snapshot.exists:return None
    data=snapshot.to_dict()
    if not isinstance(data,dict):return None
    try:reading=ProfileReading.model_validate(data)
    except ValidationError:return None
    age=max(0,(datetime.now(timezone.utc)-reading.observed_at).total_seconds())
    return {**reading.model_dump(),'age_seconds':round(age),'stale':age>75*60}
