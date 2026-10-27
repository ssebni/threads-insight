'use strict';
const $ = selector => document.querySelector(selector);
const apiBase = (window.APP_CONFIG?.API_BASE_URL || location.origin).replace(/\/$/, '');
const number = value => value == null ? '—' : new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 1 }).format(value);
let postCursor = null, dataCursor = null, historyCursor = null, conversationId = null;
let chatBusy = false, postBusy = false, dataBusy = false, activeView = 'overview';
let aiConfigured = false;
let refreshBusy = false;
let lastSummary = null;
let accessPrompt = null;
let noticeRevision = 0;

function requestSiteAccess() {
  if (accessPrompt) return accessPrompt;
  accessPrompt=new Promise(resolve=>{
    const dialog=$('#access-dialog'),form=$('#access-form');
    form.reset();dialog.oncancel=event=>event.preventDefault();dialog.showModal();
    form.onsubmit=event=>{event.preventDefault();const token=$('#access-token').value.trim();if(!token)return;sessionStorage.setItem('threads-access-token',token);dialog.close();resolve(token);};
  }).finally(()=>{accessPrompt=null;});
  return accessPrompt;
}
let followerRange = 'week', followerData = null;

function followerPoints(data, range) {
  // Select available observations, including zero and negative daily changes.
  const available = data.points.filter(point => Number.isFinite(point.change));
  if (range === 'all') return available;
  return available.slice(-(range === 'week' ? 7 : 30));
}

