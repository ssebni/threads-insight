"""Offline validation of UI observations; never writes real observations."""
import unittest
from datetime import datetime, timezone
from pydantic import ValidationError
from scripts.import_screen_followers import ScreenBatch, ScreenObservation


def sample(**overrides):
    return {**{'post_url':'https://www.threads.com/@nibetsi.zip/post/Example',
               'insights_url':'https://www.threads.com/insights/post/Example',
               'follows':4,'observed_at':datetime.now(timezone.utc),
               'source':'threads_insights_ui'}, **overrides}


class ScreenChecks(unittest.TestCase):
    def test_exact_zero_is_valid(self):
        self.assertEqual(ScreenObservation(**sample(follows=0)).follows,0)

    def test_unknown_and_approximate_are_rejected(self):
        for value in (None,-1,'1.2천',1.2,True):
            with self.assertRaises(ValidationError):
                ScreenObservation(**sample(follows=value))

    def test_wrong_post_rejected(self):
        with self.assertRaises(ValidationError):
            ScreenObservation(**sample(insights_url='https://www.threads.com/insights/post/Another'))

    def test_wrong_host_rejected(self):
        with self.assertRaises(ValidationError):
            ScreenObservation(**sample(post_url='https://untrusted.example/@nibetsi.zip/post/Example'))

    def test_wrong_account_rejected(self):
        with self.assertRaises(ValidationError):
            ScreenBatch(account_username='other',items=[sample()])

    def test_duplicate_post_rejected(self):
        with self.assertRaises(ValidationError):
            ScreenBatch(account_username='nibetsi.zip',items=[sample(),sample()])

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(ValidationError):
            ScreenObservation(**sample(observed_at='2026-10-18T00:00:00'))


if __name__=='__main__':
    unittest.main()
