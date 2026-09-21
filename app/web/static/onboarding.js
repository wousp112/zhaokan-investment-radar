(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RadarOnboarding = api;
})(typeof window !== 'undefined' ? window : this, function() {
  'use strict';
  const KEY = 'zhaokan.welcome.v1';
  // Restricted storage must never prevent creating a reminder.
  function preferences(storageGetters) {
    let memory = null;
    function read() {
      if (memory) return memory;
      for (const getStorage of storageGetters) {
        try {
          const value = JSON.parse(getStorage().getItem(KEY));
          if (['dismissed', 'started', 'completed'].includes(value?.status)) return value;
        } catch {}
      }
      return null;
    }
    function remember(status) {
      if (!['dismissed', 'started', 'completed'].includes(status)) throw new Error('Invalid welcome status');
      memory = {status};
      for (const getStorage of storageGetters) {
        try { getStorage().setItem(KEY, JSON.stringify(memory)); } catch {}
      }
    }
    return {shouldWelcome: () => !read(), remember};
  }
  // A changed example or a real-data task must never enter the price simulation.
  function isExample(spec) {
    if (spec?.data_mode !== 'replay' || spec.target?.symbol !== '600519.SH' || spec.condition_logic !== 'OR' || spec.conditions?.length !== 2) return false;
    return spec.conditions.some(c => c.type === 'PRICE_CHANGE_RATIO' && c.operator === '<=' && c.threshold === -.03)
      && spec.conditions.some(c => c.type === 'ANNOUNCEMENT_EVENT' && c.event_category === 'PERFORMANCE_FORECAST');
  }
  function exampleAlert(alerts, taskId) {
    return alerts.find(a => a.task_id === taskId && a.mode === 'replay' && a.kind === 'condition') || null;
  }
  return {KEY, preferences, isExample, exampleAlert};
});
