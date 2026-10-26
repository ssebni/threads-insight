'use strict';
let collaborationRows = [], collaborationCatalog = [], editingCollaboration = null;
const won = value => number(value) + '원';

function collaborationMetrics(performance) {
  const root = element('div', 'collab-metrics');
  for (const [key, label] of [['views','조회수'], ['likes','좋아요'], ['replies','댓글'], ['reposts','리포스트'], ['follows','팔로워 유입']]) {
    const known = performance.coverage[key], total = performance.post_count;
    const item = element('div'); item.append(metric(label, performance.totals[key]));
    if (known < total) item.append(element('small', 'caption', `${known}/${total}개 확인 · 미확인 제외`));
    root.append(item);
  }
  return root;
}

async function appendCollaborationTags(root, postId) {
  const section=element('section','post-collaboration-tags'); section.append(element('h3','','협업 해시태그'));
  const status=element('p','caption');status.setAttribute('role','status');
  try {
    const result=await api('/api/collaborations');
    const labels=element('div','post-tag-choices');
    for (const contract of result.items) {
      const label=element('label','post-tag-choice'), input=element('input');input.type='checkbox';input.checked=Boolean(contract.posts?.[postId]);
      label.append(input,document.createTextNode('#'+contract.tag));labels.append(label);
      input.addEventListener('change',async()=>{
        const assigned=input.checked;input.disabled=true;
        try {
          await api(`/api/collaborations/${contract.id}/posts/${postId}`,{method:'PUT',body:JSON.stringify({assigned,fee_override:contract.fee_mode==='per_post' ? (contract.posts?.[postId]?.fee_override ?? null) : null})});
          status.textContent=assigned ? '해시태그를 연결했습니다.' : '해시태그 연결을 해제했습니다.';
          if (activeView==='data')await loadCollaborations();
        }catch(error){input.checked=!assigned;status.textContent=error.message;}
        finally{input.disabled=false;}
      });
    }
    if (!result.items.length)labels.append(element('p','caption','협업 관리에서 협업을 먼저 만들어 주세요.'));
    section.append(labels);
  } catch(error){status.textContent='협업 해시태그를 불러오지 못했습니다. '+error.message;}
  section.append(action('새 협업 만들기',()=>{$('#post-dialog').close();switchView('data').then(()=>editCollaboration());}),status);root.append(section);
}

async function loadCollaborations() {
  const [result, catalog, analysis] = await Promise.all([api('/api/collaborations'), api('/api/collaborations/catalog'),api('/api/data?kind=collaboration&limit=100')]);
  collaborationRows = result.items; collaborationCatalog = catalog.items;
  const stats = $('#collaboration-finance'); stats.replaceChildren();
  for (const [key,label] of [['agreed','총 약정 원고료'], ['paid','입금 완료'], ['outstanding','미수금']]) {
    const card = element('article'); card.append(element('span','',label), element('strong','',won(result.finance[key]))); stats.append(card);
  }
  $('#collaboration-finance-note').textContent = result.finance.overpaid ? `약정 초과 입금 ${won(result.finance.overpaid)} · 협업별 확인이 필요합니다.` : '세금·수수료 차감 전 입력 금액 기준입니다. 입금액은 직접 기록합니다.';
  const root = $('#collaboration-list'); root.replaceChildren();
  for (const contract of collaborationRows) {
    const card = element('article', 'collaboration-card');
    card.append(element('h3', '', '#' + contract.tag), element('p','caption', `${contract.date} · 게시물 ${contract.performance.post_count}개 · ${contract.finance.status}`),
      element('strong','contract-fee',won(contract.finance.agreed)),
      element('p','caption', contract.fee_mode === 'bundle' ? '협업 전체 일괄 원고료' : `게시물당 기본 ${won(contract.fee)} · 개별 금액 변경 가능`),
      collaborationMetrics(contract.performance), element('p','memo-content',contract.memo || '협업 메모 없음'),
      action('게시물 연결 · 원고료 관리 ↗', () => showCollaboration(contract.id)));
    root.append(card);
  }
  if (!collaborationRows.length) root.append(element('p','empty','첫 협업 해시태그를 만들고 게시물을 연결해 보세요.'));
  const records=$('#collaboration-analysis');records.replaceChildren();
  analysis.items.forEach(record=>{
    const row=element('div','collaboration-picker-row');
    row.append(element('span','',`${record.date} · #${record.tag} · ${won(record.value)} · ${record.memo || '메모 없음'}`),
      action('수정',()=>editCollaboration(collaborationRows.find(contract=>contract.id===record.contract_id))),
      action('삭제',async()=>{
        if(!confirm('#'+record.tag+' 협업과 분석 기록을 삭제할까요? 원본 게시물은 유지됩니다.'))return;
        try{await api('/api/data/'+record.id,{method:'DELETE'});await loadCollaborations();notify('협업 분석 기록을 삭제했습니다.');}
        catch(error){notify(error.message,true);}
      }));records.append(row);
  });
  if(!analysis.items.length)records.append(element('p','caption','협업을 새로 저장하거나 기존 협업을 수정·저장하면 기준일·총 약정 원고료·메모가 분석 기록으로 연결됩니다.'));
  if(analysis.has_more)records.append(element('p','caption','최근 100개 협업 분석 기록을 표시합니다.'));
}

