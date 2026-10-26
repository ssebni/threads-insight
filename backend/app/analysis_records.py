from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def observation(post, insight):
    """One analytical record per post; null measurements are never converted to zero."""
    if insight.get('views') is None:
        return None
    return {
        'date': post['timestamp'].astimezone(ZoneInfo('Asia/Seoul')).date().isoformat(),
        'value': insight['views'], 'memo': post.get('text', '')[:2000],
        'source': 'threads', 'metric': 'views', 'post_id': post['id'],
        'observed_at': insight['collected_at'], 'updated_at': datetime.now(timezone.utc),
    }