function drawFollowers(data) {
  followerData = data;
  const root = $('#follower-chart'); root.replaceChildren(); root.scrollLeft = 0;
  const points = followerPoints(data, followerRange), valid = points.filter(p => p.change != null);
  const bars = followerRange !== 'all';
  const title = ({ week: '최근 일주일 팔로워 증가수', month: '최근 한달 팔로워 증가수', all: '전체 팔로워 증가수' })[followerRange];
  $('#follower-title').textContent = title;
  root.setAttribute('aria-labelledby', 'follower-tab-' + followerRange);
  root.dataset.range = followerRange;
  $('#follower-period').textContent = points.length ? points[0].date.replaceAll('-', '/') + ' ~ ' + points.at(-1).date.replaceAll('-', '/') : '기록 없음';
  const net = valid.reduce((sum, point) => sum + point.change, 0);
  const basis = ({ week: '증감수가 확인된 최근 7개 일별 기록', month: '증감수가 확인된 최근 30개 일별 기록', all: '증감수가 확인된 전체 일별 기록' })[followerRange];
  $('#follower-note').textContent = `${basis}을 표시합니다. 미집계 날짜는 제외합니다. 표시된 ${valid.length}일의 순증 합계 ${net > 0 ? '+' : ''}${number(net)}명.`;
  const width = followerRange === 'month' ? 1140 : 1000;
  const height = 285, left = 52, right = 25, top = 24, bottom = 44;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'group');
  svg.setAttribute('aria-label', title + (bars ? ' 막대 그래프' : ' 선형 그래프'));
  svg.style.minWidth = followerRange === 'month' ? '1080px' : '600px';
  const add = (tag, attrs, text) => {
    const node = document.createElementNS(svg.namespaceURI, tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text != null) node.textContent = text; svg.append(node); return node;
  };
  const max = Math.ceil(Math.max(1, ...valid.map(p => Math.abs(p.change))) * 1.2);
  const plotWidth = width - left - right, cell = plotWidth / Math.max(1, points.length);
  const x = index => bars ? left + (index + 0.5) * cell : left + index / Math.max(1, points.length - 1) * plotWidth;
  const y = value => top + (max - value) / (2 * max) * (height - top - bottom);
  [-1, 0, 1].forEach(factor => {
    const value = factor * max;
    add('line', { x1: left, y1: y(value), x2: width - right, y2: y(value), stroke: '#e8e8e8', 'stroke-dasharray': factor ? '4 5' : '0' });
    add('text', { x: left - 10, y: y(value) + 4, 'text-anchor': 'end', fill: '#737373', 'font-size': 12 }, value + '명');
  });
  let previousMonth = null;
  points.forEach((point, index) => {
    const month = point.date.slice(0, 7);
    if (bars || month !== previousMonth) {
      add('text', { x: x(index), y: height - 14, 'text-anchor': 'middle', fill: '#737373', 'font-size': 12, class: 'follower-date' }, bars ? point.date.slice(5).replace('-', '/') : Number(point.date.slice(5, 7)) + '월');
    }
    previousMonth = month;
  });
  const tooltip = element('div', 'follower-tooltip'); tooltip.id = 'follower-tooltip';
  tooltip.setAttribute('role', 'tooltip'); tooltip.hidden = true;
  const hideTip = () => { tooltip.hidden = true; };
  let segment = [];
  const flush = () => {
    const drawLine = (a, b, negative) => add('line', { x1:a[0], y1:a[1], x2:b[0], y2:b[1], stroke:negative ? '#ba7566' : '#222222', 'stroke-width':2.5, 'pointer-events':'none' });
    for (let i = 1; i < segment.length; i++) {
      const a = segment[i - 1].split(',').map(Number), b = segment[i].split(',').map(Number), baseline = y(0);
      if ((a[1] > baseline) !== (b[1] > baseline)) {
        const zero = [a[0] + (b[0] - a[0]) * (baseline - a[1]) / (b[1] - a[1]), baseline];
        drawLine(a, zero, a[1] > baseline); drawLine(zero, b, b[1] > baseline);
      } else drawLine(a, b, a[1] > baseline);
    }
    segment = [];
  };
  // Draw line segments first so visible data points and their hit areas stay on top.
  if (!bars) {
    points.forEach((point, index) => {
      if (point.change == null) { flush(); return; }
      segment.push(`${x(index)},${y(point.change)}`);
    }); flush();
  }
  points.forEach((point, index) => {
    if (point.change == null) return;
    const label = `${number(point.change)}명`;
    let mark;
    if (bars) {
      mark = add('rect', { x: x(index) - Math.min(44, cell * 0.6) / 2, y: Math.min(y(0), y(point.change)), width: Math.min(44, cell * 0.6), height: Math.max(2, Math.abs(y(point.change) - y(0))), rx: 3, fill: point.change < 0 ? '#ba7566' : '#222222', class: 'follower-mark follower-bar' });
    } else {
      add('circle', { cx: x(index), cy: y(point.change), r: 4, fill: point.change < 0 ? '#ba7566' : '#222222', 'pointer-events': 'none' });
      mark = add('circle', { cx: x(index), cy: y(point.change), r: 12, fill: 'transparent', class: 'follower-mark follower-dot' });
    }
    mark.classList.toggle('is-negative', point.change < 0);
    mark.setAttribute('tabindex', '0'); mark.setAttribute('role', 'img');
    mark.setAttribute('aria-label', label); mark.setAttribute('aria-describedby', tooltip.id);
    const showTip = () => {
      tooltip.classList.toggle('is-negative', point.change < 0);
      tooltip.textContent = label; tooltip.hidden = false;
      const box = mark.getBoundingClientRect(), tip = tooltip.getBoundingClientRect();
      tooltip.style.left = Math.max(8, Math.min(window.innerWidth - tip.width - 8, box.left + box.width / 2 - tip.width / 2)) + 'px';
      tooltip.style.top = Math.max(8, box.top - tip.height - 10) + 'px';
    };
    mark.addEventListener('pointerenter', showTip); mark.addEventListener('pointerleave', hideTip);
    mark.addEventListener('focus', showTip); mark.addEventListener('blur', hideTip);
    mark.addEventListener('click', showTip);
    mark.addEventListener('keydown', event => { if (event.key === 'Escape') hideTip(); });
  });
  root.append(svg, tooltip); root.onscroll = hideTip;
  if (!valid.length) root.append(element('div', 'chart-empty', '선택한 기간의 팔로워 증가수 이력을 수집하고 있습니다.'));
}

function selectFollowerRange(range) {
  followerRange = range;
  document.querySelectorAll('[data-follower-range]').forEach(button => {
    const selected = button.dataset.followerRange === range;
    button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
  });
  if (followerData) drawFollowers(followerData);
}

