"""Validate and save a current follower count read from the rendered profile."""
import argparse,hashlib,json
from google.cloud import firestore
from app.database import get_database
from app.profile_followers import ProfileReading


def import_profile(db,reading,write=False):
    ref=db.collection('profile_insights').document('current_followers')
    data=reading.model_dump()
    if not write:return {'would_save':True,'followers_count':reading.followers_count}
    @firestore.transactional
    def save(transaction):
        old=ref.get(transaction=transaction)
        previous=old.to_dict() if old.exists else None
        if previous and previous['observed_at']>=reading.observed_at:
            if previous['observed_at']==reading.observed_at and previous['followers_count']!=reading.followers_count:
                raise ValueError('Conflicting profile count')
            return False
        transaction.set(ref,data)
        history_id=hashlib.sha256(reading.observed_at.isoformat().encode()).hexdigest()[:24]
        transaction.create(ref.collection('observations').document(history_id),data)
        return True
    saved=save(db.transaction())
    actual=ref.get(timeout=15).to_dict()
    if actual['observed_at']<reading.observed_at or (actual['observed_at']==reading.observed_at and actual['followers_count']!=reading.followers_count):
        raise RuntimeError('Profile follower read-back failed')
    return {'saved':saved,'followers_count':actual['followers_count'],'verified':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--file',required=True);parser.add_argument('--write',action='store_true');args=parser.parse_args()
    with open(args.file,encoding='utf-8-sig') as source:reading=ProfileReading.model_validate(json.load(source))
    print(json.dumps(import_profile(get_database(),reading,args.write)))
