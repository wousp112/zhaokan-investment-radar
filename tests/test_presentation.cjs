/* Run with: node --test tests/test_presentation.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../app/web/static/presentation.js');
const cmp = (a, op, b) => ({'<':a<b, '<=':a<=b, '>':a>b, '>=':a>=b})[op];

test('display edits preserve all four operators, both directions and equality', () => {
  for (const threshold of [-0.03, 0, 0.03]) {
    for (const operator of ['<', '<=', '>', '>=']) {
      const rule = {id:'price', type:'PRICE_CHANGE_RATIO', operator, threshold};
      const display = P.toDisplay(rule);
      const saved = P.fromDisplay(rule, display);
      assert.equal(saved.threshold, threshold);
      assert.equal(saved.operator, operator);
      for (const actual of [-0.04, -0.03, -0.02, 0, 0.02, 0.03, 0.04]) {
        assert.equal(cmp(actual, saved.operator, saved.threshold), cmp(actual, operator, threshold));
      }
    }
  }
});

test('down at least 3% includes -3%, while more than 3% excludes it', () => {
  const rule = {type:'PRICE_CHANGE_RATIO'};
  const inclusive = P.fromDisplay(rule, {direction:'down', operator:'>=', value:'3'});
  const strict = P.fromDisplay(rule, {direction:'down', operator:'>', value:'3'});
  assert.equal(inclusive.operator, '<=');
  assert.equal(strict.operator, '<');
  assert.ok(cmp(-0.03, inclusive.operator, inclusive.threshold));
  assert.ok(!cmp(-0.03, strict.operator, strict.threshold));
  assert.equal(P.describe(inclusive), '较昨收下跌达到3%');
  assert.equal(P.describe(strict), '较昨收下跌超过3%');
});

test('direction changes and positive prices save correct values', () => {
  const rule = {id:'price',type:'PRICE_CHANGE_RATIO',operator:'<=',threshold:-0.03};
  const saved = P.fromDisplay(rule, {direction:'up',operator:'>=',value:'4'});
  assert.equal(saved.threshold, .04);
  assert.equal(saved.operator, '>=');
  assert.equal(P.describe(P.fromDisplay({type:'PRICE'}, {operator:'<',value:'1500'})), '股价低于1500元');
  assert.equal(P.describe(P.fromDisplay({type:'HEAT'}, {operator:'>=',value:'3'})), '量比不低于3');
});

test('missing, non-finite, negative and invalid values cannot silently become a rule', () => {
  for (const value of ['', 'abc', 'Infinity', '-1']) {
    assert.throws(() => P.fromDisplay({type:'PRICE_CHANGE_RATIO'},{direction:'down',operator:'>=',value}));
  }
  assert.throws(() => P.fromDisplay({type:'PRICE'},{operator:'<',value:'0'}));
  assert.throws(() => P.fromDisplay({type:'PRICE'},{operator:'==',value:'3'}));
});

test('Beijing date fields do not shift in a browser using a different timezone', () => {
  const original = '2026-10-05T13:45:23+08:00';
  assert.equal(P.dateInput(original), '2026-10-05T13:45:23');
  assert.equal(P.readDate(P.dateInput(original), original), original);
  assert.equal(P.readDate('2026-10-06T00:15'), '2026-10-05T16:15:00.000Z');
  assert.throws(() => P.readDate(''));
});

test('paused, expired and archived schedules never claim to keep checking', () => {
  const task = {spec:{governance:{frequency_seconds:60}}, state:{status:'SUSPENDED',paused:true}};
  assert.equal(P.statusLabel(task), '已暂停');
  assert.equal(P.schedule(task), '恢复后继续检查');
  task.state = {status:'SUSPENDED',paused:false};
  assert.equal(P.statusLabel(task), '休市中');
  task.state = {status:'EXPIRED',paused:true};
  assert.equal(P.schedule(task), '监控时间已结束');
  task.state = {status:'ARCHIVED',paused:true};
  assert.equal(P.schedule(task), '已停止检查，记录保留');
});

test('search and lifecycle filters retain business meaning', () => {
  const task = {spec:{target:{name:'贵州茅台',symbol:'600519.SH'},conditions:[{type:'PRICE',operator:'<',threshold:1500}]},state:{status:'COOLING',paused:false}};
  assert.equal(P.visibleTask(task,'running','低于1500'), true);
  assert.equal(P.visibleTask(task,'all','600519.sh'), true);
  assert.equal(P.visibleTask(task,'all','宁德'), false);
  task.state = {status:'DEGRADED',paused:false};
  assert.equal(P.visibleTask(task,'attention',''), true);
  task.state = {status:'ARCHIVED',paused:true};
  assert.equal(P.visibleTask(task,'ended',''), true);
  assert.equal(P.visibleTask(task,'paused',''), false);
});

test('demo audit actions use readable names without claiming market safety', () => {
  assert.equal(P.summary('注入演示情景：recover'), '演示：恢复来源');
  assert.equal(P.summary('注入演示情景：timeout'), '演示：行情超时');
  assert.equal(P.summary('已检查，组合条件未满足，本轮不提醒。'), '尚未达到提醒条件。');
});

test('cooldown copy only claims a saved announcement when one actually exists', () => {
  const action='条件满足但处于冷却期；新公告已保留，冷却结束后重新判断。';
  assert.equal(P.summary(action,0),'仍在提醒间隔内，稍后重新判断。');
  assert.equal(P.summary(action,1),'仍在提醒间隔内；新公告已保留，稍后再判断。');
});

test('fractional percentages display cleanly without silently rounding an existing rule', () => {
  for(const threshold of [-.035,-.0125,-.00000001,-.12345678901234566]){
    const rule={type:'PRICE_CHANGE_RATIO',operator:'<=',threshold};
    assert.equal(P.fromDisplay(rule,P.toDisplay(rule)).threshold,threshold);
  }
  assert.equal(P.percent(.035),3.5);
  assert.equal(P.toDisplay({type:'PRICE_CHANGE_RATIO',operator:'<=',threshold:-.035}).value,3.5);
  assert.equal(P.fromDisplay({type:'PRICE_CHANGE_RATIO'},{operator:'>=',direction:'down',value:'3.5'}).threshold,-.035);
});
