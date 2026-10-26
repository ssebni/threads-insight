import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.posts import database
from app.reply_views import combined_views
from app.account_views import read_account_views
from app.profile_followers import read_profile_followers
from app.profile_snapshot import read_profile_views

router = APIRouter(prefix='/api/dashboard', tags=['dashboard'])
KST = ZoneInfo('Asia/Seoul')


def followers_series(db):
    created = os.getenv('THREADS_ACCOUNT_CREATED_DATE', '2026-10-03')
    start = date.fromisoformat(created)
    end = datetime.now(KST).date()
    snapshots = {s.id: s.to_dict() for s in db.collection('follower_daily').stream(timeout=15)}
    # Preserve the prior day's baseline so the first requested date has a delta.
    baseline = snapshots.get((start - timedelta(days=1)).isoformat())
    points, previous = [], baseline.get('followers_count') if baseline else None
    current = start
    while current <= end:
        row = snapshots.get(current.isoformat())
        count = row['followers_count'] if row else None
        # Only consecutive observed days yield a daily change; gaps stay unknown.
        delta = count - previous if count is not None and previous is not None else None
        rate = round(delta / previous * 100, 3) if delta is not None and previous > 0 else None
        points.append({'date': current.isoformat(), 'followers_count': count,
                       'change': delta, 'change_percent': rate})
        previous = count
        current += timedelta(days=1)
    observed = [p for p in points if p['followers_count'] is not None]
    profile = read_profile_followers(db)
    return {'account_created_date': created, 'points': points,
            'current_count': profile['followers_count'] if profile else None,
            'current_profile': profile,
            'first_observed_date': observed[0]['date'] if observed else None,
            'metric': 'daily_net_follower_change', 'unit': '명',
            'last_change_date': next((p['date'] for p in reversed(points) if p['change'] is not None), None),
            'net_change_total': sum(p['change'] for p in points if p['change'] is not None),
            'note': '날짜별 총 팔로워 수의 전일 차이(순증, 명)입니다. 팔로우 취소·탈퇴도 반영됩니다. Meta 화면의 과거 이력을 사용하며 아직 집계되지 않은 날짜는 빈 값으로 둡니다.'}


def dashboard_for(db):
    posts = []
    for snapshot in db.collection('threads_posts').stream(timeout=30):
        rows = list(snapshot.reference.collection('insights').order_by(
            'collected_at', direction='DESCENDING').limit(1).stream(timeout=10))
        posts.append({**snapshot.to_dict(), 'id': snapshot.id,
                      'latest_insight': rows[0].to_dict() if rows else None})
    totals, coverage = {}, {}
    for name in ('views', 'likes', 'replies', 'reposts'):
        values = [p['latest_insight'][name] for p in posts
                  if p['latest_insight'] and p['latest_insight'].get(name) is not None]
        totals[name] = sum(values) if values else None
        coverage[name] = len(values)
    reply_rows = [{**s.to_dict(), 'id': s.id} for s in db.collection('threads_replies').stream(timeout=30)]
    breakdown = combined_views(totals['views'], coverage['views'], {p['id'] for p in posts}, reply_rows)
    official_views = read_account_views(db)
    profile_views = read_profile_views(db)
    totals['views'] = official_views['views'] if official_views else None
    views = [p for p in posts if p['latest_insight'] and p['latest_insight'].get('views') is not None]
    engagement = [p for p in posts if p['latest_insight'] and all(
        p['latest_insight'].get(k) is not None for k in ('likes', 'replies', 'reposts'))]
    def score(p):
        return sum(p['latest_insight'][k] for k in ('likes', 'replies', 'reposts'))
    best_views = max(views, key=lambda p: (p['latest_insight']['views'], p['timestamp'], p['id']), default=None)
    best_engagement = max(engagement, key=lambda p: (score(p), p['timestamp'], p['id']), default=None)
    observed = []
    if posts:
        refs = [db.collection('post_follower_insights').document(p['id']) for p in posts]
        follows_by_post = {s.id: s.to_dict() for s in db.get_all(refs, timeout=30) if s.exists}
        for post in posts:
            reading = follows_by_post.get(post['id'])
            if reading:
                observed.append({**post, 'follower_acquisition': reading})
    best_followers = max(observed, key=lambda p: (p['follower_acquisition']['follows'], p['timestamp'], p['id']), default=None)
    return {'totals': totals, 'coverage': coverage, 'post_count': len(posts), 'view_breakdown': breakdown, 'account_views': official_views, 'profile_views': profile_views,
            'totals_note': '메인 조회수는 Meta 공식 계정 인사이트 API의 최근 30일 값입니다. Meta 화면과 갱신 시점에 따른 차이가 남을 수 있습니다. 좋아요·댓글·리포스트와 Best Threads는 본문 누적 기준입니다.',
            'followers': followers_series(db),
            'best': {'views': best_views, 'engagement': best_engagement,
                     'engagement_score': score(best_engagement) if best_engagement else None,
                     'follower_acquisition': best_followers,
                     'follower_acquisition_coverage': len(observed),
                     'follower_acquisition_note': f'로그인된 Threads 게시물 인사이트 화면에서 실제 팔로우 수를 확인한 {len(observed)}개 게시물 중 선정합니다. 미확인 게시물은 0으로 처리하지 않습니다.'}}


@router.get('')
def dashboard(db=Depends(database)):
    return dashboard_for(db)
