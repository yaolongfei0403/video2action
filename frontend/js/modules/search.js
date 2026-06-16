/* Module 10: Semantic Search - 语义检索 */
const Search = {
  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-5">
        <div>
          <h2 class="text-xl font-semibold text-white">语义检索</h2>
          <p class="text-[12px] text-gray-500 mt-1">基于 Qwen3-Embedding + Weaviate 的纯文本向量检索</p>
        </div>
        <div class="row" style="gap:8px; font-size:10px; color:#9ca3af;">
          <span class="w-1.5 h-1.5 rounded-full bg-brand-green pulse-dot"></span>
          <span>向量库在线</span>
        </div>
      </div>
      <div class="card mb-5">
        <div class="row" style="gap:8px;">
          <i class="fas fa-search text-gray-500"></i>
          <input type="text" id="search-query" class="input" placeholder="用自然语言描述你想找的动作…" value="扣篮动作，跳跃后单手入框" style="flex:1;">
          <button class="btn btn-primary" onclick="Search.run()">
            <i class="fas fa-search"></i>搜索
          </button>
        </div>
        <div class="row" style="gap:8px; margin-top:8px; flex-wrap:wrap; font-size:11px;">
          <span class="text-muted">热门：</span>
          <span class="text-brand-blue cursor-pointer" onclick="document.getElementById('search-query').value='扣篮跳跃'">扣篮</span>
          <span class="text-brand-blue cursor-pointer" onclick="document.getElementById('search-query').value='投篮动作'">投篮</span>
          <span class="text-brand-blue cursor-pointer" onclick="document.getElementById('search-query').value='转身过人'">转身</span>
          <span class="text-brand-blue cursor-pointer" onclick="document.getElementById('search-query').value='防守滑步'">防守</span>
        </div>
      </div>
      <div class="module-grid" style="grid-template-columns: 2fr 1fr; gap:16px;">
        <div>
          <div class="row" style="justify-content:space-between; margin-bottom:12px;">
            <span class="text-sm text-muted">搜索结果 <span id="result-count" class="text-white">0</span></span>
            <span id="search-time" class="text-xs text-muted">—</span>
          </div>
          <div id="search-results" class="col">
            <div class="empty"><i class="fas fa-search"></i>输入查询开始检索</div>
          </div>
        </div>
        <div class="card">
          <h3 class="card-title">检索详情</h3>
          <div class="col text-xs" style="gap:8px;">
            <div class="card-title" style="font-size:11px;">查询语句</div>
            <div id="detail-query" class="text-muted">—</div>
            <div class="card-title" style="font-size:11px;">统计</div>
            <div class="row"><span class="text-muted">匹配数</span><span id="detail-count" class="text-white text-mono">—</span></div>
            <div class="row"><span class="text-muted">耗时</span><span id="detail-time" class="text-brand-green text-mono">—</span></div>
          </div>
        </div>
      </div>
    `;
    return root;
  },
  async run() {
    const q = document.getElementById('search-query').value.trim();
    if (!q) { Utils.toast('请输入查询', 'error'); return; }
    Utils.toast('检索中…', 'info', 1200);
    try {
      const r = await Utils.safe(() => API.searchText({ query: q, top_k: 10 }), '检索失败');
      Utils.setText('result-count', r.total);
      Utils.setText('search-time', `${r.query_time_ms.toFixed(1)} ms`);
      Utils.setText('detail-query', `"${r.query}"`);
      Utils.setText('detail-count', r.total);
      Utils.setText('detail-time', `${r.query_time_ms.toFixed(1)} ms`);
      const el = document.getElementById('search-results');
      if (r.results.length === 0) {
        el.innerHTML = '<div class="empty">无匹配结果</div>';
        return;
      }
      el.innerHTML = r.results.map(h => `
        <div class="card search-result">
          <div class="row" style="gap:16px;">
            <div style="background: linear-gradient(135deg, rgba(59,130,246,0.3), rgba(139,92,246,0.3)); width:160px; height:96px; border-radius:8px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
              <i class="fas fa-play text-2xl text-white/50"></i>
            </div>
            <div class="flex-1 min-w-0">
              <div class="row" style="justify-content:space-between;">
                <div class="text-sm font-semibold text-white">${h.payload.summary?.slice(0, 30) || h.payload.keywords || h.id.slice(0, 12)}</div>
                <div class="row" style="gap:4px; font-size:10px;">
                  <span class="text-brand-blue text-mono">${(h.score * 100).toFixed(0)}%</span>
                  <div class="progress-bar" style="width:48px;"><div class="progress-bar-fill" style="width:${(h.score * 100).toFixed(0)}%"></div></div>
                </div>
              </div>
              <p class="text-xs text-muted" style="margin:6px 0; line-height:1.4;">${h.payload.detail?.slice(0, 80) || h.payload.summary || '—'}</p>
              <div class="row" style="gap:8px; font-size:10px; color:#9ca3af;">
                <span><i class="fas fa-clock"></i> ${Utils.formatTime(h.payload.duration || 0)}</span>
                <span class="text-brand-orange"><i class="fas fa-star"></i> ${h.payload.quality_grade || 'B'} 级</span>
                <span><i class="fas fa-tag"></i> ${h.payload.keywords || '—'}</span>
              </div>
            </div>
          </div>
        </div>
      `).join('');
    } catch {}
  },
};
