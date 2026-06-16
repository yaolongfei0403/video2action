/* App 入口 - 模块路由 + 初始化 */
const App = (() => {
  const modules = {
    'dashboard': () => Dashboard.render(),
    'task-center': () => Tasks.render(),
    'video-import': () => VideoImport.render(),
    'rough-cut': () => RoughCut.render(),
    'fine-cut': () => FineCut.render(),
    'target': () => Target.render(),
    '4d': () => FourD.render(),
    'tagging': () => Tagging.render(),
    'asset-library': () => Assets.render(),
    'semantic-search': () => Search.render(),
    'completed': () => Completed.render(),
  };

  function switchModule(name) {
    if (!modules[name]) {
      console.warn(`Unknown module: ${name}`);
      return;
    }
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const navItem = document.querySelector(`.nav-item[data-module="${name}"]`);
    if (navItem) navItem.classList.add('active');
    document.querySelectorAll('.pipeline-step').forEach(el => {
      el.classList.toggle('active', el.dataset.step === name);
    });
    window.location.hash = `#/${name}`;
    // 切换前：把当前根内所有 <video> 都 reset（pause + 清 src），
    // 避免 play() promise 在 DOM 销毁后报 "interrupted"
    const root = document.getElementById('module-root');
    if (!root) { console.error('module-root not found!'); return; }
    if (window.Utils && typeof window.Utils.resetPlayer === 'function') {
      root.querySelectorAll('video').forEach(v => window.Utils.resetPlayer(v));
    }
    root.innerHTML = '';
    try {
      const result = modules[name]();
      if (result instanceof HTMLElement) {
        root.appendChild(result);
      } else if (result && result.then) {
        // 异步
        result.then(el => {
          if (el instanceof HTMLElement) root.appendChild(el);
        }).catch(e => {
          root.innerHTML = `<div class="empty"><i class="fas fa-exclamation-triangle"></i>模块加载失败: ${e.message}</div>`;
        });
      } else {
        root.innerHTML = `<div class="empty"><i class="fas fa-exclamation-triangle"></i>模块 ${name} 未返回 HTMLElement</div>`;
      }
    } catch (e) {
      console.error(e);
      root.innerHTML = `<div class="empty"><i class="fas fa-exclamation-triangle"></i>模块加载失败: ${e.message}</div>`;
    }
    const main = document.getElementById('main-content');
    if (main) main.scrollTop = 0;
  }

  async function init() {
    // 调试横幅：显示加载状态
    const root = document.getElementById('module-root');
    if (root) {
      root.innerHTML = '<div class="empty"><i class="fas fa-spinner spin"></i>初始化中…</div>';
    }

    // 绑定 nav 点击
    document.querySelectorAll('.nav-item').forEach(el => {
      el.addEventListener('click', () => switchModule(el.dataset.module));
    });
    document.querySelectorAll('.pipeline-step').forEach(el => {
      el.addEventListener('click', () => switchModule(el.dataset.step));
    });
    // hash 路由
    const hash = window.location.hash.replace('#/', '') || 'dashboard';
    switchModule(hash);
    // 启动：探测后端
    try {
      const m = await API.metrics();
      const el = document.getElementById('backend-status');
      if (el) el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-brand-green pulse-dot"></span><span>后端在线</span>`;
      // 更新侧边栏任务徽章（真实任务数）
      const badge = document.getElementById('task-center-badge');
      if (badge) badge.textContent = String(m.processing_tasks);
    } catch (e) {
      const el = document.getElementById('backend-status');
      if (el) el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-brand-red"></span><span>后端离线</span>`;
    }
  }

  return { switchModule, init };
})();

document.addEventListener('DOMContentLoaded', () => App.init());
