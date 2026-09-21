'use strict';
const $=selector=>document.querySelector(selector);
const P=window.RadarPresentation;
const O=window.RadarOnboarding;
const welcomePreferences=O.preferences([()=>window.localStorage,()=>window.sessionStorage]);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy=value=>JSON.parse(JSON.stringify(value));
const icon=name=>`<img src="/static/icons/${name}.svg" alt="">`;
const state={meta:null,tasks:[],alerts:[],filter:'all',view:'dashboard',draft:null,editing:null,compilation:null,warnings:[],auditTask:null,auditTab:'checks',demoId:null,archiveId:null,refreshing:null,walkthrough:null};
let toastTimer,auditRequest=0,composeRequest=0,alertRequest=0,reportRequest=0;
Object.assign(state,{alertUnread:0,alertTotal:0,alertCursor:null,alertHasMore:false,alertOlder:false,unreadOnly:false,workspace:null,manualDraft:false,saveRequest:null});
function toast(message){$('#toast-text').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4000);}
function showError(selector,message){const box=$(selector);box.textContent=message;box.hidden=!message;if(message&&box.hasAttribute('tabindex'))box.focus();}
function showWelcome(){
 if(document.querySelector('dialog[open]'))return;
 $('#welcome-start').disabled=!state.meta;$('#welcome-service-note').hidden=!!state.meta;
 syncNavigation(false);$('#welcome-dialog').showModal();
}
function dismissWelcome(){welcomePreferences.remember('dismissed');$('#welcome-dialog').close();$('#new-alert').focus();}
function startTutorial(){
 if(!state.meta)return;
 welcomePreferences.remember('started');$('#welcome-dialog').close();
 state.walkthrough={step:'compose',taskId:null,busy:false};
 showError('#walkthrough-error','');showCompose(true);renderTutorial();
}
function stopTutorial(){
 state.walkthrough=null;$('#walkthrough').hidden=true;$('#compose-tutorial-note').hidden=true;
 $('#demo-view').classList.remove('guided-example');
 showError('#walkthrough-error','');
}
function renderTutorial(){
 const tour=state.walkthrough,visible=tour&&['drop','inbox','done'].includes(tour.step);
 $('#demo-view').classList.toggle('guided-example',!!visible);
 $('#walkthrough').hidden=!visible;if(!visible)return;
 const task=state.tasks.find(t=>t.id===tour.taskId);
 const blocked=!task||task.spec.data_mode!=='replay'||task.state.paused||['ARCHIVED','EXPIRED','PENDING'].includes(task.state.status);
 const copy={
  drop:['接下来：试着触发提醒','模拟一次下跌，看看会不会提醒','示例把昨收价设为100元。点击下方按钮，让模拟价格降到96.2元，下跌3.8%，达到刚才设定的3%。','模拟下跌3.8%'],
  inbox:['最后一步：找到提醒','示例提醒已生成','这条通知已保存在网站里。点击“查看这条提醒”，确认你能找到它。手机不会另外收到推送。','查看这条提醒'],
  done:['教程完成','你已经收到第一条模拟提醒','结果保存在“提醒记录”。点击通知旁的“查看这条提醒”，可以查看当时的价格和判断原因。这条示例会保留为模拟提醒。','创建自己的提醒']
 }[tour.step];
 $('#walkthrough-step').textContent=copy[0];$('#walkthrough-title').textContent=copy[1];$('#walkthrough-copy').textContent=copy[2];
 $('#walkthrough-next').textContent=tour.busy?'正在检查模拟价格…':copy[3];
 $('#walkthrough-next').disabled=tour.busy||(tour.step==='drop'&&blocked);
 if(tour.step==='drop'&&blocked)$('#walkthrough-copy').textContent='这条示例已暂停或结束。可以结束教程，再从“使用教程”重新试一次。';
}
async function tutorialNext(){
 const tour=state.walkthrough;if(!tour||tour.busy)return;
 if(tour.step==='inbox'){setView('inbox');$('#walkthrough-title').focus();return;}
 if(tour.step==='done'){stopTutorial();$('#prompt').value='';$('#target').value='';setView('dashboard');showCompose();return;}
 if(tour.step!=='drop')return;
 const task=state.tasks.find(t=>t.id===tour.taskId);
 if(!task||!O.isExample(task.spec)||task.state.paused||['ARCHIVED','EXPIRED','PENDING'].includes(task.state.status)){
  showError('#walkthrough-error','示例条件已改变或停止检查，请结束教程后重新试一次。');return;
 }
 tour.busy=true;showError('#walkthrough-error','');renderTutorial();
 try{
  await api('/api/simulate/inject','POST',{task_id:tour.taskId,scenario:'drop'});
  await refresh();if(state.walkthrough!==tour)return;
  if(!O.exampleAlert(state.alerts,tour.taskId))throw new Error('还没有读到这条提醒，请稍后再试。可以在“查看记录”中检查原因。');
  tour.step='inbox';
 }catch(error){if(state.walkthrough===tour)showError('#walkthrough-error',error.message);}
 finally{tour.busy=false;renderTutorial();}
}
function closeAuthoring(id){
 if(id==='compose-dialog')composeRequest++;
 if(state.walkthrough)stopTutorial();
 $('#'+id).close();$('#new-alert').focus();
}
async function api(path,method='GET',body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),50000);
 try{const options={method,credentials:'same-origin',headers:{},signal:controller.signal};if(body!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}const r=await fetch(path,options);let data;try{data=await r.json();}catch{throw new Error('服务暂时没有返回有效结果，请稍后重试。');}if(!r.ok)throw new Error(data.error||'请求未完成，请稍后重试。');return data;}
 catch(e){if(e.name==='AbortError')throw new Error('服务响应较慢。输入内容已保留，请稍后重试。');if(e instanceof TypeError)throw new Error('暂时连不上服务。请检查网络后重试，输入内容已保留。');throw e;}finally{clearTimeout(timer);}
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
 const title={dashboard:'我的提醒',inbox:'提醒记录',demo:'演示体验',about:'使用帮助'}[view];$('#page-title').textContent=title;document.title=(state.alertUnread?'('+state.alertUnread+') ':'')+title+' · 照看';
 syncNavigation(false);if(view==='demo')renderDemo();
 if(view==='inbox'&&state.walkthrough?.step==='inbox'&&O.exampleAlert(state.alerts,state.walkthrough.taskId)){
  state.walkthrough.step='done';welcomePreferences.remember('completed');
 }
 renderTutorial();
}
function modeTag(mode){return `<span class="mode-tag ${mode==='live'?'live':'replay'}">${mode==='live'?'真实数据':'模拟数据'}</span>`;}
function taskCard(task){
 const s=task.state,terminal=['EXPIRED','ARCHIVED'].includes(s.status),rules=task.spec.conditions.map((c,i)=>`${i?'<span class="rule-logic">'+(task.spec.condition_logic==='AND'?'且':'或')+'</span>':''}${esc(P.describe(c))}`).join('<br>');
 let result=s.last_decision?'上次检查：'+P.summary(s.last_decision,Object.keys(s.pending_events||{}).length):'等待首次检查。';
 if(s.paused)result='检查已暂停，已有记录保留。';else if(terminal)result=P.schedule(task);else if(s.status==='SUSPENDED')result='非交易时段，等待下次检查。';
 const q=s.last_snapshot?.quote;
 const quote=q?(q.status==='ok'&&q.last!=null?`上次检查 <strong>${esc(P.number(q.last))}元</strong>${typeof q.change==='number'?' · '+esc(P.number(P.percent(q.change)))+'%':''}`:'行情暂不可用'):'';
 const late=state.workspace?.overdue?.find(x=>x.task_id===task.id);
 if(late)result='检查比计划晚了'+Math.ceil(late.delay_seconds/60)+'分钟。请查看服务状态，当前数值可能尚未更新。';
 return `<article class="task-card" data-task="${esc(task.id)}"><div class="task-main"><div><div class="task-name"><h3>${esc(task.spec.target.name)}</h3>${modeTag(task.spec.data_mode)}</div><div class="ticker">${esc(task.spec.target.symbol)}</div></div><div class="rules-summary">${rules}</div><div class="task-state"><span class="status ${late?'DEGRADED':esc(s.status)}">${late?'检查延迟':esc(P.statusLabel(task))}</span><small>${esc(P.schedule(task))}</small></div><div class="task-actions"><button class="text-button record-button" data-action="audit" data-id="${esc(task.id)}">查看记录</button>${!terminal?`<button class="text-button" data-action="edit" data-id="${esc(task.id)}">修改</button><button class="text-button" data-action="${s.paused||s.status==='PENDING'?'resume':'pause'}" data-id="${esc(task.id)}">${s.paused||s.status==='PENDING'?'恢复':'暂停'}</button><button class="text-button" data-action="archive" data-id="${esc(task.id)}">归档</button>`:`<button class="text-button" data-action="duplicate" data-id="${esc(task.id)}">复制为新提醒</button>`}</div></div><div class="task-bottom"><span class="last-decision">${esc(result)}</span>${quote?'<span class="snapshot-quote">'+quote+'</span>':''}<span class="last-check">${s.last_check_time?'检查于 '+esc(P.formatDate(s.last_check_time)):'等待首次检查'}${task.spec.data_mode==='replay'?' · 演示时钟':''}</span>${!terminal&&!s.paused?`<button class="text-button" data-action="check" data-id="${esc(task.id)}">立即检查</button>`:''}</div></article>`;
}
function renderTasks(){
 $('#nav-count').textContent=state.tasks.length;$('#task-total').textContent=state.tasks.length;
 const visible=state.tasks.filter(t=>P.visibleTask(t,state.filter,$('#task-search').value.trim())||(state.filter==='attention'&&state.workspace?.overdue.some(x=>x.task_id===t.id)&&P.visibleTask(t,'all',$('#task-search').value.trim())));
 const html=visible.length?visible.map(taskCard).join(''):`<div class="empty">${icon('bell')}<h2>${state.tasks.length?'没有符合筛选的提醒':'还没有提醒'}</h2><p>${state.tasks.length?'换个公司名称或查看全部提醒。':'设置股价或公告条件，发生变化时回来查看提醒。'}</p>${state.tasks.length?'<button class="secondary" data-action="clear-filter">查看全部</button>':'<button class="primary" data-action="new">新建提醒</button><button class="text-button" data-view="demo">先试一次演示</button>'}</div>`;
 replaceHtml('#task-list',html);$('#list-summary').textContent=`显示 ${visible.length} 条，共 ${state.tasks.length} 条`;
 if(state.view==='demo')renderDemo();
}
function renderAlerts(){
 $('#inbox-count').textContent=state.alertUnread;
 $('#inbox-count').setAttribute('aria-label',state.alertUnread+'条未读提醒');
 document.title=(state.alertUnread?'('+state.alertUnread+') ':'')+$('#page-title').textContent+' · 照看';
 $('#inbox-summary').textContent=state.alertUnread+'条未读，共'+state.alertTotal+'条；当前显示'+state.alerts.length+'条。';
 $('#older-alerts').hidden=!state.alertHasMore;
 replaceHtml('#alert-list',state.alerts.length?state.alerts.map(a=>{
 const name=state.tasks.find(t=>t.id===a.task_id)?.spec.target.name||a.title.split(' · ')[0];
 const message=a.kind==='condition'&&a.evidence?a.evidence.filter(c=>c.satisfied).map(e=>esc(e.type==='ANNOUNCEMENT_EVENT'?e.display_text:P.describe(e))).join('；'):esc(a.message);
 return `<article class="alert-card ${esc(a.kind)} ${a.read_at?'':'unread'}"><span class="alert-type">${{condition:'条件满足',health:'数据异常',recovery:'已恢复'}[a.kind]||'任务通知'}${a.read_at?'':' · 未读'}</span><div><h3>${esc(name)} ${modeTag(a.mode)}</h3><p>${message}</p><small>${esc(P.formatDate(a.timestamp))}${a.mode==='replay'?' · 演示时钟':''}${a.rule_version?' · 第'+a.rule_version+'版条件':''}</small>${a.feedback?'<p class="field-hint">你的反馈：'+{useful:'有用',noisy:'打扰太多',incorrect:'判断有误'}[a.feedback]+'</p>':''}</div><button class="text-button" data-action="alert-open" data-id="${a.id}">查看这条提醒</button></article>`;
 }).join(''):'<div class="empty">'+icon('inbox')+'<h2>还没有提醒记录</h2><p>条件满足或数据状态变化后，通知会显示在这里。</p></div>');
}
async function refresh(){
 if(state.refreshing)return state.refreshing;
 state.refreshing=(async()=>{try{const [tasks,alerts,health,workspace]=await Promise.all([api('/api/tasks'),api('/api/alerts?limit=50&unread_only='+state.unreadOnly),api('/api/health'),api('/api/workspace-status')]);state.tasks=tasks.tasks;state.workspace=workspace;
 const oldest=alerts.alerts.at(-1)?.id;state.alerts=alerts.alerts.concat(state.alertOlder?state.alerts.filter(a=>oldest&&a.id<oldest&&(!state.unreadOnly||!a.read_at)):[]);
 state.alertUnread=alerts.unread;state.alertTotal=alerts.total;if(!state.alertOlder){state.alertCursor=alerts.next_cursor;state.alertHasMore=alerts.has_more;}
 renderTasks();renderAlerts();$('#capacity-note').textContent=workspace.active+'/'+workspace.active_limit+'条未结束；归档可释放额度。';
 showError('#connection-error','');$('#service-state').textContent=health.scheduler_enabled?(health.status==='ok'?'服务已连接':'检查服务需要留意'):'自动检查未开启';$('#service-dot').style.background=health.status==='ok'?'var(--green)':'var(--amber)';$('#health-detail').textContent='服务启动：'+P.formatDate(health.started_at)+'；最近调度：'+P.formatDate(health.heartbeat)+'；版本 '+health.build.version+' / '+health.build.source_sha256.slice(0,12);
 $('#operating-warning').hidden=health.scheduler_enabled&&health.status==='ok'&&!workspace.overdue.length;
 $('#operating-warning').textContent=!health.scheduler_enabled?'自动检查未开启。你仍可点击“立即检查”，页面不会把手动结果说成持续监控。':health.status!=='ok'?'检查服务暂时没有正常更新。已有记录保留，请稍后刷新；当前显示的数值可能已过时。':workspace.overdue.length+'条提醒的检查出现延迟。请在下方查看受影响的公司。';
 }catch(error){$('#service-state').textContent='连接中断';$('#service-dot').style.background='var(--red)';showError('#connection-error','暂时无法更新状态，页面保留上次结果。请稍后刷新。');}})();
 try{await state.refreshing;}finally{state.refreshing=null;renderTutorial();}
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
 composeRequest++;$('#parse-button').disabled=false;$('#parse-button').textContent='下一步：核对提醒';
 if(demo){$('#mode').value='replay';$('#use-ai').checked=false;$('#target').value='';$('#prompt').value='未来两周帮我盯住贵州茅台：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。';}
 state.editing=null;state.manualDraft=false;showError('#parse-error','');updateModeHint();
 $('#compose-tutorial-note').hidden=!state.walkthrough;
 $('#compose-dialog').showModal();$('#prompt').focus();
}
function updateModeHint(){
 $('#mode-notice').textContent=$('#mode').value==='replay'?'使用模拟价格和公告。创建后可以手动改变价格，马上看看提醒效果；这些数值不代表真实行情。':'检查真实股价和公告。数据暂时取不到时，会告诉你哪些条件无法判断。量比目前只支持模拟试用。';
 $('#ai-disclosure').textContent=state.meta?.ai_available?'开启后，上方这段文字会发送给 DeepSeek AI，帮助整理成提醒条件。无需你另外注册或设置。关闭后，仍可按示例填写。':'AI 功能暂未开放。按示例写明公司和数字，仍然可以创建提醒。';
 $('#ai-status').hidden=!$('#use-ai').checked;
}
function selectedTarget(){return state.meta.symbols.find(x=>x.symbol===$('#target').value)||null;}
async function parsePrompt(event){
 event.preventDefault();if(!$('#compose-form').reportValidity())return;
 const b=$('#parse-button'),request=++composeRequest;b.disabled=true;b.textContent='正在整理提醒内容…';showError('#parse-error','');
 try{const target=selectedTarget(),prompt=$('#prompt').value;
 const found=state.meta.symbols.filter(s=>prompt.includes(s.name)||prompt.includes(s.symbol.slice(0,6)));
 if(target&&found.some(s=>s.symbol!==target.symbol))throw new Error('你写了'+found.map(s=>s.name).join('、')+'，但下方选了'+target.name+'。请把“选择公司”改为“使用文字中的公司”，或修改文字。');
 const result=await api('/api/tasks/parse','POST',{prompt,target,data_mode:$('#mode').value,use_ai:$('#use-ai').checked});
 if(request!==composeRequest)return;
 if(target&&result.task_spec.target.symbol!==target.symbol)throw new Error('文字中的'+result.task_spec.target.name+'与所选的'+target.name+'不同，请修改公司后再继续。');
 state.draft=result.task_spec;state.compilation=result.compilation;state.warnings=result.warnings;state.editing=null;$('#compose-dialog').close();showRules();
 }catch(e){if(request===composeRequest)showError('#parse-error',e.message);}finally{if(request===composeRequest){b.disabled=false;b.textContent='下一步：核对提醒';}}
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
 return `<div class="review-condition" data-condition="${index}"><div class="review-label">条件 ${index+1}${c.type==='CALENDAR'?' · 北京时间':''}<button class="text-button remove-condition" type="button" data-remove-condition="${index}" aria-label="删除条件${index+1}" ${state.draft.conditions.length===1?'disabled':''}>删除</button></div><div class="condition-edit">${fields}</div><p class="boundary-note" data-boundary="${index}"></p></div>`;
}
function showRules(){
 const d=state.draft;if(!d)return;
 const editing=!!state.editing;
 $('#rule-title').textContent=editing?'修改提醒':state.manualDraft?'选择提醒条件':'核对提醒内容';$('#activate-button').textContent=editing?'保存修改':'确认并开启提醒';$('#cancel-rule').textContent=editing?'放弃本次修改':state.manualDraft?'暂不创建':'返回修改文字';
 $('#rule-body').innerHTML=`
 ${editing?'':(state.manualDraft?'':'<p class="step-label">第2步，共2步</p>')+'<p class="context-tip">还未开始检查。核对公司、条件和结束时间，确认后再开启。</p>'}
 <div class="form-row review-target"><label for="rule-target">关注公司</label><select id="rule-target" ${editing?'disabled':''}>${state.meta.symbols.map(t=>`<option value="${t.symbol}" ${t.symbol===d.target.symbol?'selected':''}>${esc(t.name)} · ${t.symbol.slice(0,6)}</option>`).join('')}</select></div>
 <div class="form-row"><span class="row-label">使用的数据</span><span>${modeTag(d.data_mode)}</span></div>
 <div class="review-conditions">${d.conditions.map(conditionEditor).join('')}</div>
 <div class="condition-add"><label for="new-condition-type">添加条件</label><select id="new-condition-type"><option value="PRICE_CHANGE_RATIO">涨跌幅</option><option value="PRICE">股价</option><option value="ANNOUNCEMENT_EVENT">公司公告</option><option value="CALENDAR">指定时间</option><option value="HEAT" ${d.data_mode==='live'?'disabled':''}>量比（模拟）</option></select><button class="secondary" id="add-condition" type="button" ${d.conditions.length>=6?'disabled':''}>添加</button></div>
 <div class="form-row"><label for="rule-logic">什么时候提醒</label><select id="rule-logic"><option value="OR" ${d.condition_logic==='OR'?'selected':''}>满足任意一条</option><option value="AND" ${d.condition_logic==='AND'?'selected':''}>全部条件满足</option></select></div>
 <div class="form-row"><label for="rule-end">结束时间</label><input id="rule-end" type="datetime-local" step="1" value="${P.dateInput(d.validity.end_time)}" required aria-describedby="timezone-note"></div>
 <p class="field-hint" id="timezone-note">北京时间，到期后自动停止。</p>
 <div class="form-row"><span class="row-label">在哪里查看</span><span>本网站的“提醒记录”</span></div>
 <p class="field-hint">关闭页面后不发送系统推送。重新打开“提醒记录”查看。</p>
 <p class="summary-preview" id="rule-summary"></p>
 ${state.compilation&&state.compilation.ai_requested&&state.compilation.engine!=='deepseek'?'<p class="review-warnings">'+(state.compilation.fallback_reason==='DAILY_LIMIT'?'今天的 AI 试用次数已用完。':state.compilation.fallback_reason==='AI_BUSY'?'AI 正忙。':'这次没有用上 AI。')+'已按文字中的条件整理，请核对后再开启。</p>':''}
 ${editing?'<p class="field-hint">修改后保留历史记录，已有提醒间隔继续生效。</p>':''}
 <details class="advanced"><summary>更多设置</summary>
 <div class="form-row"><label for="rule-cooldown">提醒间隔</label><div><input id="rule-cooldown" type="number" min="0" max="1440" step="1" required value="${d.governance.cooldown_minutes}" aria-label="提醒间隔（分钟）"><p class="field-hint">分钟。期间继续检查，保留新公告。</p></div></div>
 <div class="form-row"><label for="rule-frequency">检查频率</label><div><input id="rule-frequency" type="number" min="10" max="3600" step="1" required value="${d.governance.frequency_seconds}" aria-label="检查间隔（秒）"><p class="field-hint">秒。相同事件不会重复提醒。</p></div></div>
 <div class="form-row"><label for="rule-hours">价格检查时间</label><select id="rule-hours"><option value="true" ${d.governance.trading_hours_only?'selected':''}>仅交易时段</option><option value="false" ${!d.governance.trading_hours_only?'selected':''}>不限时段</option></select></div>
 <p class="field-hint">不限时段仍要求来源数据有效；公告独立检查。</p></details>
 <details class="technical"><summary>开发者详情</summary>
 <p>${state.compilation?'实际解析：'+esc(state.compilation.engine)+' · '+esc(state.compilation.model||'本地解析')+' · '+state.compilation.latency_ms+' ms':'当前规则版本：'+d.version}</p>
 ${(state.warnings||[]).map(w=>'<p>'+esc(w)+'</p>').join('')}
 <p>价格按交易日与规则版本去重，公告按事件指纹去重。</p>
 <button type="button" class="secondary" id="refresh-json">读取当前设置为JSON</button><textarea class="json-text" id="rule-json" aria-label="完整规则JSON">${esc(JSON.stringify(d,null,2))}</textarea><button type="button" class="secondary" id="apply-json">应用JSON草稿</button>
 <p>仅修改草稿，点击确认或保存后生效。服务端会再次校验。</p></details>
 <p id="rule-error" class="inline-error" role="alert" tabindex="-1" hidden></p>`;
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
 try{const spec=collectRules(),editing=!!state.editing,tour=state.walkthrough;
 if(new Date(spec.validity.end_time)<=new Date(spec.validity.start_time))throw new Error('结束时间需要晚于开始时间。');
 if(new Date(spec.validity.end_time)<=new Date())throw new Error('结束时间已过去，请选择之后的时间。');
 if(spec.conditions.some(c=>c.type==='CALENDAR'&&(new Date(c.at)<new Date(spec.validity.start_time)||new Date(c.at)>=new Date(spec.validity.end_time))))throw new Error('指定提醒时间需要在开始时间之后、结束时间之前。请调整提醒日期或延长监控期限。');
 if(state.manualDraft)spec.user_intent_raw='手动设置：'+spec.target.name+'，'+spec.conditions.map(P.describe).join(spec.condition_logic==='AND'?'，且':'，或');
 const payload={task_spec:spec,activate:true,compilation_id:state.compilation?.compilation_id||null},signature=JSON.stringify(payload);
 if(!state.saveRequest||state.saveRequest.signature!==signature)state.saveRequest={signature,key:crypto.randomUUID()};
 let t;if(editing)t=await api('/api/tasks/'+state.editing.id,'PUT',{task_spec:spec,expected_version:state.editing.spec.version});else t=await api('/api/tasks/create','POST',{...payload,request_key:state.saveRequest.key});
 state.saveRequest=null;
 if(t.spec.data_mode==='replay')state.demoId=t.id;$('#rule-dialog').close();toast(editing?'修改已保存。':'提醒已创建。');
 // Save success is distinct from a first-check failure; never submit the task twice.
 try{await api('/api/simulate/tick','POST',{task_id:t.id});}catch{showError('#page-error','提醒已保存，首次检查暂未完成。可在任务记录中查看后续状态。');}
 await refresh();
 if(!editing&&tour&&state.walkthrough===tour){
  if(O.isExample(t.spec)){tour.step='drop';tour.taskId=t.id;setView('demo');renderTutorial();$('#walkthrough-title').focus();}
  else{stopTutorial();setView('dashboard');toast('已按你修改的条件创建提醒。可以在“我的提醒”中查看。');}
 }
 }catch(e){showError('#rule-error',e.message);}finally{b.disabled=false;}
}
function defaultCondition(type){
 const id='c_'+crypto.randomUUID().replaceAll('-','').slice(0,12),base={id,type,operator:'<=',display_text:'',source:''};
 if(type==='ANNOUNCEMENT_EVENT')return {...base,event_category:'PERFORMANCE_FORECAST'};
 if(type==='CALENDAR')return {...base,at:new Date(Date.now()+86400000).toISOString()};
 return {...base,threshold:type==='PRICE_CHANGE_RATIO'?-.03:type==='PRICE'?100:3,operator:type==='HEAT'?'>=':'<='};
}
function manualCompose(source){
 stopTutorial();composeRequest++;state.editing=null;state.compilation=null;state.warnings=[];state.manualDraft=true;state.saveRequest=null;
 const now=new Date(),end=new Date(now.getTime()+14*86400000);
 state.draft=source?copy(source.spec):{schema_version:'1.0',version:1,user_intent_raw:'手动设置提醒',
  target:copy(selectedTarget()||state.meta.symbols[0]),validity:{start_time:now.toISOString(),end_time:end.toISOString(),timezone:'Asia/Shanghai'},
  condition_logic:'OR',conditions:[defaultCondition('PRICE_CHANGE_RATIO')],
  governance:{frequency_seconds:60,trading_hours_only:true,cooldown_minutes:30,deduplication_keys:['announcement_id','trading_date'],alert_channels:['WEB_INBOX']},data_mode:$('#mode').value};
 state.draft.version=1;state.draft.validity={start_time:now.toISOString(),end_time:end.toISOString(),timezone:'Asia/Shanghai'};
 if(source)state.draft.conditions=state.draft.conditions.map(c=>c.type==='CALENDAR'?{...c,at:new Date(Date.now()+86400000).toISOString()}:c);
 $('#compose-dialog').close();showRules();
 $('#rule-title').textContent=source?'复制为新提醒':'选择提醒条件';
 $('#rule-body .context-tip').textContent=source?'原提醒和历史记录保留。新提醒默认持续14天，指定时间已顺延；请核对后开启。':'下方是默认示例：'+state.draft.target.name+'下跌3%，持续14天。请修改公司与条件，再确认开启。';
}
function changeConditions(removeIndex){
 try{
  const draft=collectRules();
  if(removeIndex!==undefined){if(draft.conditions.length<=1)return;draft.conditions.splice(removeIndex,1);}
  else{if(draft.conditions.length>=6)return;draft.conditions.push(defaultCondition($('#new-condition-type').value));}
  state.draft=draft;showRules();
 }catch(error){showError('#rule-error',error.message);}
}
async function loadOlderAlerts(){
 if(!state.alertCursor)return;
 const data=await api('/api/alerts?limit=50&before_id='+state.alertCursor+'&unread_only='+state.unreadOnly);
 const ids=new Set(state.alerts.map(a=>a.id));state.alerts.push(...data.alerts.filter(a=>!ids.has(a.id)));
 state.alertOlder=true;state.alertCursor=data.next_cursor;state.alertHasMore=data.has_more;state.alertUnread=data.unread;state.alertTotal=data.total;renderAlerts();
}
async function showAlert(id){
 syncNavigation(false);
 const request=++alertRequest;$('#alert-detail-body').innerHTML='<p>正在读取这条提醒…</p>';
 if(!$('#alert-detail-dialog').open)$('#alert-detail-dialog').showModal();
 try{
  let alert=await api('/api/alerts/'+id);if(request!==alertRequest||!$('#alert-detail-dialog').open)return;
  const render=()=>{
   $('#alert-detail-title').textContent=alert.title;
   $('#alert-detail-body').innerHTML=`<p>${modeTag(alert.mode)} ${esc(P.formatDate(alert.timestamp))}${alert.mode==='replay'?' · 演示时钟':''}${alert.rule_version?' · 第'+alert.rule_version+'版条件':''}</p>
    <p class="context-tip">以下保留这条通知生成时的结果。后来修改条件，不会改变这里的证据。</p>
    ${alert.evidence?.length?alert.evidence.map(evidenceCard).join(''):'<p>'+esc(alert.message)+'</p><p class="field-hint">这条早期记录没有保存逐项证据。</p>'}
    <div class="feedback-box"><p>这条提醒对你有用吗？</p><div class="feedback-actions">${Object.entries({useful:'有用',noisy:'打扰太多',incorrect:'判断有误'}).map(([key,label])=>`<button class="secondary" data-action="alert-feedback" data-id="${alert.id}" data-feedback="${key}" aria-pressed="${alert.feedback===key}">${label}</button>`).join('')}</div>
    <p class="field-hint" id="feedback-status">${alert.feedback?'反馈已保存。再次点击可撤回。':'反馈只用于改进提醒，保存在本服务，不会改变股票监控条件。'}</p></div>
    <button class="text-button" data-action="alert-task-history" data-id="${esc(alert.task_id)}">查看任务的全部检查记录</button>`;
  };
  render();
  if(!alert.read_at){alert=await api('/api/alerts/'+id+'/read','POST');if(request!==alertRequest)return;
   const index=state.alerts.findIndex(a=>a.id===alert.id);if(index>=0)state.alerts[index]=alert;await refresh();}
 }catch(error){if(request===alertRequest)$('#alert-detail-body').textContent=error.message;}
}
async function showReport(){
 syncNavigation(false);
 const request=++reportRequest,mode=$('#report-mode').value;
 $('#report-body').innerHTML='<p>正在读取运行记录…</p>';$('#report-export').href='/api/workspace-report?mode='+mode;
 if(!$('#report-dialog').open)$('#report-dialog').showModal();
 try{
  const r=await api('/api/workspace-report?mode='+mode);if(request!==reportRequest||!$('#report-dialog').open)return;
  const n=r.notifications,t=r.timing;
  const rows=[['整理文字',r.parse_requested+'次请求，'+r.parse_ready+'次生成草稿，'+r.parse_failed+'次需要调整'],['创建提醒',r.created+'条，包含直接选择条件'],['完成检查',r.checks+'次，其中'+r.unknown_checks+'次无法完整判断'],['通知记录',n.generated+'条已保存，'+n.opened+'条已打开'],['收到反馈',n.useful+'条有用，'+n.noisy+'条打扰太多，'+n.incorrect+'条判断有误'],['检查耗时',t.sample_size?t.sample_size+'次样本；中位数'+t.p50_ms+'毫秒，95%不超过'+t.p95_ms+'毫秒':'尚无带耗时的检查记录'],['自动检查延迟',t.scheduled_sample_size?t.scheduled_sample_size+'次样本；95%不超过'+t.delay_p95_seconds+'秒':'尚无自动检查样本']];
  $('#report-body').innerHTML='<p class="field-hint">最近7天 · 仅当前浏览器 · '+(mode==='replay'?'模拟数据':'真实数据')+'</p><dl class="report-values">'+rows.map(([k,v])=>'<div><dt>'+k+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl><p>'+esc(r.limits)+'</p><p class="field-hint">只统计有实际写入时间的记录；耗时与延迟最多取最近5000次，不使用推进后的演示时间计算耗时。暂无样本时不显示成功率。</p><p class="field-hint">版本 '+esc(r.build.version)+' · '+esc(r.build.source_sha256.slice(0,12))+'</p>';
 }catch(error){if(request===reportRequest)$('#report-body').textContent=error.message;}
}
function evidenceCard(c){
 const truth=c.satisfied===true?'true':c.satisfied===false?'false':'unknown';
 const label=['PRICE','PRICE_CHANGE_RATIO','HEAT'].includes(c.type)?P.describe(c):c.display_text;
 const metric=typeof c.actual_value==='number'&&c.type!=='ANNOUNCEMENT_EVENT'?(c.type==='PRICE_CHANGE_RATIO'?P.number(P.percent(c.actual_value))+'%':P.number(c.actual_value)+(c.type==='PRICE'?'元':'')):'';
 return `<div class="evidence-card"><div class="evidence-heading"><span>${esc(label)}</span><span class="truth ${truth}">${{true:'已满足',false:'未满足',unknown:c.suspended?'休市中':'无法判断'}[truth]}</span></div>${metric?'<strong class="evidence-metric">'+esc(metric)+'</strong>':''}<p>${esc(c.reason)}</p>${c.formula?'<p>现价 '+esc(c.last)+'元，昨收 '+esc(c.previous_close)+'元。</p>':''}${(c.events||[]).map(e=>'<p>'+esc(e.title)+'<br><span class="muted">'+esc(P.formatDate(e.published_at))+(e.freshness_note?' · '+esc(e.freshness_note):'')+'</span></p>').join('')}<p class="evidence-source">${esc(c.source||'系统时钟')} · ${esc(P.formatDate(c.observed_at))}</p>${c.coverage?'<p class="evidence-source">'+esc(c.coverage)+'</p>':''}</div>`;
}
function selectAuditTab(versions){state.auditTab=versions?'versions':'checks';$('#show-audits').classList.toggle('active',!versions);$('#show-versions').classList.toggle('active',versions);$('#show-audits').setAttribute('aria-pressed',String(!versions));$('#show-versions').setAttribute('aria-pressed',String(versions));}
async function showAudits(id,older=false){
 const request=++auditRequest;state.auditTask=id;selectAuditTab(false);const t=state.tasks.find(t=>t.id===id);
 const cursor=older?state.auditCursor:null;
 if(!older)state.auditEntries=[];
 $('#audit-title').textContent=(t?t.spec.target.name+' · ':'')+'检查记录';$('#export-link').href='/api/tasks/'+encodeURIComponent(id)+'/export';$('#audit-body').innerHTML='<p class="muted">正在读取检查记录…</p>';if(!$('#audit-dialog').open)$('#audit-dialog').showModal();
 try{const data=await api('/api/tasks/'+encodeURIComponent(id)+'/audit-trail?limit=50'+(cursor?'&before_id='+cursor:''));if(request!==auditRequest||!$('#audit-dialog').open)return;
 state.auditEntries.push(...data.history);state.auditCursor=data.next_cursor;
 $('#audit-body').innerHTML='<p class="field-hint">显示'+state.auditEntries.length+'条，共'+data.total+'条。导出文件包含最近1000条；更早的记录可在这里继续查看。</p>'+state.auditEntries.map((a,i)=>`<details class="audit-entry" ${i===0?'open':''}><summary><div class="audit-date"><span>${esc(P.formatDate(a.timestamp))}${a.data_mode==='replay'?' · 演示时钟':''}</span>${modeTag(a.data_mode)}</div><h3>${esc(P.summary(a.action_taken,a.pending_event_count))}</h3></summary>${(a.conditions_evaluated||[]).map(evidenceCard).join('')}${a.kind==='evaluation'?'<p class="evidence-source">'+(a.notification_sent?'已生成提醒':'未生成提醒')+' · 待提醒公告 '+(a.pending_event_count||0)+' 条</p>':''}<details class="technical"><summary>本次规则与原始记录</summary><p>规则版本 ${a.rule_version}；原始检查时间 ${esc(a.timestamp)}</p><pre>${esc(JSON.stringify(a,null,2))}</pre></details></details>`).join('')+(data.has_more?'<button class="secondary" data-action="older-audits" data-id="'+esc(id)+'">加载更早的检查</button>':'<p class="field-hint">已显示全部检查记录。</p>');
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
 if(action==='welcome')showWelcome();
 else if(action==='welcome-skip')dismissWelcome();
 else if(action==='tutorial-start')startTutorial();
 else if(action==='tutorial-next')await tutorialNext();
 else if(action==='tutorial-stop'){stopTutorial();$('#new-alert').focus();}
 else if(action==='manual')manualCompose();
 else if(action==='duplicate')manualCompose(task);
 else if(action==='report')await showReport();
 else if(action==='older-alerts')await loadOlderAlerts();
 else if(action==='older-audits')await showAudits(id,true);
 else if(action==='alert-open')await showAlert(id);
 else if(action==='alert-task-history'){$('#alert-detail-dialog').close();await showAudits(id);}
 else if(action==='alert-feedback'){
  const current=await api('/api/alerts/'+id),feedback=current.feedback===button.dataset.feedback?null:button.dataset.feedback;
  const updated=await api('/api/alerts/'+id+'/feedback','PUT',{feedback});const index=state.alerts.findIndex(a=>a.id===updated.id);if(index>=0)state.alerts[index]=updated;
  document.querySelectorAll('[data-action="alert-feedback"]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.feedback===feedback)));
  $('#feedback-status').textContent=feedback?'反馈已保存。再次点击可撤回。':'反馈已撤回。';await refresh();
 }
 else if(action==='check'){await api('/api/tasks/'+id+'/check','POST');await refresh();toast('本次检查已完成，可查看具体记录。');}
 else if(action==='new'){stopTutorial();showCompose();}else if(action==='demo-new'){stopTutorial();showCompose(true);}
 else if(action==='clear-filter'){$('#task-search').value='';setFilter('all');}
 else if(action==='audit')await showAudits(id);
 else if(action==='edit'){state.editing=copy(task);state.manualDraft=false;state.draft=copy(task.spec);state.compilation=null;state.warnings=[];showRules();}
 else if(action==='archive'){state.archiveId=id;$('#archive-description').textContent=task.spec.target.name+'的这条提醒将停止运行。';showError('#archive-error','');$('#archive-dialog').showModal();}
 else if(action==='scenario'){
  const demo=state.tasks.find(t=>t.id===state.demoId);if(!demo||demo.spec.data_mode!=='replay'||demo.state.paused)throw new Error('请先创建或恢复演示提醒。');
  const t=await api('/api/simulate/inject','POST',{task_id:demo.id,scenario:button.dataset.scenario});await refresh();$('#scenario-result').textContent=P.summary(t.state.last_decision,Object.keys(t.state.pending_events||{}).length)+' 条件提醒共'+t.state.trigger_count+'条。';
 }else if(action==='rollback'){await api('/api/tasks/'+id+'/rollback','POST',{version:Number(button.dataset.version),expected_version:task.spec.version});await refresh();await showVersions();toast('这组条件已恢复，历史记录保留。');}
 else if(action==='pause'||action==='resume'){await api('/api/tasks/'+id+'/'+action,'POST');await refresh();toast(action==='pause'?'已暂停检查。':'已恢复监控。');}
 }catch(e){if($('#alert-detail-dialog').open&&$('#feedback-status'))$('#feedback-status').textContent=e.message;else{const target=$('#audit-dialog').open?'#audit-body':state.view==='demo'?'#scenario-result':'#page-error';if(target==='#audit-body')$('#audit-body').textContent=e.message;else if(target==='#scenario-result')$('#scenario-result').textContent=e.message;else showError(target,e.message);}}
 finally{if(button.isConnected){if(button.id==='walkthrough-next')renderTutorial();else button.disabled=false;}}
}
document.addEventListener('click',event=>{
 const b=event.target.closest('button');if(!b)return;
 if(b.dataset.close){if(['compose-dialog','rule-dialog'].includes(b.dataset.close))closeAuthoring(b.dataset.close);else $('#'+b.dataset.close).close();return;}
 if(b.dataset.view)setView(b.dataset.view);
 if(b.dataset.filter)setFilter(b.dataset.filter);
 if(b.dataset.example){const name=selectedTarget()?.name||'贵州茅台';$('#prompt').value={golden:`未来两周帮我盯住${name}：日内跌幅达到3%，或者发布新的业绩预告，就提醒我。同一件事别反复提醒；如果监控出了问题，也告诉我。`,price:`未来7天，${name}股价低于1500元提醒我。`,heat:`未来两周，${name}量比达到3时提醒我。`}[b.dataset.example];showError('#parse-error','');$('#prompt').focus();}
 if(b.dataset.action)runAction(b);
});
$('#welcome-dialog').addEventListener('cancel',event=>{event.preventDefault();dismissWelcome();});
for(const id of ['compose-dialog','rule-dialog'])$('#'+id).addEventListener('cancel',event=>{event.preventDefault();closeAuthoring(id);});
$('#compose-form').addEventListener('submit',parsePrompt);$('#rule-form').addEventListener('submit',saveRules);
$('#cancel-rule').addEventListener('click',()=>{$('#rule-dialog').close();if(!state.editing&&!state.manualDraft){$('#compose-dialog').showModal();$('#prompt').focus();}else $('#new-alert').focus();});
$('#audit-dialog').addEventListener('close',()=>auditRequest++);
$('#rule-form').addEventListener('invalid',event=>{let parent=event.target.parentElement;while(parent&&parent!==event.currentTarget){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}},true);
$('#rule-body').addEventListener('input',()=>{showError('#rule-error','');updateRulePreview();});
$('#rule-body').addEventListener('change',updateRulePreview);
$('#rule-body').addEventListener('click',e=>{try{if(e.target.id==='add-condition')changeConditions();else if(e.target.dataset.removeCondition!==undefined)changeConditions(Number(e.target.dataset.removeCondition));else if(e.target.id==='refresh-json')$('#rule-json').value=JSON.stringify(collectRules(),null,2);else if(e.target.id==='apply-json'){const d=validateJsonDraft(JSON.parse($('#rule-json').value));state.draft=copy(d);showRules();}}catch(error){showError('#rule-error',error.message);}});
$('#alert-detail-dialog').addEventListener('close',()=>alertRequest++);
$('#report-mode').addEventListener('change',showReport);
$('#report-dialog').addEventListener('close',()=>reportRequest++);
$('#unread-filter').addEventListener('change',async()=>{if(state.refreshing)await state.refreshing;state.unreadOnly=$('#unread-filter').checked;state.alertOlder=false;state.alerts=[];await refresh();});
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
async function init(){try{
 state.meta=await api('/api/meta');
 $('#target').innerHTML='<option value="">使用文字中的公司</option>'+state.meta.symbols.map(s=>`<option value="${esc(s.symbol)}">${esc(s.name)} · ${s.symbol.slice(0,6)}</option>`).join('');
 $('#use-ai').checked=false;$('#use-ai').disabled=!state.meta.ai_available;
 $('#mode option[value="live"]').disabled=!state.meta.live_available;
 $('#new-alert').disabled=false;$('#welcome-start').disabled=false;$('#welcome-service-note').hidden=true;
 updateModeHint();await refresh();if(welcomePreferences.shouldWelcome())showWelcome();setInterval(refresh,4000);
 }catch(e){showError('#page-error','服务暂时未连接，请刷新页面重试。');}}
init();