function editCollaboration(contract = null) {
  editingCollaboration = contract?.id || null;
  const form = $('#collaboration-form'); form.reset(); form.hidden = false;
  form.elements.tag.disabled = Boolean(contract);
  form.elements.tag.value = contract?.tag || '';
  form.elements.date.value = contract?.date || new Date(Date.now() + 9*3600000).toISOString().slice(0,10);
  form.elements.fee_mode.value = contract?.fee_mode || 'bundle';
  form.elements.fee.value = contract?.fee ?? 0;
  form.elements.paid_amount.value = contract?.paid_amount ?? 0;
  form.elements.memo.value = contract?.memo || '';
  $('#collaboration-form-title').textContent = contract ? '#' + contract.tag + ' 협업 수정' : '새 협업 해시태그';
  $('#collaboration-save-status').textContent = contract ? '해시태그 이름은 고정됩니다. 원고료·날짜·메모는 수정할 수 있습니다.' : '';
  updateFeeLabel(); form.scrollIntoView({behavior:'smooth', block:'center'}); form.elements[contract ? 'fee' : 'tag'].focus();
}

function updateFeeLabel() {
  const bundle = $('#collaboration-form').elements.fee_mode.value === 'bundle';
  $('#contract-fee-label').textContent = bundle ? '협업 전체 원고료 (원)' : '게시물 1개당 기본 원고료 (원)';
  $('#contract-fee-help').textContent = bundle ? '게시물을 여러 개 연결해도 이 금액은 한 번만 계산합니다.' : '연결된 게시물 수 × 기본 원고료. 게시물별 다른 금액도 설정할 수 있습니다.';
}

async function saveCollaboration(event) {
  event.preventDefault(); const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]'); submit.disabled = true;
  const body = {tag:form.elements.tag.value.replace(/^#/,''), date:form.elements.date.value,
    fee_mode:form.elements.fee_mode.value, fee:Number(form.elements.fee.value),
    paid_amount:Number(form.elements.paid_amount.value), memo:form.elements.memo.value};
  if (Array.from(body.tag.normalize('NFC')).length > 10) { $('#collaboration-save-status').textContent = '해시태그는 #을 제외하고 10자 이내로 입력해 주세요.'; submit.disabled = false; return; }
  try {
    const dataBody={date:body.date,value:body.fee,memo:body.memo,collaboration:{tag:body.tag,fee_mode:body.fee_mode,paid_amount:body.paid_amount}};
    await api('/api/data' + (editingCollaboration ? '/collaboration_' + editingCollaboration : ''), {method:editingCollaboration ? 'PUT' : 'POST', body:JSON.stringify(dataBody)});
    form.hidden = true; await loadCollaborations(); notify('협업 정보를 저장했습니다. 게시물을 연결하면 성과가 합산됩니다.');
  } catch (error) { $('#collaboration-save-status').textContent = error.message; }
  finally { submit.disabled = false; }
}

async function changeCollaborationPost(contract, postId, assigned, feeOverride = null) {
  await api(`/api/collaborations/${contract.id}/posts/${postId}`, {method:'PUT',body:JSON.stringify({assigned,fee_override:feeOverride})});
  await loadCollaborations();
}

