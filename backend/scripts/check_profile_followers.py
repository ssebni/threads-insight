import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock,patch
from pydantic import ValidationError
from app.profile_followers import ProfileReading,read_profile_followers
from app.followers import collect_followers
from app.dashboard import followers_series

class ProfileChecks(unittest.TestCase):
    def reading(self,**changes):
        return {'account_username':'nibetsi.zip','source_url':'https://www.threads.com/@nibetsi.zip','source':'threads_profile_ui','followers_count':132,'observed_at':datetime.now(timezone.utc),**changes}
    def test_strict_count_and_identity(self):
        for changes in ({'followers_count':'132'},{'followers_count':True},{'followers_count':-1},{'account_username':'another'},{'source_url':'https://example.com'},{'observed_at':datetime.now()}):
            with self.assertRaises(ValidationError):ProfileReading.model_validate(self.reading(**changes))
        self.assertEqual(ProfileReading.model_validate(self.reading(followers_count=0)).followers_count,0)
        self.assertEqual(ProfileReading.model_validate(self.reading(followers_count=131)).followers_count,131)
    def test_stale_profile_is_preserved_and_flagged(self):
        db=Mock();snapshot=db.collection.return_value.document.return_value.get.return_value
        snapshot.exists=True;snapshot.to_dict.return_value=self.reading(observed_at=datetime.now(timezone.utc)-timedelta(hours=2))
        data=read_profile_followers(db);self.assertEqual(data['followers_count'],132);self.assertTrue(data['stale'])
    def test_api_collection_cannot_overwrite_profile(self):
        db=Mock();api=Mock(return_value={'data':[{'name':'followers_count','total_value':{'value':129}}]})
        self.assertTrue(collect_followers(Mock(),db,api))
        db.collection.assert_called_once_with('follower_daily')
    def test_current_profile_separate_from_daily_graph(self):
        db=Mock();snapshot=Mock(id='2026-10-18');snapshot.to_dict.return_value={'followers_count':129}
        db.collection.return_value.stream.return_value=[snapshot]
        with patch('app.dashboard.read_profile_followers',return_value={'followers_count':132}):
            result=followers_series(db)
        self.assertEqual(result['current_count'],132)
        self.assertEqual(result['points'][-1]['followers_count'],129)
        self.assertIsNone(result['points'][-1]['change'])

if __name__=='__main__':unittest.main()
