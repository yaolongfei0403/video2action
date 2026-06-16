/* Module 7: 4D Studio - 4D 重建 (从队列自动读取处理)
   队列来源: status=annotated 的 clip
*/
const FourD = {
  _pollHandle: null,
  _currentClip: null,

  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-4">
        <div>
          <h2 class="text-xl font-semibold text-white">4D Studio · 队列自动处理</h2>
          <p class="text-[12px] text-gray-500 mt-1">从 Target Studio 入队的 clip 列表 · 点「处理下一个」自动开始 4D 重建</p>
        </div>
        <div class="row" style="gap:8px;">
          <button class="btn btn-sm" onclick="FourD.loadQueue()">
            <i class="fas fa-sync"></i>刷新队列
          </button>
        </div>
      </div>
      <div class="module-grid" style="grid-template-columns: 1fr 2fr 1fr; gap:16px;">
        <!-- 左: 队列 -->
        <div class="card">
          <h3 class="card-title">4D 处理队列 <span class="text-xs text-muted" id="fourd-queue-count" style="font-weight:normal;"></span></h3>
          <div id="fourd-queue" class="col scroll-y" style="max-height:600px;">
            <div class="empty"><i class="fas fa-spinner spin"></i>加载队列中…</div>
          </div>
          <hr style="border-color:rgba(61,79,111,0.4); margin:12px 0;">
          <button class="btn btn-primary btn-block" id="fourd-process-btn" onclick="FourD.processNext()">
            <i class="fas fa-play"></i>处理下一个
          </button>
          <button class="btn btn-block" style="margin-top:8px;" id="fourd-auto-btn" onclick="FourD.toggleAuto()">
            <i class="fas fa-robot"></i><span id="fourd-auto-text">开启自动模式</span>
          </button>
        </div>

        <!-- 中: 3D 预览 -->
        <div class="card">
          <h3 class="card-title">当前任务 <span id="fourd-current-clip" class="text-xs text-muted" style="font-weight:normal;"></span></h3>
          <div class="mesh-viewer" id="fourd-3d-viewer" style="background: radial-gradient(ellipse at center, #0f1a2e 0%, #060912 100%); border-radius:12px; min-height:480px; display:flex; align-items:center; justify-content:center; position:relative;">
            <div class="empty" id="fourd-3d-empty" style="color:#6b7280;">
              <i class="fas fa-cube"></i>
              <div>点「处理下一个」开始</div>
            </div>
            <video id="fourd-render-video" controls style="width:100%; max-height:480px; display:none;"></video>
          </div>
          <div class="row" style="margin-top:12px; gap:8px;">
            <button class="btn btn-sm" onclick="FourD.loadQueue()">
              <i class="fas fa-list"></i>查看队列
            </button>
            <a id="fourd-download-link" class="btn btn-sm" style="display:none;" href="#" download>
              <i class="fas fa-download"></i>下载渲染视频
            </a>
          </div>
        </div>

        <!-- 右: 进度 + 输出 -->
        <div class="card">
          <h3 class="card-title">处理进度</h3>
          <div class="col text-xs" style="gap:8px;">
            <div class="row"><span class="text-muted">Mesh 准备</span><span id="step-1">—</span></div>
            <div class="row"><span class="text-muted">3D 估计</span><span id="step-2">—</span></div>
            <div class="row"><span class="text-muted">SMPL 拟合</span><span id="step-3">—</span></div>
            <div class="row"><span class="text-muted">时序优化</span><span id="step-4">—</span></div>
            <div class="row"><span class="text-muted">渲染输出</span><span id="step-5">—</span></div>
          </div>
          <hr style="border-color:rgba(61,79,111,0.4); margin:12px 0;">
          <h3 class="card-title" style="font-size:12px;">最近输出</h3>
          <div id="fourd-outputs" class="col text-xs">
            <div class="text-muted">—</div>
          </div>
        </div>
      </div>
    `;
    setTimeout(() => {
      this.loadQueue();
      this.maybeStartAuto();
    }, 50);
    return root;
  },

  async loadQueue() {
    const el = document.getElementById('fourd-queue');
    if (!el) return;
    el.innerHTML = '<div class="empty"><i class="fas fa-spinner spin"></i>加载中…</div>';
    try {
      const r = await API.clipQueue();
      Utils.setText('fourd-queue-count', `共 ${r.total} 个`);
      if (r.total === 0) {
        el.innerHTML = `
          <div class="empty">
            <i class="fas fa-inbox"></i>
            <div>队列为空</div>
          </div>
          <p class="text-xs text-muted text-center mt-2">到 Target Studio 选帧后确认入队</p>
        `;
        return;
      }
      el.innerHTML = r.queue.map((c, i) => `
        <div class="list-item ${this._currentClip?.clip_id === c.clip_id ? 'selected' : ''}"
             data-clip-id="${c.clip_id}"
             onclick="FourD.selectQueueItem('${c.clip_id}')">
          <div class="w-9 h-6 rounded bg-brand-blue/30 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-cube text-white/60 text-[8px]"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-xs text-white text-mono">#${i + 1} ${c.clip_id.slice(0, 8)}</div>
            <div class="text-xxs text-muted">${c.duration.toFixed(1)}s · ${c.annotation_count} 标注</div>
          </div>
          <span class="text-xxs text-brand-green font-mono">${c.obj_ids.length} obj</span>
        </div>
      `).join('');
    } catch (e) {
      el.innerHTML = `<div class="empty text-brand-red">${e.message}</div>`;
    }
  },

  selectQueueItem(clipId) {
    this._currentClip = { clip_id: clipId };
    this.loadQueue();
  },

  // 核心: 处理下一个
  async processNext() {
    this.setStep(1, 'processing', '排队取任务');
    try {
      // 先问后端: 队列里有吗?
      const next = await API.processNext4D();
      if (next.status === 'idle') {
        Utils.toast('队列为空 · 到 Target Studio 添加任务', 'info');
        this.setStep(1, 'completed', '✓ 队列空');
        return;
      }
      const info = next.info;
      this._currentClip = { clip_id: info.clip_id, output_video: null };
      Utils.setText('fourd-current-clip', `· ${info.clip_id.slice(0, 8)} (${info.start_sec.toFixed(1)}s→${info.end_sec.toFixed(1)}s)`);
      Utils.toast(`开始处理: ${info.clip_id.slice(0, 8)}`, 'info');

      this.setStep(2, 'processing', '4D 重建中');
      const r = await Utils.safe(() => API.reconstruct4D({ clip_id: info.clip_id }), '4D 重建失败');
      this.setStep(3, 'completed', '✓');
      this.setStep(4, 'completed', '✓');
      this.setStep(5, 'completed', '✓');

      // 显示渲染视频
      const videoEl = document.getElementById('fourd-render-video');
      const empty = document.getElementById('fourd-3d-empty');
      if (videoEl && r.output_video_url) {
        videoEl.src = r.output_video_url;
        videoEl.style.display = 'block';
        if (empty) empty.style.display = 'none';
      }

      Utils.setHTML('fourd-outputs', `
        <div class="list-item">
          <i class="fas fa-file-video text-brand-blue"></i>
          <a href="${r.output_video_url}" target="_blank" class="text-brand-blue text-xs truncate">${r.output_video_url.split('/').pop()}</a>
        </div>
        <div class="text-xxs text-muted">${r.total_frames} 帧 · 模式: ${r.mode}</div>
      `);
      const link = document.getElementById('fourd-download-link');
      if (link) {
        link.href = r.output_video_url;
        link.style.display = '';
      }
      Utils.toast(`✓ 4D 完成 · ${r.total_frames} 帧 · 自动模式: 继续下一个`, 'success', 2000);

      // 刷新队列 (该 clip 已移出)
      this.loadQueue();
      // 自动模式 → 1 秒后继续
      if (this._autoMode) {
        setTimeout(() => this.processNext(), 1500);
      }
    } catch (e) {
      this.setStep(2, 'failed', '✗');
      console.error(e);
    }
  },

  toggleAuto() {
    this._autoMode = !this._autoMode;
    const txt = document.getElementById('fourd-auto-text');
    if (txt) txt.textContent = this._autoMode ? '关闭自动模式' : '开启自动模式';
    Utils.toast(this._autoMode ? '✓ 自动模式已开启 (处理完一个继续下一个)' : '已切换手动模式', 'info');
    if (this._autoMode) this.processNext();
  },

  maybeStartAuto() {
    // 进入页面时如果队列非空且未在处理，提示可开启自动模式
    API.clipQueue().then(r => {
      if (r.total > 0) {
        Utils.toast(`队列有 ${r.total} 个待处理 clip · 点「开启自动模式」连续处理`, 'info', 3000);
      }
    }).catch(() => {});
  },

  setStep(n, type, text) {
    Utils.setText(`step-${n}`, text);
    const el = document.getElementById(`step-${n}`);
    if (!el) return;
    el.className = type === 'completed' ? 'text-brand-green' : type === 'failed' ? 'text-brand-red' : 'text-brand-blue';
  },
};
