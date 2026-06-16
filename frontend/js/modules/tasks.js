/* Module 2: Task Center - 任务管理 */
const Tasks = {
  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-5">
        <div>
          <h2 class="text-xl font-semibold text-white">任务中心</h2>
          <p class="text-[12px] text-gray-500 mt-1">管理所有处理任务的状态与进度</p>
        </div>
        <button class="btn" onclick="App.switchModule('video-import')"><i class="fas fa-plus"></i>新建任务</button>
      </div>
      <div id="tasks-table" class="card">
        <table class="data-table">
          <thead>
            <tr>
              <th>任务ID</th><th>类型</th><th>状态</th><th>阶段</th><th>进度</th><th>创建时间</th>
            </tr>
          </thead>
          <tbody id="tasks-tbody">
            <tr><td colspan="6" class="empty"><i class="fas fa-spinner spin"></i>加载中…</td></tr>
          </tbody>
        </table>
      </div>
    `;
    setTimeout(async () => {
      try {
        const r = await API.listTasks({ limit: 100 });
        if (r.tasks.length === 0) {
          Utils.setHTML('tasks-tbody', `<tr><td colspan="6" class="empty"><i class="fas fa-inbox"></i>暂无任务 · 从「视频接入」开始</td></tr>`);
          return;
        }
        Utils.setHTML('tasks-tbody', r.tasks.map(t => `
          <tr>
            <td class="text-mono text-brand-blue">${t.id.slice(0, 16)}</td>
            <td><span class="tag">${t.type}</span></td>
            <td><span class="status-badge ${t.status}">${t.status}</span></td>
            <td>${t.current_stage || '-'}</td>
            <td>
              <div class="row" style="gap:8px;">
                <div class="progress-bar" style="width:120px;"><div class="progress-bar-fill" style="width:${(t.progress * 100).toFixed(0)}%"></div></div>
                <span class="text-xs text-muted">${(t.progress * 100).toFixed(0)}%</span>
              </div>
            </td>
            <td class="text-muted">${Utils.formatDate(t.created_at)}</td>
          </tr>
        `).join(''));
      } catch (e) {
        Utils.setHTML('tasks-tbody', `<tr><td colspan="6" class="empty text-brand-red">加载失败: ${e.message}</td></tr>`);
      }
    }, 50);
    return root;
  }
};