async function loadDashboard() {
  const data = await api('/api/dashboard');
  for (const key of ['views', 'likes', 'replies', 'reposts']) $('#total-' + key).textContent = number(data.totals[key]);
  const official = data.account_views;
  const profileViews = data.profile_views;
  // Keep abbreviated profile values as displayed; never invent an exact count.
  $('#total-views').textContent = profileViews?.display_value || '—';
  const officialNote = profileViews
    ? `Meta 프로필 · 마지막 수집 ${new Date(profileViews.observed_at).toLocaleString('ko-KR')}`
    : official
    ? '프로필 조회수 수집 대기 중 · 크롬 연결 후 새로고침해 주세요.'
    : '프로필 조회수 수집 대기 중';
  $('#totals-note').textContent = officialNote;
  $('#follower-count').textContent = number(data.followers.current_count);
  const profile = data.followers.current_profile;
  $('#follower-observed').textContent = profile ? `화면 확인 ${new Date(profile.observed_at).toLocaleString('ko-KR')}${profile.stale ? ' · 갱신 지연: 마지막 확인값' : ''}` : '프로필 화면 수집 대기 중';
  drawFollowers(data.followers);
  const root = $('#best-threads'); root.replaceChildren();
  const categories = [
    ['최고 조회수', 'MOST VIEWED', data.best.views, data.best.views ? number(data.best.views.latest_insight.views) + '회 조회' : '데이터 없음'],
    ['최고 참여수', 'MOST ENGAGED', data.best.engagement, data.best.engagement ? number(data.best.engagement_score) + '회 참여' : '데이터 없음'],
    ['최고 유입수', 'MOST FOLLOWED', data.best.follower_acquisition, data.best.follower_acquisition ? number(data.best.follower_acquisition.follower_acquisition.follows) + '명 팔로우' : '화면 수집 대기'],
  ];
  categories.forEach(([label, eyebrow, post, score], index) => {
    const card = element('article', 'panel best-card');
    card.append(element('div', 'eyebrow', eyebrow), element('h3', '', label), element('strong', 'best-score', score));
    if (post) {
      card.append(element('p', 'caption', '발행일 ' + new Date(post.timestamp).toLocaleString('ko-KR')));
      card.append(element('p', 'post-text best-text', post.text || '(본문 없는 게시물)'));
      const insight = post.latest_insight, metrics = element('div', 'best-metrics');
      metrics.append(metric('조회수', insight.views), metric('좋아요', insight.likes), metric('댓글', insight.replies), metric('리포스트', insight.reposts));
      card.append(metrics, action('전체 원문과 인사이트 보기 ↗', () => showPost(post.id), 'button wide'));
    } else card.append(element('p', 'unavailable', index === 2 ? data.best.follower_acquisition_note : '지표가 수집되면 최고의 게시물이 표시됩니다.'));
    root.append(card);
  });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function notify(text, error = false) {
  noticeRevision++;
  $('#notice').textContent = text;
  $('#notice').classList.toggle('error', error);
  $('#notice').hidden = false;
}
async function api(path, options = {}) {
  const controller = new AbortController();
  let waitingNotice = null;
  const slow = setTimeout(() => {
    notify('서버 응답을 기다리는 중입니다. 배포 서버가 잠들어 있었다면 첫 연결에 시간이 걸릴 수 있어요.');
    waitingNotice = noticeRevision;
  }, 10000);
  const timeout = setTimeout(() => controller.abort(), 70000);
  try {
    const token=sessionStorage.getItem('threads-access-token');
    const response = await fetch(apiBase + path, {
      ...options, headers: { 'Content-Type': 'application/json', ...(token ? {'Authorization':'Bearer '+token} : {}), ...options.headers }, signal: controller.signal,
    });
    if(response.status===401){
      clearTimeout(slow);clearTimeout(timeout);
      if(options.accessRetry)throw new Error('사이트 접근키가 일치하지 않습니다. 페이지를 새로고침하고 다시 입력해 주세요.');
      await requestSiteAccess();return api(path,{...options,accessRetry:true});
    }
    if (response.status === 204) return null;
    const body = await response.json();
    if (!response.ok) {
      const detail = typeof body.detail === 'string' ? body.detail : '입력 내용을 확인해 주세요.';
      throw new Error(detail);
    }
    if (response.headers.get('X-Data-Cache') === 'stale') {
      const at = Number(response.headers.get('X-Data-Cached-At')) * 1000;
      notify(`Firestore 한도 초과로 ${new Date(at).toLocaleString('ko-KR')}에 저장한 화면을 표시합니다. 최신 데이터가 아닙니다.`, true);
    }
    return body;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('서버 응답 시간이 초과됐습니다. 잠시 후 다시 시도해 주세요.');
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 서버 실행 상태와 API 주소를 확인해 주세요.');
    throw error;
  } finally {
    clearTimeout(slow); clearTimeout(timeout);
    // Remove only this request's waiting message; preserve later errors and notices.
    if (waitingNotice !== null && waitingNotice === noticeRevision) $('#notice').hidden = true;
  }
}
function action(text, onClick, className = 'button') {
  const button = element('button', className, text);
  button.type = 'button'; button.addEventListener('click', onClick);
  return button;
}
function metric(label, value) {
  const span = element('span'); span.append(label + ' ', element('b', '', number(value))); return span;
}
async function loadSummary() {
  const data = await api('/api/data/summary'); lastSummary = data;
  $('#chat-context').textContent = `조회수 기록 ${number(data.count)}개 · ${data.period.start || '—'} ~ ${data.period.end || '—'}의 요약을 반영합니다.`;
  $('#chat-summary').textContent = `조회수 합계 ${number(data.metrics.total)}회 · 평균 ${number(data.metrics.average)}회 · 최근 추세 ${data.trend.label} · 100개 목표 ${data.meets_minimum ? '달성' : '수집 중'}`;
}
async function showPost(id) {
  try {
    const [post, savedMemo] = await Promise.all([api(`/api/v1/posts/${id}`), api(`/api/memos/${id}`)]);
    const root = $('#post-detail'); root.replaceChildren();
    root.append(element('p', 'caption', new Date(post.timestamp).toLocaleString('ko-KR')), element('p', 'post-text', post.text || '(본문 없는 게시물)'));
    try {
      const url = new URL(post.permalink);
      if (url.protocol === 'https:') {
        const link = element('a', '', 'Threads에서 원문 보기 ↗'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; root.append(link);
      }
    } catch (_) { /* A missing permalink does not prevent viewing the data. */ }
    const insight = post.latest_insight;
    if (insight) {
      const metrics = element('div', 'post-metrics detail-metrics');
      metrics.append(metric('조회', insight.views), metric('좋아요', insight.likes), metric('댓글', insight.replies), metric('리포스트', insight.reposts)); root.append(metrics);
    }
    await appendCollaborationTags(root, id);
    const form = element('form', 'memo-form'), label = element('label', '', '메모');
    const input = element('textarea'); input.id = 'post-memo'; input.rows = 7; input.maxLength = 10000;
    input.placeholder = '이 게시물에 대한 생각이나 아이디어를 자유롭게 적어보세요.';
    input.value = savedMemo.memo; label.htmlFor = input.id;
    const status = element('p', 'caption'); status.setAttribute('role', 'status');
    const controls = element('div', 'form-actions');
    const save = element('button', 'button primary', '메모 저장'); save.type = 'submit';
    const remove = action('메모 삭제', async () => {
      if (!confirm('이 게시물의 메모를 삭제할까요?')) return;
      save.disabled = remove.disabled = true;
      try { await api(`/api/memos/${id}`, {method:'DELETE'}); input.value = ''; remove.hidden = true; status.textContent = '메모를 삭제했습니다.'; if (activeView === 'data') await loadData(); }
      catch (error) { status.textContent = error.message; }
      finally { save.disabled = remove.disabled = false; }
    }); remove.hidden = !savedMemo.memo;
    controls.append(save, remove); form.append(label, input, controls, status);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (!input.value.trim()) { status.textContent = '메모 내용을 입력해 주세요.'; input.focus(); return; }
      save.disabled = remove.disabled = true;
      try { await api(`/api/memos/${id}`, {method:'PUT', body:JSON.stringify({memo:input.value})}); remove.hidden = false; status.textContent = '메모를 저장했습니다.'; if (activeView === 'data') await loadData(); }
      catch (error) { status.textContent = error.message; }
      finally { save.disabled = remove.disabled = false; }
    }); root.append(form);
    $('#post-dialog').showModal();
  } catch (error) { notify(error.message, true); }
}
async function loadPosts(append = false) {
  if (postBusy) return; postBusy = true;
  try {
    const result = await api('/api/v1/posts?limit=10' + (append && postCursor ? '&cursor=' + encodeURIComponent(postCursor) : ''));
    const root = $('#posts'); if (!append) root.replaceChildren();
    result.items.forEach(post => {
      const article = element('article', 'post'); const meta = element('div', 'post-meta');
      meta.append(element('span', '', new Date(post.timestamp).toLocaleString('ko-KR')), element('span', 'post-type', post.media_type));
      const metrics = element('div', 'post-metrics'); const insight = post.latest_insight;
      metrics.append(metric('조회', insight?.views), metric('좋아요', insight?.likes), metric('답글', insight?.replies), action('상세 ↗', () => showPost(post.id), 'button subtle post-detail-button'));
      article.append(meta, element('p', 'post-text', post.text.length > 200 ? post.text.slice(0, 200) + '…' : post.text || '(본문 없는 게시물)'), metrics); root.append(article);
    });
    if (!result.items.length && !append) root.append(element('p', 'empty', '아직 수집된 게시물이 없습니다.'));
    postCursor = result.next_cursor; $('#more-posts').hidden = !result.has_more;
  } finally { postBusy = false; }
}
async function loadData(append = false) {
  if (!append) await loadCollaborations();
  return loadMemos(append);
}
async function loadMemos(append = false) {
  if (dataBusy) return; dataBusy = true;
  try {
    const result = await api('/api/memos?limit=20' + (append && dataCursor ? '&cursor=' + encodeURIComponent(dataCursor) : ''));
    const root = $('#data-list'); if (!append) root.replaceChildren();
    result.items.forEach(record => {
      const row = element('article', 'memo-card');
      row.append(element('p', 'caption', '발행일 ' + new Date(record.post_timestamp).toLocaleString('ko-KR')),
        element('p', 'post-text', record.post_text || '(본문 없는 게시물)'), element('h3', '', '메모'), element('p', 'memo-content', record.memo),
        element('p', 'caption', '메모 수정 ' + new Date(record.updated_at).toLocaleString('ko-KR')),
        action('상세 · 메모 수정 ↗', () => showPost(record.post_id)));
      root.append(row);
    });
    if (!result.items.length && !append) root.append(element('p', 'empty', '아직 메모가 없습니다. 대시보드에서 게시물의 상세를 눌러 첫 메모를 남겨보세요.'));
    dataCursor = result.next_cursor; $('#more-data').hidden = !result.has_more;
  } finally { dataBusy = false; }
}
function message(role, text) {
  const node = element('div', 'message ' + role); node.append(element('span', 'message-label', role === 'user' ? '나' : '인사이트 비서'), document.createTextNode(text));
  $('#messages').append(node); $('#messages').scrollTop = $('#messages').scrollHeight; return node;
}
async function loadHistory(append = false) {
  const result = await api('/api/conversations?limit=20' + (append && historyCursor ? '&cursor=' + encodeURIComponent(historyCursor) : ''));
  const root = $('#conversation-list'); if (!append) root.replaceChildren();
  result.items.forEach(conversation => {
    const row = element('div', 'conversation-row');
    row.dataset.conversationId = conversation.id;
    row.classList.toggle('active', conversation.id === conversationId);
    const open = action(conversation.title, async () => {
      if (chatBusy) return;
      try {
        const body = await api('/api/conversations/' + conversation.id);
        conversationId = body.id; $('#messages').replaceChildren(); body.messages.forEach(m => message(m.role, m.content));
        document.querySelectorAll('.conversation-row').forEach(node => node.classList.toggle('active', node.dataset.conversationId === conversationId));
        $('#chat-input').focus();
        notify('대화를 불러왔습니다. 이어서 질문할 수 있습니다.');
      } catch (error) { notify(error.message, true); }
    }, 'conversation-open');
    open.append(element('small', '', new Date(conversation.updated_at).toLocaleString('ko-KR')));
    row.append(open, action('삭제', async () => {
      if (chatBusy || !confirm('이 대화 기록을 삭제할까요?')) return;
      try { await api('/api/conversations/' + conversation.id, { method: 'DELETE' }); if (conversationId === conversation.id) newChat(); await loadHistory(); notify('대화 기록을 삭제했습니다.'); }
      catch (error) { notify(error.message, true); }
    })); root.append(row);
  });
  if (!result.items.length && !append) root.append(element('p', 'empty', 'AI와 나눈 대화가 여기에 저장됩니다.'));
  historyCursor = result.next_cursor; $('#more-history').hidden = !result.has_more;
}
function newChat() { if (chatBusy) return; conversationId = null; document.querySelectorAll('.conversation-row').forEach(node => node.classList.remove('active')); $('#messages').replaceChildren(); message('assistant', '새로운 대화를 시작합니다. 내 데이터에 대해 무엇이 궁금하세요?'); $('#chat-input').value = ''; $('#chat-input').focus(); }
async function sendChat(event) {
  event.preventDefault(); const text = $('#chat-input').value.trim(); if (!text || chatBusy) return;
  chatBusy = true; $('#send-chat').disabled = true; $('#new-chat').disabled = true;
  if ($('#messages .welcome')) $('#messages').replaceChildren();
  const userNode = message('user', text), loading = message('assistant', '데이터를 읽고 답변을 준비하고 있습니다…'); loading.classList.add('loading');
  try {
    const result = await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: text, conversation_id: conversationId }) });
    conversationId = result.conversation_id; loading.remove(); message('assistant', result.answer); $('#chat-input').value = '';
    await loadHistory();
  } catch (error) { loading.remove(); userNode.remove(); notify(error.message, true); }
  finally { chatBusy = false; $('#send-chat').disabled = false; $('#new-chat').disabled = false; }
}
async function switchView(name) {
  document.body.dataset.view = name;
  activeView = name; document.querySelectorAll('.view').forEach(node => node.hidden = node.id !== name + '-view' && !(name === 'chat' && node.id === 'history-view'));
  $('#chat-view').hidden = name !== 'chat';
  $('#notice').hidden = true;
  if (name === 'chat' && !aiConfigured) notify('AI 채팅 연결 준비 중입니다. 백엔드 API 키 설정을 확인해 주세요.');
  document.querySelectorAll('.nav').forEach(node => node.classList.toggle('active', node.dataset.view === name));
  $('#page-label').textContent = ({ overview: '대시보드', data: '협업 관리', chat: 'AI 비서' })[name];
  $('.page-title .eyebrow').textContent = name === 'data' ? 'COLLABORATIONS' : 'YOUR WORDS, WITH PERSPECTIVE';
  const pageTitle = $('.page-title h1');
  if (name === 'data') pageTitle.textContent = '스레드 협업 관리';
  else pageTitle.replaceChildren(document.createTextNode('기록에서, 다음 아이디어로'), element('span', '', '.'));
  $('.page-title>p').textContent = name === 'data' ? '협업별 스레드 성과와 원고료, 정산 현황을 한눈에 확인하세요.' : '내 콘텐츠의 흐름을 살펴보고, 데이터에 근거한 이야기를 나눠보세요.';
  try { if (name === 'overview') await Promise.all([loadDashboard(), loadPosts()]); if (name === 'data') await loadData(); if (name === 'chat') await loadHistory(); } catch (error) { notify(error.message, true); }
}
async function refresh(silent = false) {
  if (refreshBusy) return;
  refreshBusy = true;
  $('#refresh').disabled = true;
  const originalLabel = $('#refresh').textContent;
  let syncResult = null;
  let profileWarning = null;
  try {
    if (!silent) {
      $('#refresh').textContent = '↻ 업데이트 중…';
      notify('Threads에서 최신 게시물과 수치를 가져오고 있습니다. 잠시 기다려 주세요.');
      let profileSnapshot = null;
      try { profileSnapshot = await requestProfileSnapshot(); }
      catch (error) { profileWarning = error.message; }
      await api('/api/v1/sync/run', { method: 'POST', body: JSON.stringify({profile_snapshot: profileSnapshot}) });
      const deadline = Date.now() + 15 * 60 * 1000;
      while (Date.now() < deadline) {
        const status = await api('/api/v1/sync/status');
        if (status.manual.status !== 'running') { syncResult = status.manual; break; }
        const progress = status.progress;
        const seconds = Math.floor((Date.now() - new Date(status.manual.started_at).getTime()) / 1000);
        const detail = progress?.phase === 'posts' && progress.total ? `게시물 ${progress.completed}/${progress.total}개 확인` : progress?.phase === 'replies' ? (progress.total ? `답글 ${progress.completed}/${progress.total}개 확인` : '답글 조회수 확인') : progress?.phase === 'account' ? '계정 조회수 확인' : 'Threads 데이터 확인';
        $('#refresh').textContent = `↻ ${detail}`;
        notify(`${detail} 중 · ${seconds}초 경과. 수집이 끝나면 대시보드를 함께 갱신합니다.`);
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      if (!syncResult) throw new Error('업데이트가 계속 진행 중입니다. 잠시 후 새로고침해 주세요.');
    }
  } catch (error) {
    notify(error.message, true); refreshBusy = false; $('#refresh').disabled = false; $('#refresh').textContent = originalLabel; return;
  }
  try {
    await Promise.all([loadSummary(), activeView === 'overview' ? Promise.all([loadDashboard(), loadPosts()]) : activeView === 'data' ? loadData() : loadHistory()]);
    $('#updated').textContent = '마지막 확인 ' + new Date().toLocaleTimeString('ko-KR');
    if (!silent) {
      if (syncResult.status === 'success') notify(`최신 데이터를 반영했습니다. 새 게시물 ${syncResult.result?.created || 0}개 추가`);
      else {
        const errors = syncResult.errors || [];
        const reason = errors.includes('threads_token_expired_or_invalid') ? 'Threads 연결 인증을 갱신해야 합니다.' : errors.includes('threads_rate_limited') ? 'Meta 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.' : errors.includes('profile_screen_unavailable') ? (profileWarning || '프로필 화면 수집에 실패했습니다.') + ' 프로필 수치는 마지막 저장값을 유지합니다. API 갱신 결과는 반영했습니다.' : 'Threads 업데이트 일부를 완료하지 못했습니다. 마지막 저장 데이터를 표시합니다.';
        notify(reason, true);
      }
    }
  } catch (error) { notify(error.message, true); }
  finally { refreshBusy = false; $('#refresh').disabled = false; $('#refresh').textContent = originalLabel; }
}
function requestProfileSnapshot() {
  if (document.documentElement.dataset.threadsProfileBridge !== 'ready') {
    return Promise.reject(new Error('크롬에 Threads Insight 프로필 연결 확장 프로그램을 설치하고 대시보드를 다시 열어 주세요.'));
  }
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const finish = (error, snapshot) => {
      clearTimeout(timer); window.removeEventListener('threads-profile-response', receive);
      error ? reject(new Error(error)) : resolve(snapshot);
    };
    const receive = event => {
      if (event.detail?.id !== id) return;
      finish(event.detail.error || (!event.detail.snapshot ? '프로필 응답이 올바르지 않습니다.' : null), event.detail.snapshot);
    };
    const timer = setTimeout(() => finish('프로필 화면 수집 시간이 초과되었습니다.'), 55000);
    window.addEventListener('threads-profile-response', receive);
    window.dispatchEvent(new CustomEvent('threads-profile-request', {detail: {id}}));
  });
}
$('#chat-form').addEventListener('submit', sendChat);
$('#new-chat').addEventListener('click', newChat);
$('#refresh').addEventListener('click', () => refresh());
$('#close-dialog').addEventListener('click', () => $('#post-dialog').close());
document.querySelectorAll('.nav').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view)));
document.querySelectorAll('.suggestion').forEach(button => button.addEventListener('click', () => { $('#chat-input').value = button.dataset.question; $('#chat-form').requestSubmit(); }));
$('#more-posts').addEventListener('click', () => loadPosts(true).catch(error => notify(error.message, true)));
$('#more-data').addEventListener('click', () => loadData(true).catch(error => notify(error.message, true)));
$('#more-history').addEventListener('click', () => loadHistory(true).catch(error => notify(error.message, true)));
$('#chat-input').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#chat-form').requestSubmit(); } });
document.querySelectorAll('[data-follower-range]').forEach((button, index, buttons) => {
  button.addEventListener('click', () => selectFollowerRange(button.dataset.followerRange));
  button.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
    if (event.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    if (next != null) { event.preventDefault(); buttons[next].focus(); selectFollowerRange(buttons[next].dataset.followerRange); }
  });
});
refresh(true);
api('/api/chat/status').then(status => { aiConfigured = status.configured; }).catch(error => notify(error.message, true));
// Stored data is read on page open, tab change, or the user's refresh request.
