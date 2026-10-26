"""Offline checks for official headline scope, partial failures and stale readings."""
import os,unittest,asyncio
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock,patch,AsyncMock
os.environ['THREADS_AUTO_SYNC']='false'
from app.account_views import parse_account_views,collect_account_views,read_account_views
from app.dashboard import dashboard_for

class AccountViewsChecks(unittest.TestCase):
    def payload(self,values):
        return {'data':[{'name':'views','values':[{'value':v,'end_time':f'2026-10-{i+1:02d}T07:00:00Z'} for i,v in enumerate(values)]}]}

    def test_exact_sum_and_zero(self):
        self.assertEqual(parse_account_views(self.payload([12,0,34]))[0],46)
        self.assertEqual(parse_account_views(self.payload([0]))[0],0)

    def test_rejects_missing_partial_bool_negative_and_duplicate(self):
        for values in ([],[None],[True],[-1],[1,2.5]):
            with self.subTest(values=values),self.assertRaises(ValueError):
                parse_account_views(self.payload(values))
        p=self.payload([1,2]);p['data'][0]['values'][1]['end_time']=p['data'][0]['values'][0]['end_time']
        with self.assertRaises(ValueError):parse_account_views(p)

    def test_requested_period_and_atomic_save(self):
        api=Mock(return_value=self.payload([17,5]));db=Mock()
        result=collect_account_views(Mock(),db,api)
        self.assertEqual(result['views'],22)
        params=api.call_args.args[2]
        self.assertEqual(params['until']-params['since'],30*86400)
        self.assertEqual(api.call_args.args[1],'me/threads_insights')
        db.collection.return_value.document.return_value.set.assert_called_once()

    def test_invalid_response_leaves_last_good_value(self):
        db=Mock()
        with self.assertRaises(ValueError):collect_account_views(Mock(),db,Mock(return_value=self.payload([1,None])))
        db.collection.assert_not_called()

    def test_stale_snapshot_is_preserved(self):
        db=Mock();snap=db.collection.return_value.document.return_value.get.return_value
        snap.exists=True;snap.to_dict.return_value={'views':99,'period_days':30,'collected_at':datetime.now(timezone.utc)-timedelta(minutes=5)}
        self.assertTrue(read_account_views(db)['stale'])
        self.assertEqual(read_account_views(db)['views'],99)

    def test_headline_uses_official_not_lifetime_sum(self):
        db=Mock();db.collection.return_value.stream.return_value=[]
        with patch('app.dashboard.read_account_views',return_value={'views':42}),patch('app.dashboard.followers_series',return_value={}):
            r=dashboard_for(db)
        self.assertEqual(r['totals']['views'],42)
        self.assertIsNone(r['view_breakdown']['total'])
        with patch('app.dashboard.read_account_views',return_value=None),patch('app.dashboard.followers_series',return_value={}):
            self.assertIsNone(dashboard_for(db)['totals']['views'])

class AccountPollChecks(unittest.IsolatedAsyncioTestCase):
    async def test_worker_refreshes_without_post_scan(self):
        from app import threads_sync as sync
        before=dict(sync.state)
        try:
            with patch('app.threads_sync.refresh_account_views',return_value='verified-time') as refresh,patch('app.threads_sync.sync_once') as posts,patch('app.threads_sync.asyncio.sleep',new=AsyncMock(side_effect=asyncio.CancelledError)) as sleep:
                with self.assertRaises(asyncio.CancelledError):await sync.poll_account_views()
                refresh.assert_called_once();posts.assert_not_called()
                self.assertEqual(sync.state['account_views_last_success_at'],'verified-time')
                sleep.assert_awaited_once_with(sync.interval_seconds())
        finally:sync.state.update(before)

    async def test_rate_limit_backs_off_and_preserves_success_time(self):
        from app import threads_sync as sync
        before=dict(sync.state);sync.state['account_views_last_success_at']='last-good'
        try:
            with patch('app.threads_sync.refresh_account_views',side_effect=sync.SyncError('threads_rate_limited')),patch('app.threads_sync.asyncio.sleep',new=AsyncMock(side_effect=asyncio.CancelledError)) as sleep:
                with self.assertRaises(asyncio.CancelledError):await sync.poll_account_views()
                self.assertEqual(sync.state['account_views_last_success_at'],'last-good')
                self.assertEqual(sync.state['account_views_error'],'threads_rate_limited')
                self.assertGreaterEqual(sleep.call_args.args[0],900)
        finally:sync.state.update(before)

if __name__=='__main__':unittest.main()

