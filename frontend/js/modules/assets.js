/* Module 9: Asset Library - 资产库 */
const Assets = {
  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-5">
        <div>
          <h2 class="text-xl font-semibold text-white">动作资产库</h2>
          <p class="text-[12px] text-gray-500 mt-1">已入库的 4D 动作资产</p>
        </div>
        <div class="row" style="gap:8px;">
          <select id="asset-grade-filter" class="select" onchange="Assets.load()">
            <option value="">全部等级</option>
            <option value="A">仅 A 级</option>
            <option value="B">B 级</option>
            <option value="C">C 级</option>
          </select>
          <button class="btn" onclick="App.switchModule('semantic-search')">
            <i class="fas fa-search"></i>语义检索
          </button>
        </div>
      </div>
      <div id="assets-grid" class="module-grid" style="grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:14px;">
        ${[1,2,3,4,5,6].map(() => '<div class="card" style="height:200px;"></div>').join('')}
      </div>
    `;
    setTimeout(() => this.load(), 50);
    return root;
  },
  async load() {
    const grid = document.getElementById('assets-grid');
    if (!grid) return;
    const grade = document.getElementById('asset-grade-filter')?.value;
    try {
      const r = await API.listAssets({ quality_grades: grade, limit: 50 });
      if (r.assets.length === 0) {
        grid.innerHTML = '<div class="empty" style="grid-column:1/-1;"><i class="fas fa-database"></i>资产库为空 · 从「标签生成」完成入库</div>';
        return;
      }
      grid.innerHTML = r.assets.map(a => `
        <div class="card asset-card">
          <div style="background: linear-gradient(135deg, rgba(59,130,246,0.3), rgba(139,92,246,0.3)); height:120px; border-radius:8px; display:flex; align-items:center; justify-content:center; position:relative;">
            <i class="fas fa-play text-3xl text-white/50"></i>
            <span class="status-badge completed" style="position:absolute; top:8px; left:8px;">入库</span>
            <span class="status-badge ${a.quality_grade === 'A' ? 'completed' : 'pending'}" style="position:absolute; top:8px; right:8px;">${a.quality_grade} 级</span>
            <span style="position:absolute; bottom:8px; right:8px; font-size:10px; background:rgba(0,0,0,0.7); padding:2px 6px; border-radius:3px; font-family:monospace;">${Utils.formatTime(a.duration)}</span>
          </div>
          <div style="padding:8px 0 0;">
            <div class="text-sm text-white truncate">${a.summary.slice(0, 20) || a.keywords || a.id}</div>
            <div class="text-xs text-muted" style="margin-top:4px;">${a.keywords || '—'}</div>
            <div class="text-xs text-muted" style="margin-top:4px;">${Utils.formatDate(a.created_at)}</div>
          </div>
        </div>
      `).join('');
    } catch (e) {
      grid.innerHTML = `<div class="empty text-brand-red" style="grid-column:1/-1;">${e.message}</div>`;
    }
  },
};
