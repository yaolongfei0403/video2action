/* Module 11: Completed - 入库完成 */
const Completed = {
  async render() {
    const root = document.createElement('div');
    const t = State.get('currentTask');
    root.innerHTML = `
      <div class="mb-4">
        <h2 class="text-xl font-semibold text-white">入库完成</h2>
        <p class="text-[12px] text-gray-500 mt-1">4D 动作资产已成功入库，可供语义检索和引用</p>
      </div>
      <div class="card" style="text-align:center; padding:48px; position:relative; overflow:hidden;">
        <div style="position:absolute; top:0; left:0; right:0; height:4px; background:linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899);"></div>
        <div style="width:96px; height:96px; background:linear-gradient(135deg, rgba(16,185,129,0.2), rgba(6,182,212,0.2)); border-radius:50%; display:flex; align-items:center; justify-content:center; margin:0 auto 20px;">
          <i class="fas fa-check-circle text-brand-green" style="font-size:40px;"></i>
        </div>
        <h3 class="text-2xl font-bold text-white mb-2">任务完成!</h3>
        <p class="text-[13px] text-gray-400 mb-8">视频已成功处理并入库，渲染视频已存储至对象存储</p>
        <div id="completion-stats" class="module-grid" style="grid-template-columns: repeat(4, 1fr); gap:16px; max-width:600px; margin:0 auto 32px;">
          <div class="metric-card"><div class="label">渲染视频</div><div class="value" id="stat-videos">-</div></div>
          <div class="metric-card"><div class="label">语义标签</div><div class="value" id="stat-tags">-</div></div>
          <div class="metric-card"><div class="label">向量记录</div><div class="value" id="stat-vectors">-</div></div>
          <div class="metric-card"><div class="label">输出大小</div><div class="value" id="stat-size">-</div></div>
        </div>
        <div class="row" style="justify-content:center; gap:12px;">
          <button class="btn btn-primary" onclick="App.switchModule('semantic-search')">
            <i class="fas fa-search"></i>前往语义检索
          </button>
          <button class="btn" onclick="App.switchModule('asset-library')">
            <i class="fas fa-database"></i>查看资产库
          </button>
          <a id="download-link" class="btn" style="text-decoration:none; display:none;" href="#" download>
            <i class="fas fa-download"></i>下载渲染视频
          </a>
        </div>
      </div>
    `;
    if (t && t.id) {
      try {
        const r = await API.getCompletion(t.id);
        Utils.setText('stat-videos', r.rendered_videos || 0);
        Utils.setText('stat-tags', r.tags || 0);
        Utils.setText('stat-vectors', r.vector_records || 0);
        Utils.setHTML('stat-size', `${(r.output_size_mb || 0).toFixed(1)}<span style="font-size:12px; color:#6b7280;">MB</span>`);
        if (r.clip && r.clip.rendered_video_url) {
          const link = document.getElementById('download-link');
          link.href = r.clip.rendered_video_url;
          link.style.display = '';
        }
      } catch (e) {
        console.warn('completion stats failed:', e.message);
      }
    }
    return root;
  },
};
