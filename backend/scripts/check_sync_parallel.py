"""Offline regression checks for bounded refresh and safe insight persistence."""
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from app.sync_workers import SYNC_WORKERS, collect_parallel
from app.threads_sync import METRICS, SyncError, next_insight_check, sync_post


class ParallelChecks(unittest.TestCase):
    def test_overlap_session_isolation_and_result_coverage(self):
        barrier = threading.Barrier(SYNC_WORKERS)
        guard = threading.Lock()
        owners = {}
        def collect(item, session):
            with guard:
                previous = owners.setdefault(id(session), threading.get_ident())
                self.assertEqual(previous, threading.get_ident())
            self.assertEqual(session.headers['Authorization'], 'Bearer offline-test')
            if item < SYNC_WORKERS:
                barrier.wait(timeout=3)
            return item * 2
        with requests.Session() as session:
            session.headers['Authorization'] = 'Bearer offline-test'
            result = list(collect_parallel(range(12), session, collect))
        self.assertEqual(sorted(result), list(range(0, 24, 2)))
        self.assertEqual(len(owners), SYNC_WORKERS)

    def test_rate_limit_stops_scheduling(self):
        barrier = threading.Barrier(SYNC_WORKERS)
        started = []
        def collect(item, session):
            started.append(item)
            barrier.wait(timeout=3)
            if item == 0:
                raise SyncError('threads_rate_limited')
            time.sleep(0.05)
            return item
        with requests.Session() as session:
            with self.assertRaisesRegex(SyncError, 'threads_rate_limited'):
                list(collect_parallel(range(100), session, collect))
        self.assertEqual(sorted(started), list(range(SYNC_WORKERS)))

    def post(self, exists=True):
        data={'id':'123','text':'sample','timestamp':datetime.now(timezone.utc),
              'media_type':'TEXT_POST','permalink':'https://www.threads.com/@sample/post/example'}
        db=Mock();ref=Mock(id='123');snapshot=Mock(exists=exists,to_dict=lambda:data)
        return db,ref,snapshot,data

    def test_force_complete_skips_old_history_and_keeps_atomic_batch(self):
        db,ref,snapshot,data=self.post()
        payload={'data':[{'name':name,'values':[{'value':0}]} for name in METRICS]}
        with patch('app.threads_sync.api_get',return_value=payload):
            result=sync_post(Mock(),db,ref,data,snapshot,True)
        self.assertEqual(result,{'created':0,'updated':0,'insights_saved':1})
        ref.collection.return_value.order_by.assert_not_called()
        db.batch.return_value.commit.assert_called_once()
        saved=db.batch.return_value.create.call_args.args[1]
        self.assertEqual(saved['status'],'success')
        self.assertEqual(saved['views'],0)
        db.batch.return_value.set.assert_called_once()

    def test_force_missing_metrics_preserves_previous_observation(self):
        db,ref,snapshot,data=self.post()
        ref.collection.return_value.order_by.return_value.limit.return_value.stream.return_value=[Mock()]
        with patch('app.threads_sync.api_get',return_value={'data':[]}):
            result=sync_post(Mock(),db,ref,data,snapshot,True)
        self.assertEqual(result['insights_saved'],0)
        db.batch.return_value.commit.assert_not_called()

    def test_new_post_and_initial_insight_commit_together(self):
        db,ref,snapshot,data=self.post(exists=False)
        with patch('app.threads_sync.api_get',return_value={'data':[]}):
            result=sync_post(Mock(),db,ref,data,snapshot,True)
        self.assertEqual(result,{'created':1,'updated':0,'insights_saved':1})
        self.assertEqual(db.batch.return_value.create.call_count,2)
        db.batch.return_value.commit.assert_called_once()

    def test_api_failure_does_not_commit_or_advance_due_time(self):
        db,ref,snapshot,data=self.post(exists=False)
        next_insight_check.pop(ref.id,None)
        with patch('app.threads_sync.api_get',side_effect=SyncError('threads_rate_limited')):
            with self.assertRaises(SyncError):
                sync_post(Mock(),db,ref,data,snapshot,True)
        db.batch.return_value.commit.assert_not_called()
        self.assertNotIn(ref.id,next_insight_check)


if __name__=='__main__':
    unittest.main()
