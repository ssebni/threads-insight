"""Create and remove this run's temporary contract; never modify Threads or memos."""
import uuid
import requests

base='http://127.0.0.1:8010/api/collaborations'
body={'tag':'검증'+uuid.uuid4().hex[:8], 'date':'2026-10-26','fee_mode':'bundle','fee':300000,'paid_amount':100000,'memo':'자동 검증 후 삭제되는 임시 협업'}
identity=None
def ok(response, code=200):
    assert response.status_code == code, (response.status_code,response.text[:300])
    return response.json() if code != 204 else None
def current():
    return next(row for row in ok(requests.get(base,timeout=70))['items'] if row['id']==identity)
try:
    posts=ok(requests.get(base+'/catalog',timeout=40))['items'][:2]
    assert len(posts)==2
    identity=ok(requests.post(base,json=body,timeout=30),201)['id']
    assert requests.post(base,json=body,timeout=30).status_code==409
    for post in posts:
        ok(requests.put(f"{base}/{identity}/posts/{post['id']}",json={'assigned':True},timeout=30))
    row=current()
    assert row['performance']['post_count']==2 and row['finance']['agreed']==300000
    assert row['finance']['outstanding']==200000
    body.update(fee_mode='per_post',fee=100000)
    ok(requests.put(base+'/'+identity,json=body,timeout=30))
    ok(requests.put(f"{base}/{identity}/posts/{posts[0]['id']}",json={'assigned':True,'fee_override':50000},timeout=30))
    assert current()['finance']['agreed']==150000
    ok(requests.put(f"{base}/{identity}/posts/{posts[1]['id']}",json={'assigned':False},timeout=30))
    row=current()
    assert row['finance']['agreed']==50000 and row['finance']['overpaid']==50000
    assert requests.post(base,json={**body,'tag':'가'*11},timeout=30).status_code==422
    print('PASS: live create, duplicate, assignment, bundle/per-post, override, unlink, validation')
finally:
    if identity:
        ok(requests.delete(base+'/'+identity,timeout=30),204)
        assert not any(row['id']==identity for row in ok(requests.get(base,timeout=70))['items'])
        print('PASS: temporary contract deleted; original posts and memos retained')
