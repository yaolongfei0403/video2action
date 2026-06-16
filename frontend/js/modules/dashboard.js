/* Module 1: Dashboard - 总览指标 */
const Dashboard = {
  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-5">
        <div>
          <h2 class="text-xl font-semibold text-white">Dashboard 总览</h2>
          <p class="text-[12px] text-gray-500 mt-1">实时监控 4D 动作知识库系统运行状态</p>
        </div>
        <div class="flex gap-2">
          <button class="btn" onclick="App.switchModule('task-center')"><i class="fas fa-list"></i>任务中心</button>
        </div>
      </div>
      <div id="dashboard-metrics" class="module-grid module-grid-dashboard mb-5">
        ${[1,2,3,4].map(() => `<div class="metric-card"><div class="label">加载中…</div></div>`).join('')}
      </div>
      <div class="module-grid" style="grid-template-columns: 1fr 1fr; gap:16px;">
        <div class="card">
          <h3 class="card-title">资产分类</h3>
          <div id="category-stats">加载中…</div>
        </div>
        <div class="card">
          <h3 class="card-title">最近视频</h3>
          <div id="recent-videos">加载中…</div>
        </div>
      </div>
    `;
    // 异步加载
    setTimeout(async () => {
      try {
        const m = await API.metrics();
        Utils.setHTML('dashboard-metrics', `
          <div class="metric-card">
            <div class="label">总资产</div>
            <div class="value">${Utils.formatNumber(m.total_assets)}</div>
            <div class="delta">入库动作片段</div>
          </div>
          <div class="metric-card">
            <div class="label">处理中</div>
            <div class="value">${m.processing_tasks}</div>
            <div class="delta">${m.gpu_idle}/${m.gpu_total} GPU 空闲</div>
          </div>
          <div class="metric-card">
            <div class="label">成功率</div>
            <div class="value">${(m.success_rate * 100).toFixed(1)}%</div>
            <div class="delta">端到端</div>
          </div>
          <div class="metric-card">
            <div class="label">视频源</div>
            <div class="value">${m.videos_today}</div>
            <div class="delta">本地 / GUID</div>
          </div>
        `);
        const cs = await API.categoryStats();
        const cats = cs.categories;
        Utils.setHTML('category-stats', Object.entries(cats).map(([k, v]) => `
          <div class="row" style="margin-bottom:6px;">
            <span style="width:80px; font-size:12px;">${k}</span>
            <div class="progress-bar flex-1"><div class="progress-bar-fill" style="width:${(v / Math.max(cs.total, 1) * 100).toFixed(0)}%"></div></div>
            <span style="width:60px; text-align:right; font-family:monospace; font-size:11px;">${v}</span>
          </div>
        `).join(''));
        const r = await API.recent();
        Utils.setHTML('recent-videos', r.videos.length === 0
          ? '<div class="empty"><i class="fas fa-video"></i>暂无视频</div>'
          : r.videos.slice(0, 6).map(v => `
            <div class="list-item" style="margin-bottom:6px;">
              <i class="fas fa-file-video text-brand-blue"></i>
              <div class="flex-1 min-w-0">
                <div class="text-sm text-white truncate">${v.name || v.guid || v.id}</div>
                <div class="text-xs text-muted">${Utils.formatDuration(v.duration)} · ${v.status}</div>
              </div>
              <span class="text-xs text-muted">${Utils.formatDate(v.created_at)}</span>
            </div>
          `).join(''));
      } catch (e) {
        console.error(e);
        Utils.setHTML('dashboard-metrics', `<div class="metric-card"><div class="label">加载失败</div><div class="text-xs text-muted">${e.message}</div></div>`);
      }
    }, 50);
    return root;
  }
};
