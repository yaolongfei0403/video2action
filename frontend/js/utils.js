/* 通用工具 - 时间格式化、Toast、防抖等 */

const Utils = {
  // 时间格式化 (mm:ss / hh:mm:ss)
  formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '00:00';
    const s = Math.floor(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
  },

  formatDuration(sec) {
    if (sec < 1) return `${(sec * 1000).toFixed(0)}ms`;
    if (sec < 60) return `${sec.toFixed(1)}s`;
    const m = Math.floor(sec / 60);
    const s = (sec - m * 60).toFixed(0);
    return `${m}m${s}s`;
  },

  // 数字千分位
  formatNumber(n) {
    return Number(n || 0).toLocaleString('en-US');
  },

  // 百分比
  formatPercent(n, total) {
    if (!total) return '0%';
    return `${Math.round((n / total) * 100)}%`;
  },

  // Toast
  toast(msg, type = 'info', duration = 2800) {
    const stack = document.getElementById('toast-stack');
    if (!stack) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icon = {
      success: 'check-circle',
      error: 'exclamation-circle',
      info: 'info-circle',
    }[type] || 'info-circle';
    const color = {
      success: '#10b981',
      error: '#ef4444',
      info: '#3b82f6',
    }[type] || '#3b82f6';
    el.innerHTML = `<i class="fas fa-${icon}" style="color:${color}"></i><span>${msg}</span>`;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity 0.3s, transform 0.3s';
      el.style.opacity = '0';
      el.style.transform = 'translateX(100%)';
      setTimeout(() => el.remove(), 300);
    }, duration);
  },

  // 安全的 DOM 写入（找不到元素时静默跳过，避免异步回调中 null.textContent 报错）
  setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
    return el;
  },
  setHTML(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
    return el;
  },
  setAttr(id, attr, value) {
    const el = document.getElementById(id);
    if (el) el.setAttribute(attr, value);
    return el;
  },
  replaceEl(id, html) {
    const el = document.getElementById(id);
    if (el) el.outerHTML = html;
    return el;
  },

  // 防抖
  debounce(fn, delay = 300) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  },

  // 简单的 HTML 模板
  h(tag, props = {}, ...children) {
    const el = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'html') el.innerHTML = v;
      else el.setAttribute(k, v);
    });
    children.flat().forEach(c => {
      if (c == null || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  },

  // 日期格式化
  formatDate(iso) {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      const pad = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch { return iso; }
  },

  // async 错误处理包装
  async safe(fn, errMsg = '操作失败') {
    try {
      return await fn();
    } catch (e) {
      console.error(e);
      Utils.toast(`${errMsg}: ${e.message || e}`, 'error', 4000);
      throw e;
    }
  },

  // 生成 ID
  genId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  },

  // 静默播放：兼容模块卸载时 play() 被中断的常见场景
  //   浏览器报 "The play() request was interrupted because the media was
  //   removed from the document" 是良性错误，吞掉即可。
  // 真正失败（如 src 404）由 video element 的 error 事件处理。
  safePlay(videoEl) {
    if (!videoEl) return Promise.resolve();
    const p = videoEl.play();
    if (p && typeof p.catch === 'function') {
      p.catch(() => { /* 被中断或被拒绝，静默 */ });
    }
    return p || Promise.resolve();
  },

  // 卸载/切换视频前的清理：暂停 + 清 src，触发 abort 任何待 resolve 的 play()
  resetPlayer(videoEl) {
    if (!videoEl) return;
    try {
      if (!videoEl.paused) videoEl.pause();
    } catch (e) { /* 元素可能已不在文档中 */ }
    try {
      videoEl.removeAttribute('src');
      videoEl.load();   // 强制 abort 任何挂起的 fetch / play
    } catch (e) { /* ignore */ }
  },
};
