/* Presentation-only conversions. Stored Rule DSL and comparisons remain unchanged. */
(function(root){
'use strict';
const flip={'<=':'>=','>=':'<=','<':'>','>':'<'};
const number=v=>Number(v).toString();
// Shift decimal exponents without displaying binary tails such as 3.5000000000000004.
function shiftDecimal(value,places){const [base,exponent='0']=String(value).split('e');return Number(base+'e'+(Number(exponent)+places));}
const percent=v=>shiftDecimal(v,2);
function toDisplay(c){const down=c.type==='PRICE_CHANGE_RATIO'&&c.threshold<0;return {direction:down?'down':'up',operator:down?flip[c.operator]:c.operator,value:c.type==='PRICE_CHANGE_RATIO'?percent(Math.abs(c.threshold)):c.threshold};}
function fromDisplay(c,d){
 const value=Number(d.value);
 if(d.value===''||!Number.isFinite(value))throw new Error('请填写有效的条件数值。');
 if(!flip[d.operator])throw new Error('请选择比较方式。');
 if(value<0||(c.type!=='PRICE_CHANGE_RATIO'&&value===0))throw new Error('请使用正数填写条件；涨跌幅可为0。');
 const ratio=c.type==='PRICE_CHANGE_RATIO',down=ratio&&d.direction==='down',previous=toDisplay(c);
 const unchanged=ratio&&value===previous.value&&d.direction===previous.direction&&d.operator===previous.operator;
 return {...c,operator:down?flip[d.operator]:d.operator,threshold:unchanged?c.threshold:ratio?shiftDecimal(value,-2)*(down?-1:1):value};
}
const eventLabels={PERFORMANCE_FORECAST:'新的业绩预告',PERFORMANCE_REPORT:'新的业绩快报',ANY_ANNOUNCEMENT:'新的公司公告'};
function describe(c){
 if(c.type==='ANNOUNCEMENT_EVENT')return '发布'+(eventLabels[c.event_category]||'新的公司公告');
 if(c.type==='CALENDAR')return '到达 '+formatDate(c.at);
 const d=toDisplay(c),op={'>=':'达到','>':'超过','<':'低于','<=':'不高于'}[d.operator];
 if(c.type==='PRICE_CHANGE_RATIO'){
  if(d.value===0)return '较昨收涨跌幅'+({'<=':'不高于','<':'低于','>=':'不低于','>':'高于'}[c.operator])+'0%';
  const inclusive=(d.operator==='<'||d.operator==='<=')?(d.direction==='down'?'（含持平或上涨）':'（含持平或下跌）'):'';
  return '较昨收'+(d.direction==='down'?'下跌':'上涨')+op+number(d.value)+'%'+inclusive;
 }
 return (c.type==='PRICE'?'股价':'量比')+({'<=':'不高于','<':'低于','>=':'不低于','>':'高于'}[c.operator])+number(d.value)+(c.type==='PRICE'?'元':'');
}
function formatDate(value){if(!value)return '暂无记录';const d=new Date(value);if(!Number.isFinite(d.getTime()))return '时间无效';return d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
function dateInput(value){return new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,19);}
function readDate(value,original){if(original&&value===dateInput(original))return original;if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value))throw new Error('请填写完整的日期和时间。');const d=new Date(value+'+08:00');if(!Number.isFinite(d.getTime()))throw new Error('日期或时间无效。');return d.toISOString();}
function schedule(task){const s=task.state;if(s.status==='ARCHIVED')return '已停止检查，记录保留';if(s.status==='EXPIRED')return '监控时间已结束';if(s.status==='PENDING')return '确认后开始检查';if(s.paused)return '恢复后继续检查';if(s.status==='SUSPENDED')return '非交易时段，等待开市';if(s.status==='DEGRADED')return '查看记录了解受影响条件';if(s.status==='COOLING')return '提醒间隔内，仍在检查';return '每'+task.spec.governance.frequency_seconds+'秒检查';}
function statusLabel(task){return task.state.status==='SUSPENDED'&&!task.state.paused?'休市中':({PENDING:'待确认',ACTIVE:'监控中',SUSPENDED:'已暂停',COOLING:'提醒间隔中',DEGRADED:'数据待恢复',EXPIRED:'已到期',ARCHIVED:'已归档',TRIGGERED:'已提醒'}[task.state.status]||task.state.status);}
function summary(action,pendingCount){
 if(action==='条件满足但处于冷却期；新公告已保留，冷却结束后重新判断。')return pendingCount>0?'仍在提醒间隔内；新公告已保留，稍后再判断。':'仍在提醒间隔内，稍后重新判断。';
 const scenarios={normal:'未达条件',drop:'下跌至3.8%',deeper:'继续下跌',announcement:'新业绩预告',same_announcement:'重复公告',heat:'量比升至3.6',advance:'推进演示时间',timeout:'行情超时',http500:'服务错误',stale:'数据过期',conflict:'指标冲突',event_failure:'公告故障',recover:'恢复来源',closed:'休市',open:'开市'};
 if(typeof action==='string'&&action.startsWith('注入演示情景：')){const key=action.slice('注入演示情景：'.length);return '演示：'+(scenarios[key]||'切换情景');}
 return ({'已检查，组合条件未满足，本轮不提醒。':'尚未达到提醒条件。','部分条件缺少有效数据，本轮无法完整判断。':'部分数据不可用，暂时无法完整判断。','提醒已写入站内消息，进入冷却。':'已保存一条提醒，继续监控。','提醒已写入站内消息。':'已保存一条提醒。','条件满足但处于冷却期；新公告已保留，冷却结束后重新判断。':'仍在提醒间隔内；新公告已保留，稍后再判断。','条件满足，但同一交易日的该价格规则或相同事件已提醒，不重复发送。':'相同条件已经提醒，本次不再重复。'})[action]||action||'等待首次检查。';
}
function visibleTask(t,filter,query){const s=t.state,ended=['ARCHIVED','EXPIRED'].includes(s.status);const matches=filter==='all'||(filter==='running'&&!ended&&!s.paused&&s.status!=='PENDING')||(filter==='attention'&&s.status==='DEGRADED')||(filter==='paused'&&s.paused&&!ended)||(filter==='ended'&&ended);return matches&&(!query||[t.spec.target.name,t.spec.target.symbol,...t.spec.conditions.map(describe)].join(' ').toLowerCase().includes(query.toLowerCase()));}
const api={toDisplay,fromDisplay,describe,eventLabels,formatDate,dateInput,readDate,schedule,statusLabel,summary,visibleTask,number,percent};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.RadarPresentation=api;
})(typeof window==='undefined'?this:window);