function showCollaboration(identity) {
  const contract = collaborationRows.find(row=>row.id === identity); if (!contract) return;
  const dialog = $('#collaboration-dialog'), root = $('#collaboration-detail'); root.replaceChildren();
  $('#collaboration-dialog-title').textContent = '#' + contract.tag;
  const finance = element('div', 'contract-finance');
  finance.append(metric('약정 원고료',contract.finance.agreed),metric('입금액',contract.finance.paid),metric('미수금',contract.finance.outstanding),element('span','badge',contract.finance.status));
  root.append(finance, collaborationMetrics(contract.performance), element('p','caption','각 지표는 연결된 게시물의 최신 누적값 합계입니다. 팔로워 유입은 확인된 게시물만 합산하며 계정 순증과 다릅니다.'));
  const controls = element('div','form-actions');
  controls.append(action('원고료 · 입금액 수정',()=>{dialog.close(); editCollaboration(contract);}), action('협업 삭제',async()=>{
    if (!confirm('#' + contract.tag + ' 협업과 연결·원고료 기록을 삭제할까요? Threads 게시물과 메모는 유지됩니다.')) return;
    try { await api('/api/data/collaboration_' + contract.id, {method:'DELETE'}); dialog.close(); await loadCollaborations(); notify('협업을 삭제했습니다.'); }
    catch(error){ $('#collaboration-dialog-status').textContent=error.message; }
  })); root.append(controls, element('h3','','연결된 게시물'));
  const assignedRoot = element('div','collaboration-posts');
  contract.items.forEach(post=>{
    const card = element('article','collaboration-post');
    card.append(element('p','caption',post.timestamp ? new Date(post.timestamp).toLocaleString('ko-KR') : '게시일 미확인'),element('p','post-text',post.text || '(본문 없음)'));
    if (contract.fee_mode === 'per_post') {
      const label = element('label','','이 게시물 원고료 (원)'), field = element('input'); field.type='number';field.min='0';field.max='1000000000000';field.step='1';field.placeholder=String(contract.fee);field.value=post.fee_override ?? '';
      label.append(field); card.append(label, action('개별 금액 저장', async()=>{
        if (!field.checkValidity()) {field.reportValidity();return;}
        try {await changeCollaborationPost(contract,post.id,true,field.value === '' ? null : Number(field.value)); showCollaboration(identity);$('#collaboration-dialog-status').textContent='금액을 저장했습니다.';}
        catch(error){$('#collaboration-dialog-status').textContent=error.message;}
      }));
    }
    card.append(action('스레드 상세 · 메모',()=>{dialog.close(); showPost(post.id);}),action('연결 해제',async()=>{
      try{await changeCollaborationPost(contract,post.id,false);showCollaboration(identity);}
      catch(error){$('#collaboration-dialog-status').textContent=error.message;}
    })); assignedRoot.append(card);
  });
  if (!contract.items.length) assignedRoot.append(element('p','empty','아래 목록에서 협업 게시물을 선택해 주세요.'));
  root.append(assignedRoot,element('h3','','게시물 연결'));
  const search = element('input'); search.type='search';search.placeholder='게시물 본문 검색';search.setAttribute('aria-label','연결할 게시물 검색');
  const picker = element('div','collaboration-picker');
  function drawPicker() {
    picker.replaceChildren();
    const query=search.value.toLocaleLowerCase();
    collaborationCatalog.filter(post=>!contract.posts?.[post.id] && (post.text || '').toLocaleLowerCase().includes(query)).forEach(post=>{
      const row=element('div','collaboration-picker-row');
      const label=element('div');label.append(element('small','caption',new Date(post.timestamp).toLocaleDateString('ko-KR')),element('p','', (post.text || '(본문 없음)').slice(0,140)));
      row.append(label,action('연결',async event=>{
        const button=event?.currentTarget;
        if(button)button.disabled=true;
        try{await changeCollaborationPost(contract,post.id,true);showCollaboration(identity);}
        catch(error){$('#collaboration-dialog-status').textContent=error.message;if(button)button.disabled=false;}
      }));picker.append(row);
    });
    if (!picker.children.length)picker.append(element('p','empty','연결 가능한 게시물이 없습니다.'));
  }
  search.addEventListener('input',drawPicker);drawPicker();root.append(search,picker);
  $('#collaboration-dialog-status').textContent='';if (!dialog.open)dialog.showModal();
}

$('#new-collaboration').addEventListener('click',()=>editCollaboration());
$('#collaboration-form').addEventListener('submit',saveCollaboration);
$('#collaboration-form').elements.fee_mode.addEventListener('change',updateFeeLabel);
$('#cancel-collaboration').addEventListener('click',()=>{$('#collaboration-form').hidden=true;});
$('#close-collaboration').addEventListener('click',()=>$('#collaboration-dialog').close());
