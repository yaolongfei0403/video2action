/* Module 8: Tagging - VLM 标签生成 */
const Tagging = {
  async render() {
    const root = document.createElement('div');
    const clip = State.get('currentClip');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-4">
        <div>
          <h2 class="text-xl font-semibold text-white">标签生成 · VLM 语义化</h2>
          <p class="text-[12px] text-gray-500 mt-1">基于 4D 重建后的视频 + 关键词 · 由 Qwen-VL 生成动作描述</p>
        </div>
        <div class="row" style="gap:8px;">
          <input type="text" id="tag-keywords" class="input" placeholder="关键词 (如: 篮球, 扣篮, 跳跃)" value="篮球, 扣篮, 跳跃" style="width:240px;">
          <button class="btn btn-primary" onclick="Tagging.runVLM()">
            <i class="fas fa-brain"></i>生成描述
          </button>
        </div>
      </div>
      <div class="module-grid" style="grid-template-columns: 1fr 2fr 1fr; gap:16px;">
        <div class="card">
          <h3 class="card-title">原视频</h3>
          <div style="background:#000; border-radius:8px; height:200px; display:flex; align-items:center; justify-content:center;">
            <i class="fas fa-film text-3xl text-gray-600"></i>
          </div>
          <div class="text-xs text-muted" style="margin-top:8px;">当前: ${clip ? clip.id : '未选择'}</div>
        </div>
        <div class="card">
          <h3 class="card-title">VLM 自动描述 (Qwen-VL)</h3>
          <div id="vlm-output" class="col" style="gap:12px;">
            <div class="card-title" style="font-size:11px;">动作概述</div>
            <textarea id="vlm-summary" class="textarea" rows="2" placeholder="点击「生成描述」开始…"></textarea>
            <div class="card-title" style="font-size:11px;">动作细节</div>
            <textarea id="vlm-detail" class="textarea" rows="3"></textarea>
            <div class="card-title" style="font-size:11px;">动作节奏</div>
            <textarea id="vlm-rhythm" class="textarea" rows="2"></textarea>
            <div class="card-title" style="font-size:11px;">适用场景</div>
            <textarea id="vlm-use-case" class="textarea" rows="2"></textarea>
          </div>
        </div>
        <div class="card">
          <h3 class="card-title">标签编辑</h3>
          <div class="col" style="gap:8px;">
            <label class="text-xs text-muted">质量等级</label>
            <select id="tag-grade" class="select">
              <option value="A">A 级</option>
              <option value="B" selected>B 级</option>
              <option value="C">C 级</option>
            </select>
            <label class="text-xs text-muted">人工补充标签</label>
            <input type="text" id="tag-manual" class="input" placeholder="逗号分隔">
          </div>
          <div class="col" style="margin-top:16px; gap:8px;">
            <button class="btn btn-primary btn-block" onclick="Tagging.save()">
              <i class="fas fa-save"></i>保存标签
            </button>
            <button class="btn btn-success btn-block" onclick="Tagging.saveAndIndex()">
              <i class="fas fa-database"></i>保存并入库
            </button>
          </div>
        </div>
      </div>
    `;
    return root;
  },
  async runVLM() {
    const clip = State.get('currentClip');
    if (!clip) { Utils.toast('请先选择 Clip', 'error'); return; }
    const keywords = document.getElementById('tag-keywords')?.value || '';
    Utils.toast('调用 VLM 生成描述…', 'info');
    try {
      const r = await Utils.safe(() => API.vlmDescribe({ clip_id: clip.id, keywords }), 'VLM 失败');
      Utils.setText('vlm-summary', r.description.summary || '');
      Utils.setText('vlm-detail', r.description.detail || '');
      Utils.setText('vlm-rhythm', r.description.rhythm || '');
      Utils.setText('vlm-use-case', r.description.use_case || '');
      Utils.toast(`描述生成完成 (模式: ${r.mode})`, 'success');
    } catch {}
  },
  async save() {
    const clip = State.get('currentClip');
    if (!clip) { Utils.toast('请先选择 Clip', 'error'); return; }
    const $ = (id) => document.getElementById(id)?.value || '';
    try {
      await Utils.safe(() => API.saveTags({
        clip_id: clip.id,
        keywords: $('tag-keywords'),
        summary: $('vlm-summary'),
        detail: $('vlm-detail'),
        rhythm: $('vlm-rhythm'),
        use_case: $('vlm-use-case'),
        manual_tags: $('tag-manual').split(',').map(s => s.trim()).filter(Boolean),
        quality_grade: $('tag-grade') || 'B',
      }), '保存失败');
      Utils.toast('标签已保存', 'success');
    } catch {}
  },
  async saveAndIndex() {
    await this.save();
    const clip = State.get('currentClip');
    if (!clip) return;
    try {
      const r = await Utils.safe(() => API.indexClip(clip.id), '入库失败');
      Utils.toast(`已入库! 向量库: ${r.vector_count} 条`, 'success');
      setTimeout(() => App.switchModule('completed'), 800);
    } catch {}
  },
};
