"""Offline checks for reply view totals and safe incremental collection."""
import unittest
import requests
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
from app.reply_views import combined_views, fetch_replies, sync_reply_views

class ReplyChecks(unittest.TestCase):
    def test_sum_scope_dedup_and_unknown(self):
        result = combined_views(100, 1, {'1'}, [
            {'id':'1','is_reply':True,'views':100},
            {'id':'2','is_reply':True,'views':50},
            {'id':'3','is_reply':False,'views':999},
            {'id':'4','is_reply':True,'views':None}])
        self.assertEqual(result['total'], 150)
        self.assertEqual(result['own_replies_coverage'], 1)
        self.assertIsNone(combined_views(None,0,set(),[])['total'])
        self.assertEqual(combined_views(None,0,set(),[{'id':'2','is_reply':True,'views':0}])['total'],0)

    def test_reply_pagination_and_scope(self):
        api=Mock(side_effect=[{'data':[{'id':'1','timestamp':'2026-10-18T00:00:00Z','is_reply':True}], 'paging':{'next':'unused','cursors':{'after':'cursor'}}}, {'data':[{'id':'2','is_reply':False}]}])
        result=fetch_replies(Mock(),api)
        self.assertEqual(list(result),['1'])
        self.assertEqual(api.call_args.args[1],'me/replies')
        self.assertEqual(api.call_args.args[2]['after'],'cursor')

    def test_failed_metric_preserves_value_and_limits_work(self):
        db=Mock(); refs={str(i):Mock(id=str(i)) for i in range(3)}
        db.collection.return_value.document.side_effect=lambda pid:refs[pid]
        old=datetime.now(timezone.utc)-timedelta(hours=1)
        db.get_all.return_value=[Mock(id=pid,exists=True,to_dict=lambda:{'views':9,'checked_at':old}) for pid in refs]
        api=Mock(side_effect=[{'data':[{'id':pid,'timestamp':'2026-10-18T00:00:00Z','is_reply':True} for pid in refs]}, {'data':[]}])
        with requests.Session() as session:
            result=sync_reply_views(session,db,api,900,limit=1)
        self.assertEqual(result['checked'],1)
        self.assertEqual(result['pending'],2)
        data=refs['0'].set.call_args.args[0]
        self.assertNotIn('views',data)
        self.assertIn('checked_at',data)
        self.assertTrue(refs['0'].set.call_args.kwargs['merge'])

if __name__ == '__main__': unittest.main()
