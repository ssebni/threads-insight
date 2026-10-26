"""Offline analysis and GPT request-contract checks; no API charges."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

os.environ['THREADS_AUTO_SYNC'] = 'false'

from app.analysis_records import observation
from app.chat import generate_reply
from app.dashboard import followers_series
from app.data_api import summary_for


def fake_database(rows):
    db = Mock()
    snapshots = [Mock(id=record_id, to_dict=lambda row=row: row) for record_id, row in rows]
    db.collection.return_value.stream.return_value = snapshots
    db.collection.return_value.limit.return_value.stream.return_value = snapshots
    return db


class AnalysisChecks(unittest.TestCase):
    def test_empty_summary(self):
        result = summary_for(fake_database([]))
        self.assertEqual(result['count'], 0)
        self.assertIsNone(result['metrics']['average'])
        self.assertFalse(result['meets_minimum'])

    def test_summary_math(self):
        result = summary_for(fake_database([
            ('a', {'date': '2026-10-01', 'value': 10, 'source': 'manual'}),
            ('b', {'date': '2026-10-08', 'value': 20, 'source': 'threads'}),
            ('c', {'date': '2026-10-08', 'value': 30, 'source': 'threads'}),
        ]))
        self.assertEqual(result['metrics']['total'], 60)
        self.assertEqual(result['metrics']['average'], 20)
        self.assertEqual(result['trend']['change_percent'], 400)
        self.assertEqual(result['count'], 3)

    def test_follower_gap_and_zero_not_invented(self):
        db = fake_database([
            ('2026-10-14', {'followers_count': 0}),
            ('2026-10-15', {'followers_count': 100}),
            ('2026-10-17', {'followers_count': 110}),
            ('2026-10-18', {'followers_count': 99}),
        ])
        with patch('app.dashboard.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 18, tzinfo=timezone.utc)
            result = followers_series(db)
        points = {p['date']: p for p in result['points']}
        self.assertIsNone(points['2026-10-15']['change_percent'])
        self.assertIsNone(points['2026-10-17']['change_percent'])
        self.assertEqual(points['2026-10-18']['change_percent'], -10)
        self.assertIsNone(points['2026-10-03']['followers_count'])

    def test_korean_post_date_and_null_measurement(self):
        post = {'id': '1', 'timestamp': datetime(2026, 10, 17, 23, tzinfo=timezone.utc)}
        self.assertIsNone(observation(post, {'views': None}))
        self.assertEqual(observation(post, {'views': 0, 'collected_at': post['timestamp']})['date'], '2026-10-18')

    def test_gpt_context_and_cost_limits(self):
        # Provider contract only; no external request is made.
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-placeholder'}):
            with patch('app.chat.OpenAI') as sdk:
                sdk.return_value.__enter__.return_value.responses.create.return_value.output_text = ' 검증 답변 '
                answer = generate_reply([{'role': 'user', 'content': '요약해줘'}], {'count': 80, 'daily': []})
                request = sdk.return_value.__enter__.return_value.responses.create.call_args.kwargs
                self.assertIn('80', request['instructions'])
                self.assertEqual(request['max_output_tokens'], 1000)
                self.assertFalse(request['store'])
                self.assertEqual(answer, '검증 답변')

    def test_first_day_uses_previous_day_baseline(self):
        db = fake_database([
            ('2026-10-02', {'followers_count': 36}),
            ('2026-10-03', {'followers_count': 42}),
            ('2026-10-04', {'followers_count': 41}),
        ])
        with patch('app.dashboard.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 4, tzinfo=timezone.utc)
            result = followers_series(db)
        self.assertEqual([p['change'] for p in result['points']], [6, -1])
        self.assertEqual(result['net_change_total'], 5)
        self.assertEqual(result['unit'], '명')


if __name__ == '__main__':
    unittest.main()
