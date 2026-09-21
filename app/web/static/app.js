'use strict';
const $=selector=>document.querySelector(selector);
const P=window.RadarPresentation;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy=value=>JSON.parse(JSON.stringify(value));
const icon=name=>`<img src="/static/icons/${name}.svg" alt="">`;
const state={meta:null,tasks:[],alerts:[],filter:'all',view:'dashboard',draft:null,editing:null,compilation:null,warnings:[],auditTask:null,auditTab:'checks',demoId:null,archiveId:null,refreshing:null};
let toastTimer,auditRequest=0;
function toast(message){$('#toast-text').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4000);}
function showError(selector,message){const box=$(selector);box.textContent=message;box.hidden=!message;if(message&&box.hasAttribute('tabindex'))box.focus();}
async function api(path,method='GET',body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),50000);
 try{const options={method,credentials:'same-origin',headers:{},signal:controller.signal};if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}const r=await fetch(path,options);let data;try{data=await r.json();}catch{throw new Error('服务暂时没有返回有效结果，请稍后重试。');}if(!r.ok)throw new Error(data.error||'请求未完成，请稍后重试。');return data;}
 catch(e){if(e.name==='AbortError')throw new Error('服务响应较慢。输入内容已保留，请稍后重试。');throw e;}finally{clearTimeout(timer);}
}
function replaceHtml(selector,html){
 const element=$(selector);if(element.dataset.rendered===html)return;
 const active=document.activeElement,inside=element.contains(active),action=active?.dataset.action,id=active?.dataset.id;
 element.innerHTML=html;element.dataset.rendered=html;
 if(inside&&action&&id){const buttons=Array.from(element.querySelectorAll('button[data-id]'));const target=buttons.find(b=>b.dataset.id===id&&b.dataset.action===action)||buttons.find(b=>b.dataset.id===id&&['pause','resume'].includes(b.dataset.action));target?.focus({preventScroll:true});}
}
function setView(view){
 if(!['dashboard','inbox','demo','about'].includes(view))return;
 state.view=view;for(const v of ['dashboard','inbox','demo','about'])$('#'+v+'-view').hidden=v!==view;
 document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
 const title={dashboard:'我的提醒',inbox:'提醒记录',demo:'演示体验',about:'使用帮助'}[view];$('#page-title').textContent=title;document.title=title+' · 照看';
 syncNavigation(false);if(view==='demo')renderDemo();
}
function modeTag(mode){return `<span class="mode-tag ${mode==='live'?'live':'replay'}">${mode==='live'?'真实数据':'模拟数据'}</span>`;}
function taskCard(task){
 const s=task.state,terminal=['EXPIRED','ARCHIVED'].includes(s.status),rules=task.spec.conditions.map((c,i)=>`${i?'<span class="rule-logic">'+(task.spec.condition_logic==='AND'?'且':'或')+'</span>':''}${esc(P.describe(c))}`).join('<br>');
 let result=s.last_decision?'上次检查：'+P.summary(s.last_decision,Object.keys(s.pending_events||{}).length):'等待首次检查。';
 if(s.paused)result='检查已暂停，已有记录保留。';else if(terminal)result=P.schedule(task);else if(s.status==='SUSPENDED')result='非交易时段，等待下次检查。';
 const q=s.last_snapshot?.quote;
 const quote=q?(q.status==='ok'&&q.last!=null?`上次检查 <strong>${esc(P.number(q.last))}元</strong>${typeof q.change==='number'?' · '+esc(P.number(P.percent(q.change)))+'%':''}`:'行情暂不可用'):'';
 return `<article class="task-card" data-task="${esc(task.id)}"><div class="task-main"><div><div class="task-name"><h3>${esc(task.spec.target.name)}</h3>${modeTag(task.spec.data_mode)}</div><div class="ticker">${esc(task.spec.target.symbol)}</div></div><div class="rules-summary">${rules}</div><div class="task-state"><span class="status ${esc(s.status)}">${esc(P.statusLabel(task))}</span><small>${esc(P.schedule(task))}</small></div><div class="task-actions"><button class="text-button record-button" data-action="audit" data-id="${esc(task.id)}">查看记录</button>${!terminal?`<button class="text-button" data-action="edit" data-id="${esc(task.id)}">修改</button><button class="text-button" data-action="${s.paused||s.status==='PENDING'?'resume':'pause'}" data-id="${esc(task.id)}">${s.paused||s.status==='PENDING'?'恢复':'暂停'}</button><button class="text-button" data-action="archive" data-id="${esc(task.id)}">归档</button>`:''}</div></div><div class="task-bottom"><span class="last-decision">${esc(result)}</span>${quote?'<span class="snapshot-quote">'+quote+'</span>':''}<span class="last-check">${s.last_check_time?'检查于 '+esc(P.formatDate(s.last_check_time)):'等待首次检查'}${task.spec.data_mode==='replay'?' · 演示时钟':''}</span></div></article>`;
}
function renderTasks(){
 $('#nav-count').textContent=state.tasks.length;$('#task-total').textContent=state.tasks.length;
 const visible=state.tasks.filter(t=>P.visibleTask(t,state.filter,$('#task-search').value.trim()));
 const html=visible.length?visible.map(taskCard).join(''):`<div class="empty">${icon('bell')}<h2>${state.tasks.length?'没有符合筛选的提醒':'还没有提醒'}</h2><p>${state.tasks.length?'换个公司名称或查看全部提醒。':'设置股价或公告条件，发生变化时回来查看提醒。'}</p>${state.tasks.length?'<button class="secondary" data-action="clear-filter">查看全部</button>':'<button class="primary" data-action="new">新建提醒</button><button class="text-button" data-view="demo">先试一次演示</button>'}</div>`;
 replaceHtml('#task-list',html);$('#list-summary').textContent=`显示 ${visible.length} 条，共 ${state.tasks.length} 条`;
 if(state.view==='demo')renderDemo();
}
function renderAlerts(){
 $('#inbox-count').textContent=state.alerts.length;
 replaceHtml('#alert-list',state.alerts.length?state.alerts.map(a=>{
 const name=state.tasks.find(t=>t.id===a.task_id)?.spec.target.name||a.title.split(' · ')[0];
 const message=a.kind==='condition'&&a.evidence?a.evidence.filter(c=>c.satisfied).map(e=>esc(e.type==='ANNOUNCEMENT_EVENT'?e.display_text:P.describe(e))).join('；'):esc(a.message);
 return `<article class="alert-card ${esc(a.kind)}"><span class="alert-type">${{condition:'条件满足',health:'数据异常',recovery:'已恢复'}[a.kind]||'任务通知'}</span><div><h3>${esc(name)} ${modeTag(a.mode)}</h3><p>${message}</p><small>${esc(P.formatDate(a.timestamp))}${a.mode==='replay'?' · 演示时钟':''}</small></div><button class="text-button" data-action="audit" data-id="${esc(a.task_id)}">查看记录</button></article>`;
 }).join(''):'<div class="empty">'+icon('inbox')+'<h2>还没有提醒记录</h2><p>条件满足或数据状态变化后，通知会显示在这里。</p></div>');
}
async function refresh(){
 if(state.refreshing)return state.refreshing;
 state.refreshing=(async()=>{try{const [tasks,alerts,health]=await Promise.all([api('/api/tasks'),api('/api/alerts'),api('/api/health')]);state.tasks=tasks.tasks;state.alerts=alerts.alerts;renderTasks();renderAlerts();showError('#connection-error','');$('#service-state').textContent=health.scheduler_enabled?(health.status==='ok'?'服务已连接':'服务需要留意'):'自动检查未开启';$('#service-dot').style.background=health.status==='ok'?'var(--green)':'var(--amber)';$('#health-detail').textContent='服务启动：'+P.formatDate(health.started_at)+'；最近调度：'+P.formatDate(health.heartbeat);}catch(error){$('#service-state').textContent='连接中断';$('#service-dot').style.background='var(--red)';showError('#connection-error','暂时无法更新状态，页面保留上次结果。请稍后刷新。');}})();
 try{await state.refreshing;}finally{state.refreshing=null;}
}
const scenarios=[['normal','未达条件'],['drop','下跌至3.8%'],['deeper','继续下跌'],['announcement','新业绩预告'],['advance','推进31分钟'],['timeout','行情超时'],['recover','恢复来源']];
const extraScenarios=[['same_announcement','重复公告'],['heat','量比升至3.6'],['http500','服务错误'],['stale','数据过期'],['conflict','指标冲突'],['event_failure','公告故障'],['closed','休市'],['open','开市']];
function renderDemo(){
 const demos=state.tasks.filter(t=>t.spec.data_mode==='replay');if(!demos.some(t=>t.id===state.demoId))state.demoId=demos[0]?.id||null;
 const options=demos.map(t=>`<option value="${esc(t.id)}">${esc(t.spec.target.name)} · ${esc(P.statusLabel(t))} · ${esc(P.formatDate(t.state.created_at))}</option>`).join('');
 replaceHtml('#demo-target',options||'<option value="">先创建一条演示提醒</option>');$('#demo-target').value=state.demoId||'';
 const t=demos.find(x=>x.id===state.demoId),disabled=!t||t.state.paused||['EXPIRED','ARCHIVED','PENDING'].includes(t.state.status);
 const buttons=items=>items.map(([key,label])=>`<button type="button" data-action="scenario" data-scenario="${key}" ${disabled?'disabled':''}>${label}</button>`).join('');
 const detailWasOpen=$('#scenario-buttons details')?.open;
 replaceHtml('#scenario-buttons','<div class="scenarios">'+buttons(scenarios)+'</div><details'+(detailWasOpen?' open':'')+'><summary>更多测试情景</summary><div class="scenarios">'+buttons(extraScenarios)+'</div></details>');
 $('#demo-state').textContent=t?(disabled?'这条任务已停止检查。恢复任务或新建示例后再测试。':'使用模拟昨收100元；推进时间只影响这条演示任务。'):'示例会先显示规则，确认后才开始。';
 replaceHtml('#demo-task',t?taskCard(t):'');
}
function showCompose(demo=false){
 if(!state.meta)return;
 if(demo){$('#mode').value='replay';$('#use-ai').checked=false;$('#target').value='';$('#prompt').value='未来两周帮我盯住贵州茅台：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。';}
 state.editing=null;showError('#parse-error','');updateModeHint();$('#compose-dialog').showModal();$('#prompt').focus();
}
function updateModeHint(){
 $('#mode-notice').textContent=($('#mode').value==='replay'?'演示使用模拟行情。':'将从真实来源取数，失败时会显示数据异常。')+($('#use-ai').checked?' 输入内容将由DeepSeek提取规则。':' 本次使用本地规则解析。');
}
function selectedTarget(){return state.meta.symbols.find(x=>x.symbol===$('#target').value)||null;}
async function parsePrompt(event){
 event.preventDefault();if(!$('#compose-form').reportValidity())return;
 const b=$('#parse-button');b.disabled=true;b.textContent='正在整理规则…';showError('#parse-error','');
 try{const target=selectedTarget(),prompt=$('#prompt').value;
 const found=state.meta.symbols.filter(s=>prompt.includes(s.name)||prompt.includes(s.symbol.slice(0,6)));
 if(target&&found.some(s=>s.symbol!==target.symbol))throw new Error('输入中的公司与补充公司不同。请清空补充公司，或修改输入后重试。');
 const result=await api('/api/tasks/parse','POST',{prompt,target,data_mode:$('#mode').value,use_ai:$('#use-ai').checked});
 if(target&&result.task_spec.target.symbol!==target.symbol)throw new Error('输入识别为'+result.task_spec.target.name+'，与补充公司不同。请确认公司后重新生成。');
 state.draft=result.task_spec;state.compilation=result.compilation;state.warnings=result.warnings;state.editing=null;$('#compose-dialog').close();showRules();
 }catch(e){showError('#parse-error',e.message);}finally{b.disabled=false;b.textContent='查看规则';}
}
function conditionEditor(c,index){
 let fields='';const d=P.toDisplay(c);
 if(['PRICE_CHANGE_RATIO','PRICE','HEAT'].includes(c.type)){
  const ratio=c.type==='PRICE_CHANGE_RATIO';
  fields=ratio?`<select class="condition-metric" data-field="direction" aria-label="条件${index+1}涨跌方向"><option value="down" ${d.direction==='down'?'selected':''}>较昨收下跌</option><option value="up" ${d.direction==='up'?'selected':''}>较昨收上涨</option></select>`:`<span class="condition-metric">${c.type==='PRICE'?'股价':'量比'}</span>`;
  const labels=ratio?{'>=':'达到','>':'超过','<':'低于','<=':'不高于'}:{'>=':'不低于','>':'高于','<':'低于','<=':'不高于'};
  fields+=`<select class="condition-operator" data-field="operator" aria-label="条件${index+1}比较方式">${['>=','>','<','<='].map(o=>`<option value="${esc(o)}" ${d.operator===o?'selected':''}>${labels[o]}</option>`).join('')}</select><input class="condition-value" data-field="threshold" type="number" min="${ratio?0:0.000000001}" step="any" required aria-label="条件${index+1}数值" value="${d.value}"><span class="condition-unit">${ratio?'%':c.type==='PRICE'?'元':''}</span>`;
 }else if(c.type==='ANNOUNCEMENT_EVENT')fields=`<select class="event-select" data-field="event_category" aria-label="条件${index+1}公告类别">${Object.entries(P.eventLabels).map(([key,label])=>`<option value="${key}" ${c.event_category===key?'selected':''}>发布${label}</option>`).join('')}</select>`;
 else fields=`<input class="calendar-input" data-field="at" type="datetime-local" step="1" value="${P.dateInput(c.at)}" aria-label="条件${index+1}提醒时间" required>`;
 return `<div class="review-condition" data-condition="${index}"><div class="review-label">条件 ${index+1}${c.type==='CALENDAR'?' · 北京时间':''}</div><div class="condition-edit">${fields}</div><p class="boundary-note" data-boundary="${index}"></p></div>`;
}
function showRules(){
 const d=state.draft;if(!d)return;
 const editing=!!state.editing;
 $('#rule-title').textContent=editing?'修改提醒':'设置提醒';$('#activate-button').textContent=editing?'保存修改':'开始监控';$('#cancel-rule').textContent=editing?'取消':'返回';
 $('#rule-body').innerHTML=`<div class="form-row review-target"><label for="rule-target">关注公司</label><select id="rule-target" ${editing?'disabled':''}>${state.meta.symbols.map(t=>`<option value="${t.symbol}" ${t.symbol===d.target.symbol?'selected':''}>${esc(t.name)} · ${t.symbol.slice(0,6)}</option>`).join('')}</select></div><div class="form-row"><span class="row-label">数据模式</span><span>${modeTag(d.data_mode)}</span></div><div class="review-conditions">${d.conditions.map(conditionEditor).join('')}</div><div class="form-row"><label for="rule-logic">触发方式</label><select id="rule-logic"><option value="OR" ${d.condition_logic==='OR'?'selected':''}>满足任意一条</option><option value="AND" ${d.condition_logic==='AND'?'selected':''}>全部条件满足</option></select></div><div class="form-row"><label for="rule-end">结束时间</label><input id="rule-end" type="datetime-local" step="1" value="${P.dateInput(d.validity.end_time)}" required aria-describedby="timezone-note"></div><p class="field-hint" id="timezone-note">北京时间，到期后自动停止。</p><div class="form-row"><span class="row-label">提醒方式</span><span>站内提醒</span></div><p class="field-hint">关闭页面后不发送系统推送。重新打开“提醒记录”查看。</p><p class="summary-preview" id="rule-summary"></p>${state.compilation&&state.compilation.engine!=='deepseek'?'<p class="review-warnings">'+(state.compilation.fallback_reason?'AI暂时不可用，已用本地解析提取规则。请核对后开始。':'本次使用本地规则解析。')+'</p>':''}${editing?'<p class="field-hint">修改后保留历史记录，已有提醒间隔继续生效。</p>':''}<details class="advanced"><summary>更多设置</summary><div class="form-row"><label for="rule-cooldown">提醒间隔</label><div><input id="rule-cooldown" type="number" min="0" max="1440" step="1" required value="${d.governance.cooldown_minutes}" aria-label="提醒间隔（分钟）"><p class="field-hint">分钟。期间继续检查，保留新公告。</p></div></div><div class="form-row"><label for="rule-frequency">检查频率</label><div><input id="rule-frequency" type="number" min="10" max="3600" step="1" required value="${d.governance.frequency_seconds}" aria-label="检查间隔（秒）"><p class="field-hint">秒。相同事件不会重复提醒。</p></div></div><div class="form-row"><label for="rule-hours">价格检查时间</label><select id="rule-hours"><option value="true" ${d.governance.trading_hours_only?'selected':''}>仅交易时段</option><option value="false" ${!d.governance.trading_hours_only?'selected':''}>不限时段</option></select></div><p class="field-hint">不限时段仍要求来源数据有效；公告独立检查。</p></details><details class="technical"><summary>技术详情</summary><p>${state.compilation?'实际解析：'+esc(state.compilation.engine)+' · '+esc(state.compilation.model||'本地解析')+' · '+state.compilation.latency_ms+' ms':'当前规则版本：'+d.version}</p>${(state.warnings||[]).map(w=>'<p>'+esc(w)+'</p>').join('')}<p>价格按交易日与规则版本去重，公告按事件指纹去重。</p><button type="button" class="secondary" id="refresh-json">读取当前设置为JSON</button><textarea class="json-text" id="rule-json" aria-label="完整规则JSON">${esc(JSON.stringify(d,null,2))}</textarea><button type="button" class="secondary" id="apply-json">应用JSON草稿</button><p>仅修改草稿，点击开始或保存后生效。服务端会再次校验。</p></details><p id="rule-error" class="inline-error" role="alert" tabindex="-1" hidden></p>`;
 updateRulePreview();if(!$('#rule-dialog').open)$('#rule-dialog').showModal();
}
function collectRules(){
 const d=copy(state.draft);
 document.querySelectorAll('.review-condition').forEach(row=>{const i=Number(row.dataset.condition),c=d.conditions[i],field=name=>row.querySelector('[data-field="'+name+'"]');
 if(['PRICE_CHANGE_RATIO','PRICE','HEAT'].includes(c.type))d.conditions[i]=P.fromDisplay(c,{direction:field('direction')?.value,operator:field('operator').value,value:field('threshold').value});
 else if(c.type==='CALENDAR')c.at=P.readDate(field('at').value,c.at);else c.event_category=field('event_category').value;
 });
 d.target=copy(state.meta.symbols.find(t=>t.symbol===$('#rule-target').value));
 d.condition_logic=$('#rule-logic').value;d.validity.end_time=P.readDate($('#rule-end').value,d.validity.end_time);
 d.governance.cooldown_minutes=Number($('#rule-cooldown').value);d.governance.frequency_seconds=Number($('#rule-frequency').value);d.governance.trading_hours_only=$('#rule-hours').value==='true';
 return d;
}
function updateRulePreview(){
 try{const d=collectRules();$('#timezone-note').textContent='北京时间 '+new Date(d.validity.end_time).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'long',timeStyle:'short',hour12:false})+'，到期后停止。';$('#rule-summary').textContent=d.target.name+'，'+d.conditions.map(P.describe).join(d.condition_logic==='AND'?'，且':'，或')+'时保存站内提醒。监控至'+P.formatDate(d.validity.end_time)+'。';
 d.conditions.forEach((c,i)=>{const note=$('[data-boundary="'+i+'"]');if(c.type==='PRICE_CHANGE_RATIO'||c.type==='PRICE'||c.type==='HEAT'){const disp=P.toDisplay(c),relation=['>=','<='].includes(c.operator)?'包含':'不包含';note.textContent=relation+'正好'+P.number(disp.value)+(c.type==='PRICE_CHANGE_RATIO'?'%':c.type==='PRICE'?'元':'')+'。'+(c.type==='PRICE_CHANGE_RATIO'&&['<','<='].includes(disp.operator)?(disp.direction==='down'?'也包含持平和上涨。':'也包含持平和下跌。'):'');}else note.textContent='';});
 }catch{if($('#rule-summary'))$('#rule-summary').textContent='补全条件后，这里会显示提醒内容。';}
}
async function saveRules(event){
 event.preventDefault();const b=$('#activate-button');if(b.disabled)return;
 if(!$('#rule-form').reportValidity())return;b.disabled=true;showError('#rule-error','');
 try{const spec=collectRules(),editing=!!state.editing;
 if(new Date(spec.validity.end_time)<=new Date(spec.validity.start_time))throw new Error('结束时间需要晚于开始时间。');
 if(new Date(spec.validity.end_time)<=new Date())throw new Error('结束时间已过去，请选择之后的时间。');
 let t;if(editing)t=await api('/api/tasks/'+state.editing.id,'PUT',{task_spec:spec,expected_version:state.editing.spec.version});else t=await api('/api/tasks/create','POST',{task_spec:spec,activate:true,compilation_id:state.compilation?.compilation_id||null});
 if(t.spec.data_mode==='replay')state.demoId=t.id;$('#rule-dialog').close();toast(editing?'修改已保存。':'提醒已创建。');
 // Save success is distinct from a first-check failure; never submit the task twice.
 try{await api('/api/simulate/tick','POST',{task_id:t.id});}catch{showError('#page-error','提醒已保存，首次检查暂未完成。可在任务记录中查看后续状态。');}
 await refresh();
 }catch(e){showError('#rule-error',e.message);}finally{b.disabled=false;}
}
function evidenceCard(c){
 const truth=c.satisfied===true?'true':c.satisfied===false?'false':'unknown';
 const label=['PRICE','PRICE_CHANGE_RATIO','HEAT'].includes(c.type)?P.describe(c):c.display_text;
 const metric=typeof c.actual_value==='number'&&c.type!=='ANNOUNCEMENT_EVENT'?(c.type==='PRICE_CHANGE_RATIO'?P.number(P.percent(c.actual_value))+'%':P.number(c.actual_value)+(c.type==='PRICE'?'元':'')):'';
 return `<div class="evidence-card"><div class="evidence-heading"><span>${esc(label)}</span><span class="truth ${truth}">${{true:'已满足',false:'未满足',unknown:c.suspended?'休市中':'无法判断'}[truth]}</span></div>${metric?'<strong class="evidence-metric">'+esc(metric)+'</strong>':''}<p>${esc(c.reason)}</p>${c.formula?'<p>现价 '+esc(c.last)+'元，昨收 '+esc(c.previous_close)+'元。</p>':''}${(c.events||[]).map(e=>'<p>'+esc(e.title)+'<br><span class="muted">'+esc(P.formatDate(e.published_at))+(e.freshness_note?' · '+esc(e.freshness_note):'')+'</span></p>').join('')}<p class="evidence-source">${esc(c.source||'系统时钟')} · ${esc(P.formatDate(c.observed_at))}</p>${c.coverage?'<p class="evidence-source">'+esc(c.coverage)+'</p>':''}</div>`;
}
function selectAuditTab(versions){state.auditTab=versions?'versions':'checks';$('#show-audits').classList.toggle('active',!versions);$('#show-versions').classList.toggle('active',versions);$('#show-audits').setAttribute('aria-pressed',String(!versions));$('#show-versions').setAttribute('aria-pressed',String(versions));}
async function showAudits(id){
 const request=++auditRequest;state.auditTask=id;selectAuditTab(false);const t=state.tasks.find(t=>t.id===id);
 $('#audit-title').textContent=(t?t.spec.target.name+' · ':'')+'检查记录';$('#export-link').href='/api/tasks/'+encodeURIComponent(id)+'/export';$('#audit-body').innerHTML='<p class="muted">正在读取检查记录…</p>';if(!$('#audit-dialog').open)$('#audit-dialog').showModal();
 try{const data=await api('/api/tasks/'+encodeURIComponent(id)+'/audit-trail');if(request!==auditRequest)return;
 $('#audit-body').innerHTML=data.history.map((a,i)=>`<details class="audit-entry" ${i===0?'open':''}><summary><div class="audit-date"><span>${esc(P.formatDate(a.timestamp))}${a.data_mode==='replay'?' · 演示时钟':''}</span>${modeTag(a.data_mode)}</div><h3>${esc(P.summary(a.action_taken,a.pending_event_count))}</h3></summary>${(a.conditions_evaluated||[]).map(evidenceCard).join('')}${a.kind==='evaluation'?'<p class="evidence-source">'+(a.notification_sent?'已生成提醒':'未生成提醒')+' · 待提醒公告 '+(a.pending_event_count||0)+' 条</p>':''}<details class="technical"><summary>本次规则与原始记录</summary><p>规则版本 ${a.rule_version}；原始检查时间 ${esc(a.timestamp)}</p><pre>${esc(JSON.stringify(a,null,2))}</pre></details></details>`).join('')||'<p class="muted">还没有检查记录。</p>';
 }catch(e){if(request===auditRequest)$('#audit-body').textContent=e.message;}
}
async function showVersions(){
 const request=++auditRequest;selectAuditTab(true);$('#audit-body').innerHTML='<p class="muted">正在读取修改记录…</p>';
 try{const data=await api('/api/tasks/'+state.auditTask+'/versions');if(request!==auditRequest)return;const t=state.tasks.find(t=>t.id===state.auditTask),terminal=['ARCHIVED','EXPIRED'].includes(t?.state.status);
 $('#audit-body').innerHTML=data.versions.map(v=>`<article class="version-card"><h3>${v.version===t.spec.version?'当前规则':'历史规则'} · 第${v.version}版</h3><p class="muted">${esc(P.formatDate(v.at))} · ${esc(v.reason)}</p><p>${v.spec.conditions.map(c=>esc(P.describe(c))).join(v.spec.condition_logic==='AND'?'，且':'，或')}</p>${v.version!==t.spec.version&&!terminal?`<button class="secondary" data-action="rollback" data-id="${esc(t.id)}" data-version="${v.version}">恢复这组条件</button>`:''}</article>`).join('');
 }catch(e){if(request===auditRequest)$('#audit-body').textContent=e.message;}
}
function validateJsonDraft(d){
 if(!d||!Array.isArray(d.conditions)||d.conditions.length<1||d.conditions.length>6||!d.validity||!d.governance||!d.target)throw new Error('JSON缺少必要的公司、条件或时间设置。');
 if(!state.meta.symbols.some(t=>t.symbol===d.target.symbol&&t.name===d.target.name))throw new Error('JSON中的公司不在支持列表中。');
 if(state.editing&&(d.target.symbol!==state.editing.spec.target.symbol||d.data_mode!==state.editing.spec.data_mode))throw new Error('修改提醒时不能更换公司或数据模式，请另建提醒。');
 if(!['AND','OR'].includes(d.condition_logic)||!['live','replay'].includes(d.data_mode))throw new Error('请检查组合关系和数据模式。');
 P.dateInput(d.validity.start_time);P.dateInput(d.validity.end_time);
 for(const c of d.conditions){if(!['PRICE','PRICE_CHANGE_RATIO','HEAT','CALENDAR','ANNOUNCEMENT_EVENT'].includes(c.type))throw new Error('JSON包含不支持的条件类型。');if(c.type==='CALENDAR')P.dateInput(c.at);else if(c.type==='ANNOUNCEMENT_EVENT'){if(!P.eventLabels[c.event_category])throw new Error('请选择支持的公告类别。');}else P.fromDisplay(c,P.toDisplay(c));}
 return d;
}
function setFilter(filter){state.filter=filter;document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b.dataset.filter===filter);b.setAttribute('aria-pressed',String(b.dataset.filter===filter));});renderTasks();}
async function runAction(button){
 const action=button.dataset.action,id=button.dataset.id,task=state.tasks.find(t=>t.id===id);button.disabled=true;showError('#page-error','');
 try{
 if(action==='new')showCompose();else if(action==='demo-new')showCompose(true);
 else if(action==='clear-filter'){$('#task-search').value='';setFilter('all');}
 else if(action==='audit')await showAudits(id);
 else if(action==='edit'){state.editing=copy(task);state.draft=copy(task.spec);state.compilation=null;state.warnings=[];showRules();}
 else if(action==='archive'){state.archiveId=id;$('#archive-description').textContent=task.spec.target.name+'的这条提醒将停止运行。';showError('#archive-error','');$('#archive-dialog').showModal();}
 else if(action==='scenario'){
  const demo=state.tasks.find(t=>t.id===state.demoId);if(!demo||demo.spec.data_mode!=='replay'||demo.state.paused)throw new Error('请先创建或恢复演示提醒。');
  const t=await api('/api/simulate/inject','POST',{task_id:demo.id,scenario:button.dataset.scenario});await refresh();$('#scenario-result').textContent=P.summary(t.state.last_decision,Object.keys(t.state.pending_events||{}).length)+' 条件提醒共'+t.state.trigger_count+'条。';
 }else if(action==='rollback'){await api('/api/tasks/'+id+'/rollback','POST',{version:Number(button.dataset.version),expected_version:task.spec.version});await refresh();await showVersions();toast('这组条件已恢复，历史记录保留。');}
 else if(action==='pause'||action==='resume'){await api('/api/tasks/'+id+'/'+action,'POST');await refresh();toast(action==='pause'?'已暂停检查。':'已恢复监控。');}
 }catch(e){const target=$('#audit-dialog').open?'#audit-body':state.view==='demo'?'#scenario-result':'#page-error';if(target==='#audit-body')$('#audit-body').textContent=e.message;else if(target==='#scenario-result')$('#scenario-result').textContent=e.message;else showError(target,e.message);}
 finally{if(button.isConnected)button.disabled=false;}
}
document.addEventListener('click',event=>{
 const b=event.target.closest('button');if(!b)return;
 if(b.dataset.close){$('#'+b.dataset.close).close();return;}
 if(b.dataset.view)setView(b.dataset.view);
 if(b.dataset.filter)setFilter(b.dataset.filter);
 if(b.dataset.example){const name=selectedTarget()?.name||'贵州茅台';$('#prompt').value={golden:`未来两周帮我盯住${name}：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。`,price:`未来7天，${name}股价低于1500元提醒我。`,heat:`未来两周，${name}量比达到3时提醒我。`}[b.dataset.example];showError('#parse-error','');$('#prompt').focus();}
 if(b.dataset.action)runAction(b);
});
$('#compose-form').addEventListener('submit',parsePrompt);$('#rule-form').addEventListener('submit',saveRules);
$('#cancel-rule').addEventListener('click',()=>{$('#rule-dialog').close();if(!state.editing){$('#compose-dialog').showModal();$('#prompt').focus();}});
$('#rule-form').addEventListener('invalid',event=>{let parent=event.target.parentElement;while(parent&&parent!==event.currentTarget){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}},true);
$('#rule-body').addEventListener('input',()=>{showError('#rule-error','');updateRulePreview();});
$('#rule-body').addEventListener('change',updateRulePreview);
$('#rule-body').addEventListener('click',e=>{try{if(e.target.id==='refresh-json')$('#rule-json').value=JSON.stringify(collectRules(),null,2);else if(e.target.id==='apply-json'){const d=validateJsonDraft(JSON.parse($('#rule-json').value));state.draft=copy(d);showRules();}}catch(error){showError('#rule-error',error.message);}});
$('#prompt').addEventListener('input',()=>showError('#parse-error',''));$('#target').addEventListener('change',()=>showError('#parse-error',''));
$('#mode').addEventListener('change',updateModeHint);$('#use-ai').addEventListener('change',updateModeHint);
$('#task-search').addEventListener('input',renderTasks);$('#refresh-button').addEventListener('click',refresh);
$('#show-audits').addEventListener('click',()=>showAudits(state.auditTask));$('#show-versions').addEventListener('click',showVersions);
$('#demo-target').addEventListener('change',()=>{state.demoId=$('#demo-target').value;$('#scenario-result').textContent='';renderDemo();});
$('#close-toast').addEventListener('click',()=>$('#toast').hidden=true);
function syncNavigation(open){
 const mobile=window.matchMedia('(max-width: 780px)').matches,visible=mobile&&open;
 $('#sidebar').classList.toggle('open',visible);$('#sidebar').inert=mobile&&!visible;
 $('#main').inert=visible;$('#nav-backdrop').hidden=!visible;
 $('#mobile-menu').setAttribute('aria-expanded',String(visible));document.body.classList.toggle('nav-open',visible);
}
function closeNavigation(){syncNavigation(false);$('#mobile-menu').focus();}
$('#mobile-menu').addEventListener('click',()=>{syncNavigation(true);$('#close-nav').focus();});
$('#close-nav').addEventListener('click',closeNavigation);$('#nav-backdrop').addEventListener('click',closeNavigation);
window.matchMedia('(max-width: 780px)').addEventListener('change',()=>syncNavigation(false));
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#sidebar').classList.contains('open'))closeNavigation();});
syncNavigation(false);
$('#confirm-archive').addEventListener('click',async()=>{const b=$('#confirm-archive');b.disabled=true;try{await api('/api/tasks/'+state.archiveId,'DELETE');$('#archive-dialog').close();await refresh();toast('提醒已归档。');}catch(e){showError('#archive-error',e.message);}finally{b.disabled=false;}});
async function init(){try{state.meta=await api('/api/meta');$('#target').innerHTML='<option value="">从输入中识别</option>'+state.meta.symbols.map(s=>`<option value="${esc(s.symbol)}">${esc(s.name)} · ${s.symbol.slice(0,6)}</option>`).join('');$('#use-ai').checked=state.meta.ai_available;$('#use-ai').disabled=!state.meta.ai_available;$('#mode option[value="live"]').disabled=!state.meta.live_available;$('#new-alert').disabled=false;await refresh();setInterval(refresh,4000);}catch(e){showError('#page-error','服务暂时未连接，请刷新页面重试。');}}
init();
