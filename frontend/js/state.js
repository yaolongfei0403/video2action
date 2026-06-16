/* 全局状态 - 简单 pub/sub */
const State = (() => {
  const state = {
    currentVideo: null,
    currentClip: null,
    currentTask: null,
    currentFrame: 0,
    objIds: [],            // 当前 clip 下的目标 id 列表
    fps: 30.0,
    pointType: 'positive', // positive / negative
    assets: [],
    tasks: [],
  };
  const listeners = {};

  function get(key) { return state[key]; }
  function set(key, val) {
    state[key] = val;
    emit(`${key}:update`, val);
    emit('any:update', { key, val });
  }
  function on(event, cb) { (listeners[event] ||= []).push(cb); }
  function emit(event, data) {
    (listeners[event] || []).forEach(cb => { try { cb(data); } catch (e) { console.error(e); } });
  }

  return { get, set, on, emit };
})();
