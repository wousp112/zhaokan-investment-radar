'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy = value => JSON.parse(JSON.stringify(value));
const timeText = value => value ? new Date(value).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '尚无检查';
const dateText = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '尚无记录';
const state = {meta:null,tasks:[],alerts:[],draft:null,editing:null,compilation:null,warnings:[],auditTask:null,refreshing:false};
let toastTimer;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6500);}
async function api(path,method='GET',body){
  const options={method,credentials:'same-origin',headers:{}};
  if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
  const response=await fetch(path,options);
  let result;try{result=await response.json();}catch{throw new Error('服务暂时没有返回有效结果，请刷新重试。');}
  if(!response.ok)throw new Error(result.error || '请求失败，请稍后重试。');
  return result;
}
function setView(view){
  for(const name of ['dashboard','inbox','about'])$('#'+name+'-view').hidden=name!==view;
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  $('#page-title').textContent={dashboard:'我的任务',inbox:'提醒记录',about:'运行说明'}[view];
}
function modeTag(mode){return `<span class="data-tag ${mode==='live'?'live':''}">${mode==='live'?'真实数据':'模拟数据'}</span>`;}
function description(condition){
  const op={'<=':'≤','>=':'≥','<':'<','>':'>'}[condition.operator]||'';
  if(condition.type==='PRICE_CHANGE_RATIO')return `相对昨收涨跌幅 ${op} ${(condition.threshold*100).toFixed(2).replace(/\.00$/,'')}%`;
  if(condition.type==='PRICE')return `现价 ${op} ${condition.threshold} 元`;
  if(condition.type==='HEAT')return `量比 ${op} ${condition.threshold}`;
  if(condition.type==='CALENDAR')return `到达 ${dateText(condition.at)}`;
  return {PERFORMANCE_FORECAST:'出现新的业绩预告',PERFORMANCE_REPORT:'出现新的业绩快报',ANY_ANNOUNCEMENT:'出现新的公告'}[condition.event_category]||'公告条件';
}
const scenarios=[['normal','未达阈值'],['drop','跌至 -3.8%'],['deeper','再跌至 -4.5%'],['announcement','新业绩预告'],['same_announcement','重复公告'],['heat','量比升至 3.6'],['timeout','行情超时'],['http500','接口 500'],['stale','数据过期'],['conflict','指标冲突'],['event_failure','公告故障'],['recover','恢复来源'],['closed','休市'],['open','开市'],['advance','推进31分钟']];
function renderTasks(){
  const openLabs=new Set([...document.querySelectorAll('.fault-lab[open]')].map(e=>e.dataset.task));
  const visible=state.tasks;
  $('#nav-count').textContent=visible.length;$('#task-total').textContent=visible.length;$('#stat-total').textContent=visible.length;
  $('#stat-active').textContent=visible.filter(t=>['ACTIVE','COOLING','DEGRADED'].includes(t.state.status)).length;
  $('#stat-alerts').textContent=visible.reduce((sum,t)=>sum+t.state.trigger_count,0);
  const last=visible.map(t=>t.state.last_check_time).filter(Boolean).sort().at(-1);$('#stat-check').textContent=timeText(last);
  if(!visible.length){$('#task-list').innerHTML='<div class="empty"><div class="empty-icon">◎</div><h3>你的第一条监控，从一句关注点开始</h3><p>点击上方示例，生成并确认规则后，这里会出现持续运行的任务。</p></div>';return;}
  $('#task-list').innerHTML=visible.map(t=>{
    const s=t.state, terminal=['ARCHIVED','EXPIRED'].includes(s.status);
    const rules=t.spec.conditions.map(c=>esc(description(c))).join(`<span class="rule-logic">${t.spec.condition_logic==='OR'?'或':'且'}</span><br>`);
    const countdown=s.cooldown_until?Math.max(0,Math.ceil((new Date(s.cooldown_until)-new Date(s.last_check_time||Date.now()))/60000)):0;
    return `<article class="task-card" data-task="${esc(t.id)}"><div class="task-main"><div><div class="task-name"><h3>${esc(t.spec.target.name)}</h3>${modeTag(t.spec.data_mode)}</div><div class="ticker">${esc(t.spec.target.symbol)} · v${t.spec.version}</div></div><div class="rules-summary">${rules}</div><div class="task-state"><span class="status ${esc(s.status)}"><span>●</span>${esc(state.meta.states[s.status])}</span><small>${countdown&&!terminal?`冷却约 ${countdown} 分钟 · 继续检查`:`每 ${t.spec.governance.frequency_seconds} 秒检查`}</small></div></div><div class="task-bottom"><div class="last-decision">${s.last_check_time?`<span>最近检查 ${esc(timeText(s.last_check_time))} · ${s.check_count} 次</span><br>`:''}${esc(s.last_decision||(s.status==='PENDING'?'规则待确认，尚未运行。':'等待首次检查。'))}</div><div class="task-actions"><button class="text-button" data-action="audit" data-id="${t.id}">查看依据 ↗</button>${!terminal?`<button class="text-button" data-action="edit" data-id="${t.id}">改规则</button><button class="text-button" data-action="${s.paused||s.status==='PENDING'?'resume':'pause'}" data-id="${t.id}">${s.paused||s.status==='PENDING'?'恢复':'暂停'}</button><button class="text-button" data-action="archive" data-id="${t.id}">归档</button>`:''}</div></div>${t.spec.data_mode==='replay'&&!terminal?`<details class="fault-lab" data-task="${t.id}" ${openLabs.has(t.id)?'open':''}><summary>情景验证台<span>仅影响当前演示任务，所有操作会留下记录</span></summary><div class="scenarios">${scenarios.map(([key,label])=>`<button data-action="scenario" data-id="${t.id}" data-scenario="${key}" class="${['timeout','stale','conflict','http500','event_failure'].includes(key)?'warn':''}">${label}</button>`).join('')}</div><div class="time-note">按演示时钟推进。行情基准为模拟昨收100元，不对应真实股价。</div></details>`:''}</article>`;
  }).join('');
}
function renderAlerts(){
  $('#inbox-count').textContent=state.alerts.length;
  $('#alert-list').innerHTML=state.alerts.length?state.alerts.map(a=>`<article class="panel alert-card ${esc(a.kind)}"><div class="alert-head"><h3>${esc(a.title)} ${modeTag(a.mode)}</h3><small>${esc(dateText(a.timestamp))}</small></div><p>${esc(a.message)}</p><button class="text-button" data-action="audit" data-id="${esc(a.task_id)}">查看对应检查记录 ↗</button><p class="disclaimer">${esc(a.disclaimer)}</p></article>`).join(''):'<div class="empty"><h3>目前没有提醒</h3><p>规则满足或监控异常后，记录会显示在这里。</p></div>';
}
async function refresh(){
  if(state.refreshing)return;state.refreshing=true;
  try{
    const [tasks,alerts,health]=await Promise.all([api('/api/tasks'),api('/api/alerts'),api('/api/health')]);
    state.tasks=tasks.tasks;state.alerts=alerts.alerts;renderTasks();renderAlerts();
    $('#service-state').textContent=health.scheduler_enabled?(health.status==='ok'?'后台检查已启用':'后台检查需要留意'):'后台自动检查未启用';
    $('#service-dot').style.background=health.status==='ok'?'var(--green)':'var(--amber)';
    $('#heartbeat').textContent=health.heartbeat?'调度心跳 '+timeText(health.heartbeat):'尚无调度心跳';
  }catch(error){$('#service-state').textContent='服务连接中断';$('#service-dot').style.background='var(--red)';$('#heartbeat').textContent='无法获取最新状态';}
  finally{state.refreshing=false;}
}
function conditionEditor(c,index){
  let fields='';
  if(['PRICE_CHANGE_RATIO','PRICE','HEAT'].includes(c.type)){
    fields=`<span>${{PRICE_CHANGE_RATIO:'相对昨收涨跌幅',PRICE:'现价',HEAT:'量比'}[c.type]}</span><select data-condition="${index}" data-field="operator" aria-label="比较关系">${['<=','<','>=','>'].map(op=>`<option value="${esc(op)}" ${op===c.operator?'selected':''}>${esc(op)}</option>`).join('')}</select><input data-condition="${index}" data-field="threshold" type="number" step="any" aria-label="条件阈值" value="${c.type==='PRICE_CHANGE_RATIO'?+(c.threshold*100).toFixed(6):c.threshold}"><span>${c.type==='PRICE_CHANGE_RATIO'?'%':c.type==='PRICE'?'元':''}</span>`;
  }else fields=`<span>${esc(description(c))}</span>`;
  return `<div class="review-condition"><div class="review-label">条件 ${index+1}</div><div class="condition-edit">${fields}</div></div>`;
}
function showRules(){
  const d=state.draft;const days=Math.round((new Date(d.validity.end_time)-new Date(d.validity.start_time))/86400000);
  $('#rule-title').textContent=state.editing?`修改规则 · 当前 v${state.editing.spec.version}`:'核对监控规则';
  $('#activate-button').textContent=state.editing?'保存为新版本':'确认并开始监控';
  $('#rule-body').innerHTML=`<div class="review-target">${esc(d.target.name)} <small>${esc(d.target.symbol)}</small>${modeTag(d.data_mode)}</div>${d.conditions.map(conditionEditor).join('')}<div class="review-grid"><div><label for="rule-logic">条件组合</label><select id="rule-logic"><option value="OR" ${d.condition_logic==='OR'?'selected':''}>满足任一条件（或）</option><option value="AND" ${d.condition_logic==='AND'?'selected':''}>全部同时满足（且）</option></select></div><div><label for="rule-days">监控总时长（天）</label><input id="rule-days" type="number" min="1" max="366" value="${days}"></div><div><label for="rule-cooldown">提醒冷却（分钟）</label><input id="rule-cooldown" type="number" min="0" max="1440" value="${d.governance.cooldown_minutes}"></div><div><label for="rule-frequency">检查间隔（秒）</label><input id="rule-frequency" type="number" min="10" max="3600" value="${d.governance.frequency_seconds}"></div><div><label for="rule-hours">价格检查时间</label><select id="rule-hours"><option value="true" ${d.governance.trading_hours_only?'selected':''}>仅交易时段</option><option value="false" ${!d.governance.trading_hours_only?'selected':''}>不限时段（仍校验数据时效）</option></select></div></div><div class="review-warnings">${state.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}<p>价格按规则版本和交易日去重，公告按事件指纹去重。</p></div>${state.compilation?`<p class="compiler-info">本次解析：${state.compilation.engine==='deepseek'?esc(state.compilation.model):'本地规则解析'} · ${state.compilation.latency_ms} ms · 结构校验通过${state.compilation.fallback_reason?' · 模型调用失败后已回退':''}</p>`:''}<details class="advanced"><summary>查看或编辑完整规则 JSON</summary><textarea id="rule-json" aria-label="完整规则 JSON">${esc(JSON.stringify(d,null,2))}</textarea><button type="button" id="apply-json" class="secondary">采用 JSON 中的规则</button><p>支持价格、公告、日历和量比条件；保存时由服务器重新校验。</p></details>`;
  if(!$('#rule-dialog').open)$('#rule-dialog').showModal();
}
function collectRules(){
  const d=copy(state.draft);
  document.querySelectorAll('[data-condition]').forEach(input=>{
    const c=d.conditions[+input.dataset.condition];
    c[input.dataset.field]=input.dataset.field==='threshold'?+input.value/(c.type==='PRICE_CHANGE_RATIO'?100:1):input.value;
  });
  d.condition_logic=$('#rule-logic').value;d.governance.cooldown_minutes=+$('#rule-cooldown').value;
  d.governance.frequency_seconds=+$('#rule-frequency').value;d.governance.trading_hours_only=$('#rule-hours').value==='true';
  d.validity.end_time=new Date(new Date(d.validity.start_time).getTime()+Number($('#rule-days').value)*86400000).toISOString();
  return d;
}
async function parsePrompt(){
  const button=$('#parse-button');button.disabled=true;button.textContent='正在理解关注点…';
  try{
    const target=state.meta.symbols.find(t=>t.symbol===$('#target').value);
    const result=await api('/api/tasks/parse','POST',{prompt:$('#prompt').value,target,data_mode:$('#mode').value,use_ai:$('#use-ai').checked});
    state.draft=result.task_spec;state.compilation=result.compilation;state.warnings=result.warnings;state.editing=null;showRules();
  }catch(error){toast(error.message);}
  finally{button.disabled=false;button.innerHTML='生成规则 <span>↗</span>';}
}
async function saveRules(){
  const button=$('#activate-button');button.disabled=true;
  try{
    const spec=collectRules();let task;
    if(state.editing)task=await api('/api/tasks/'+state.editing.id,'PUT',{task_spec:spec,expected_version:state.editing.spec.version});
    else task=await api('/api/tasks/create','POST',{task_spec:spec,activate:true,compilation_id:state.compilation?.compilation_id||null});
    $('#rule-dialog').close();toast(state.editing?'规则已保存为新版本。':'监控已建立，正在执行首次检查。');
    await api('/api/simulate/tick','POST',{task_id:task.id});await refresh();
  }catch(error){toast(error.message);}finally{button.disabled=false;}
}
function evidenceCard(c){
  const truth=c.satisfied===true?'true':c.satisfied===false?'false':'unknown';
  let metric='';
  if(typeof c.actual_value==='number'&&c.type!=='ANNOUNCEMENT_EVENT')metric=c.type==='PRICE_CHANGE_RATIO'?(c.actual_value*100).toFixed(2)+'%':String(c.actual_value);
  return `<div class="evidence-card"><div class="evidence-heading"><span>${esc(c.display_text)}</span><span class="truth ${truth}">${{true:'已满足',false:'未满足',unknown:c.suspended?'休市静默':'无法判断'}[truth]}</span></div>${metric?`<strong class="evidence-metric">${esc(metric)}</strong>`:''}<p>${esc(c.reason)}</p>${c.formula?`<p>现价 ${esc(c.last)} / 昨收 ${esc(c.previous_close)} − 1</p>`:''}${(c.events||[]).map(e=>`<p>${esc(e.title)} · ${esc(e.published_at)}${e.freshness_note?'<br>'+esc(e.freshness_note):''}</p>`).join('')}<p class="evidence-source">来源：${esc(c.source||'系统')} · 数据时间 ${esc(dateText(c.observed_at))}${c.request_id?` · 请求 ${esc(c.request_id)}`:''}</p>${c.coverage?`<p class="evidence-source">${esc(c.coverage)}</p>`:''}</div>`;
}
async function showAudits(taskId){
  state.auditTask=taskId;$('#show-audits').classList.add('active');$('#show-versions').classList.remove('active');
  const task=state.tasks.find(t=>t.id===taskId);$('#audit-title').textContent=(task?task.spec.target.name+' · ':'')+'检查记录';
  $('#export-link').href='/api/tasks/'+taskId+'/export';$('#audit-body').innerHTML='<p class="muted">正在读取检查记录…</p>';
  if(!$('#audit-dialog').open)$('#audit-dialog').showModal();
  try{
    const data=await api('/api/tasks/'+taskId+'/audit-trail');
    $('#audit-body').innerHTML=data.history.map(a=>`<article class="audit-entry"><div class="audit-date"><span>${esc(dateText(a.timestamp))} · v${a.rule_version}</span>${modeTag(a.data_mode)}</div><h3>${esc(a.action_taken)}</h3>${a.conditions_evaluated.map(evidenceCard).join('')}${a.kind==='evaluation'?`<p class="evidence-source">组合：${a.condition_logic} · ${a.notification_sent?'已生成提醒':'未生成提醒'} · 待提醒公告 ${a.pending_event_count||0} 条 · 规则校验摘要 ${esc(a.spec_hash)}</p>`:''}</article>`).join('')||'<p class="muted">尚无检查记录。</p>';
  }catch(error){$('#audit-body').textContent=error.message;}
}
async function showVersions(){
  $('#show-versions').classList.add('active');$('#show-audits').classList.remove('active');
  try{
    const data=await api('/api/tasks/'+state.auditTask+'/versions');const task=state.tasks.find(t=>t.id===state.auditTask);
    $('#audit-body').innerHTML=data.versions.map(v=>`<article class="version-card"><h3>v${v.version}${v.version===task.spec.version?' · 当前版本':''}</h3><p>${esc(dateText(v.at))} · ${esc(v.reason)}</p><p>${v.spec.conditions.map(c=>esc(description(c))).join(' '+v.spec.condition_logic+' ')}</p>${v.version!==task.spec.version?`<button class="secondary" data-action="rollback" data-id="${task.id}" data-version="${v.version}">恢复这组规则为新版本</button>`:''}</article>`).join('');
  }catch(error){toast(error.message);}
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.view)setView(button.dataset.view);
  if(button.dataset.example){
    const name=state.meta.symbols.find(t=>t.symbol===$('#target').value)?.name||'贵州茅台';
    $('#prompt').value={golden:`未来两周帮我盯住${name}：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。`,price:`未来7天帮我监控${name}，股价低于95元提醒我。`,heat:`未来两周帮我监控${name}，量比达到3时提醒我。`}[button.dataset.example];$('#prompt').focus();
  }
  const action=button.dataset.action;if(!action)return;
  const id=button.dataset.id;const task=state.tasks.find(t=>t.id===id);button.disabled=true;
  try{
    if(action==='audit')await showAudits(id);
    else if(action==='edit'){state.draft=copy(task.spec);state.editing=copy(task);state.compilation=null;state.warnings=['新版本保留历史记录。公告去重与已有冷却仍然生效。'];showRules();}
    else if(action==='scenario'){await api('/api/simulate/inject','POST',{task_id:id,scenario:button.dataset.scenario});await refresh();toast('情景已执行，可查看本轮判断依据。');}
    else if(action==='rollback'){await api('/api/tasks/'+id+'/rollback','POST',{version:+button.dataset.version,expected_version:task.spec.version});await refresh();await showVersions();toast('已恢复为新的规则版本。');}
    else if(action==='archive'){if(confirm('归档后将停止此任务，历史检查记录会保留。确认归档？')){await api('/api/tasks/'+id,'DELETE');await refresh();}}
    else{await api('/api/tasks/'+id+'/'+action,'POST');await refresh();}
  }catch(error){toast(error.message);}finally{button.disabled=false;}
});
$('#parse-button').addEventListener('click',parsePrompt);$('#activate-button').addEventListener('click',saveRules);
$('#cancel-rule').addEventListener('click',()=>$('#rule-dialog').close());$('#refresh-button').addEventListener('click',refresh);
$('#show-audits').addEventListener('click',()=>showAudits(state.auditTask));$('#show-versions').addEventListener('click',showVersions);
$('#rule-body').addEventListener('click',event=>{if(event.target.id==='apply-json'){try{state.draft=JSON.parse($('#rule-json').value);showRules();toast('已采用 JSON 草稿，保存时将校验字段。');}catch{toast('JSON 格式或规则结构不正确，请核对。');}}});
$('#mode').addEventListener('change',()=>{$('#mode-notice').textContent=$('#mode').value==='replay'?'演示情景使用模拟行情，可验证触发、冷却与故障恢复。页面不会展示为真实行情。':'真实数据依赖服务可用性。公告检索覆盖有限；价格异常会暂停该条件判断，不会切换为模拟行情。';});
async function init(){try{state.meta=await api('/api/meta');$('#target').innerHTML=state.meta.symbols.map(t=>`<option value="${t.symbol}">${esc(t.name)} · ${t.symbol.slice(0,6)}</option>`).join('');$('#use-ai').checked=state.meta.ai_available;$('#use-ai').disabled=!state.meta.ai_available;$('#mode option[value="live"]').disabled=!state.meta.live_available;await refresh();setInterval(refresh,4000);}catch(error){toast(error.message);}}
init();
