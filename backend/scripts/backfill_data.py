"""Populate the assignment's data collection from existing latest post insights."""
from app.analysis_records import observation
from app.database import get_database


def main():
    db = get_database()
    written = skipped = 0
    for post in db.collection('threads_posts').stream(timeout=30):
        latest = list(post.reference.collection('insights').order_by(
            'collected_at', direction='DESCENDING').limit(1).stream(timeout=10))
        record = observation(post.to_dict(), latest[0].to_dict()) if latest else None
        if record:
            db.collection('data').document('threads_' + post.id).set(record, merge=True, timeout=10)
            written += 1
        else:
            skipped += 1
    print({'analytical_records': written, 'missing_views_skipped': skipped})


if __name__ == '__main__':
    main()
