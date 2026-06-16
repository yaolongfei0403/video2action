/* Module 4: Rough Cut - 粗切工作台 (改为初筛界面)
   上传后粗切已自动在后台跑完，此处只做通过/拒绝的初筛。
*/
const RoughCut = {
  _player: null,
  _currentVideo: null,         // 当前选中的视频
  _queueData: null,             // 队列数据 (全部视频的粗切状态)
  _candidatesData: null,        // 当前视频的候选
  _currentCandidate: null,      // 当前在右侧选中的候选（用于高亮 + 左侧 seek）
  _pollHandle: null,             // 处理中轮询

  async render() {
    const root = document.createElement('div');
    const initialVideo = State.get('currentVideo');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-4">
        <div>
          <h2 class="text-xl font-semibold text-white">粗切工作台 · 初筛</h2>
          <p class="text-[12px] text-gray-500 mt-1">视频上传后自动入队粗切 · 在此通过 / 拒绝候选片段，通过的自动进入精切</p>
        </div>
        <div class="row" style="gap:8px;">
          <button class="btn btn-sm" onclick="RoughCut.loadQueue()">
            <i class="fas fa-sync"></i>刷新队列
          </button>
        </div>
      </div>

      <!-- 队列概览 (顶部) -->
      <div class="card mb-4">
        <h3 class="card-title">自动粗切队列 <span class="text-xs text-muted" style="font-weight:normal;">(上传即入队，后台自动执行)</span></h3>
        <div id="rc-queue" class="col scroll-y" style="max-height:140px; overflow-y:auto;">
          <div class="empty"><i class="fas fa-spinner spin"></i>加载队列中…</div>
        </div>
      </div>

      <div class="module-grid" style="grid-template-columns: 2fr 1fr; gap:16px;">
        <!-- 左: 视频 + 时间轴 -->
        <div class="card">
          <h3 class="card-title">视频预览 <span id="rc-current-name" class="text-xs text-muted" style="font-weight:normal;"></span></h3>
          <div style="background:#000; border-radius:12px; overflow:hidden; min-height:320px; display:flex; align-items:center; justify-content:center; position:relative;">
            <video id="rc-player" style="width:100%; max-height:480px; display:none;" controls preload="metadata" playsinline></video>
            <div id="rc-empty" class="empty" style="color:#6b7280;">
              <i class="fas fa-film"></i>
              <div>从下方队列选择一段视频开始初筛</div>
            </div>
          </div>
          <div class="row" style="gap:12px; margin-top:12px;">
            <span id="rc-time" class="text-xs text-mono text-muted">00:00 / 00:00</span>
            <button class="btn btn-sm" id="rc-play" onclick="RoughCut.togglePlay()"><i class="fas fa-play"></i>播放</button>
          </div>
          <h3 class="card-title" style="margin-top:16px;">时间轴 (绿色:高分待通过 · 橙色:低分 · 紫色:已通过)</h3>
          <div class="timeline-bar" id="rc-timeline">
            <div class="timeline-playhead" id="rc-playhead" style="left:0%"></div>
          </div>
        </div>

        <!-- 右: 候选 (初筛) -->
        <div class="card">
          <h3 class="card-title">候选 · 初筛 <span class="text-xs text-muted" id="rc-count-badge" style="font-weight:normal;"></span></h3>
          <div id="rc-candidates" class="col scroll-y" style="max-height:480px;">
            <div class="empty"><i class="fas fa-cut"></i>选择视频查看候选</div>
          </div>
        </div>
      </div>
    `;
    setTimeout(() => {
      this.bindPlayer();
      this.loadQueue(initialVideo?.id);
    }, 50);
    return root;
  },

  bindPlayer() {
    this._player = document.getElementById('rc-player');
    if (!this._player) return;
    this._player.addEventListener('timeupdate', () => {
      if (!this._player) return;
      const t = this._player.currentTime;
      const dur = this._currentVideo?.duration || 0;
      Utils.setText('rc-time', `${Utils.formatTime(t)} / ${Utils.formatTime(dur)}`);
      const pct = dur > 0 ? (t / dur * 100) : 0;
      const head = document.getElementById('rc-playhead');
      if (head) head.style.left = pct + '%';
    });
    this._player.addEventListener('play', () => Utils.setHTML('rc-play', '<i class="fas fa-pause"></i>暂停'));
    this._player.addEventListener('pause', () => Utils.setHTML('rc-play', '<i class="fas fa-play"></i>播放'));
    this._player.addEventListener('ended', () => Utils.setHTML('rc-play', '<i class="fas fa-play"></i>播放'));
  },

  togglePlay() {
    if (!this._player) return;
    if (this._player.paused) Utils.safePlay(this._player);
    else this._player.pause();
  },

  seekTo(sec) {
    if (this._player) this._player.currentTime = sec;
  },

  // 加载队列 + 自动选中第一个有候选的视频
  async loadQueue(autoSelectId = null) {
    const el = document.getElementById('rc-queue');
    if (!el) return;
    try {
      // GET /api/rough-cut/queue (api.js 中无对应方法，直接 fetch)
      const resp = await fetch('/api/rough-cut/queue');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const r = await resp.json();
      this._queueData = r.queue || [];
      this.renderQueue();
      // 自动选中
      let target = autoSelectId;
      if (!target) {
        const done = this._queueData.find(q => q.status === 'done' && q.candidates > 0);
        target = done?.video_id || this._queueData[0]?.video_id;
      }
      if (target) this.selectVideo(target);
      // 如果有 processing 状态的，启动轮询
      this.maybeStartPolling();
    } catch (e) {
      el.innerHTML = `<div class="empty text-brand-red">${e.message}</div>`;
    }
  },

  renderQueue() {
    const el = document.getElementById('rc-queue');
    if (!el || !this._queueData) return;
    if (this._queueData.length === 0) {
      el.innerHTML = '<div class="empty">暂无视频 · 先到「视频接入」上传</div>';
      return;
    }
    el.innerHTML = `
      <div class="row" style="gap:8px; flex-wrap:wrap;">
        ${this._queueData.map(q => {
          const color = {
            'processing': 'border-brand-blue/40 bg-brand-blue/10',
            'done': 'border-brand-green/40 bg-brand-green/10',
            'failed': 'border-brand-red/40 bg-brand-red/10',
            'pending': 'border-dark-500/40 bg-dark-700/40',
          }[q.status] || '';
          const icon = {
            'processing': 'spinner spin',
            'done': 'check',
            'failed': 'times',
            'pending': 'clock',
          }[q.status] || 'circle';
          return `
            <div class="list-item ${this._currentVideo?.id === q.video_id ? 'selected' : ''} ${color}"
                 style="border-width:1px; padding:6px 10px; cursor:pointer;"
                 onclick="RoughCut.selectVideo('${q.video_id}')">
              <i class="fas fa-${icon} text-brand-${q.status === 'failed' ? 'red' : q.status === 'done' ? 'green' : 'blue'}"></i>
              <div class="flex-1 min-w-0">
                <div class="text-sm text-white truncate">${q.name}</div>
                <div class="text-xs text-muted">
                  ${q.status === 'processing' ? `<span class="text-brand-blue">粗切中 ${(q.progress*100).toFixed(0)}%</span>` :
                    q.status === 'done' ? `<span class="text-brand-green">${q.candidates} 候选</span> · ${q.approved} 通过` :
                    q.status === 'failed' ? '<span class="text-brand-red">失败</span>' :
                    '<span class="text-muted">等待中</span>'}
                </div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  // 选中一个视频，渲染其候选
  async selectVideo(videoId) {
    this._currentVideo = { id: videoId };
    // 切换视频 → 清掉旧候选选择
    this._currentCandidate = null;
    try {
      const v = await API.getVideo(videoId);
      this._currentVideo = v;
      Utils.setText('rc-current-name', `· ${v.guid || v.id}`);
      // 加载播放器
      const player = document.getElementById('rc-player');
      const empty = document.getElementById('rc-empty');
      if (player && v.url) {
        // 切换 src 前先 reset，避免 play() 跨 src 串扰
        Utils.resetPlayer(player);
        player.src = v.url;
        player.style.display = 'block';
        if (empty) empty.style.display = 'none';
        this.bindPlayer();
        player.addEventListener('error', () => {
          Utils.toast(`视频加载失败: ${v.url}`, 'error');
        }, { once: true });
      }
      // 加载候选
      const r = await API.listCandidates(videoId);
      this._candidatesData = r.candidates;
      this.renderCandidates(r.candidates);
      this.renderTimeline(r.candidates, v.duration);
      // 刷新队列高亮
      this.renderQueue();
    } catch (e) {
      Utils.toast(`加载视频失败: ${e.message}`, 'error');
    }
  },

  // 点击候选 → 切换左侧播放器到该候选的 start_sec，并自动播放
  selectCandidate(candId, ev) {
    // 点中按钮（通过/拒绝/去精切等）时不触发选择 - 让按钮自己处理
    if (ev && ev.target && ev.target.closest('button')) return;
    const c = (this._candidatesData || []).find(x => x.id === candId);
    if (!c) return;
    this._currentCandidate = c;
    // 同步高亮：列表 + 时间轴
    this.renderCandidates(this._candidatesData || []);
    this.renderTimeline(this._candidatesData || [], this._currentVideo?.duration);
    // 选中即播放：seek 到 start_sec 并自动播到 end_sec 后暂停
    if (this._player) {
      try {
        // 取消可能残留的旧 timeupdate 监听，避免上一段的暂停逻辑误触发
        if (this._stopTU) {
          this._player.removeEventListener('timeupdate', this._stopTU);
          this._stopTU = null;
        }
        this._player.currentTime = c.start_sec;
        Utils.safePlay(this._player);
        const end = c.end_sec;
        const onTU = () => {
          if (!this._player || this._player.currentTime >= end) {
            this._player.pause();
            this._player.removeEventListener('timeupdate', onTU);
            this._stopTU = null;
          }
        };
        this._stopTU = onTU;
        this._player.addEventListener('timeupdate', onTU);
      } catch (e) { /* ignore */ }
    }
  },

  // 处理中自动轮询
  maybeStartPolling() {
    if (this._pollHandle) clearInterval(this._pollHandle);
    const processing = this._queueData?.some(q => q.status === 'processing');
    if (!processing) return;
    this._pollHandle = setInterval(() => this.loadQueue(this._currentVideo?.id), 2000);
  },

  renderCandidates(cands) {
    const el = document.getElementById('rc-candidates');
    if (!el) return;
    const pending = cands.filter(c => !c.approved && !c.rejected);
    const approved = cands.filter(c => c.approved);
    const rejected = cands.filter(c => c.rejected);
    Utils.setText('rc-count-badge', `待筛 ${pending.length} · 通过 ${approved.length} · 拒绝 ${rejected.length}`);

    if (cands.length === 0) {
      el.innerHTML = '<div class="empty">该视频无候选</div>';
      return;
    }

    // 排序：pending → approved → rejected
    const sorted = [...pending, ...approved, ...rejected];
    el.innerHTML = sorted.map((c, i) => {
      const isApproved = c.approved;
      const isRejected = c.rejected;
      const isSelected = this._currentCandidate && this._currentCandidate.id === c.id;
      // 拒绝时：淡化文字 + 红色边框 + 删除线
      const stateClass = isRejected ? 'rc-rejected' : '';
      const iconClass = isApproved ? 'check' : (isRejected ? 'times' : 'play');
      const iconBg = isApproved
        ? 'bg-brand-purple/40'
        : (isRejected ? 'bg-brand-red/40' : 'bg-gradient-to-br from-brand-blue/30 to-brand-purple/30');
      return `
        <div class="list-item ${isApproved ? 'bg-success-light' : ''} ${stateClass} ${isSelected ? 'selected' : ''}" data-cand-id="${c.id}" style="cursor:pointer;" onclick="RoughCut.selectCandidate('${c.id}', event)">
          <div class="w-14 h-9 rounded ${iconBg} flex items-center justify-center flex-shrink-0">
            <i class="fas fa-${iconClass} ${isRejected ? 'text-brand-red' : 'text-white/60'} text-[8px]"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-white">
              ${isApproved ? '<span class="text-brand-green">✓</span> ' : ''}
              ${isRejected ? '<span class="rc-rejected-tag">已拒绝</span> ' : ''}
              ${Utils.formatTime(c.start_sec)} → ${Utils.formatTime(c.end_sec)}
              <span class="text-xs text-muted">· ${c.duration_sec.toFixed(1)}s</span>
            </div>
            <div class="text-xs ${c.score > 0.7 ? 'text-brand-green' : 'text-brand-orange'} font-mono">score=${c.score.toFixed(2)}</div>
          </div>
          <div class="row" style="gap:8px; flex-shrink:0;">
            ${isApproved ? `
              <button class="btn btn-success btn-lg" onclick="RoughCut.toFineCut('${c.id}', ${c.start_sec}, ${c.end_sec})" title="去精切">
                <i class="fas fa-cut"></i><span class="ml-1">精切</span>
              </button>
              <button class="btn btn-lg" onclick="RoughCut.approve('${c.id}', false)" title="撤销通过">
                <i class="fas fa-undo"></i><span class="ml-1">撤销</span>
              </button>
            ` : isRejected ? `
              <button class="btn btn-success btn-lg" onclick="RoughCut.approve('${c.id}', true)" title="改为通过">
                <i class="fas fa-check"></i><span class="ml-1">通过</span>
              </button>
              <button class="btn btn-lg" onclick="RoughCut.reject('${c.id}', false)" title="撤销拒绝">
                <i class="fas fa-undo"></i><span class="ml-1">撤销</span>
              </button>
            ` : `
              <button class="btn btn-success btn-lg" onclick="RoughCut.approve('${c.id}', true)" title="通过">
                <i class="fas fa-check"></i><span class="ml-1">通过</span>
              </button>
              <button class="btn btn-danger btn-lg" onclick="RoughCut.reject('${c.id}', true)" title="拒绝">
                <i class="fas fa-times"></i><span class="ml-1">拒绝</span>
              </button>
            `}
          </div>
        </div>
      `;
    }).join('');
  },

  renderTimeline(cands, totalSec) {
    const tl = document.getElementById('rc-timeline');
    if (!tl) return;
    const total = totalSec || 60;
    const selectedId = this._currentCandidate?.id;
    tl.innerHTML = cands.map(c => {
      const left = (c.start_sec / total * 100).toFixed(1);
      const width = ((c.end_sec - c.start_sec) / total * 100).toFixed(1);
      let color = c.score > 0.7 ? 'tl-green' : 'tl-orange';
      if (c.approved) color = 'tl-purple';
      if (c.rejected) color = 'tl-red';
      const isSelected = c.id === selectedId;
      return `<div class="timeline-seg ${color} ${isSelected ? 'tl-selected' : ''}" style="left:${left}%; width:${width}%; ${c.rejected ? 'opacity:0.45;' : ''}" title="${c.start_sec.toFixed(1)}s → ${c.end_sec.toFixed(1)}s score=${c.score.toFixed(2)}" onclick="RoughCut.selectCandidate('${c.id}', event)"></div>`;
    }).join('') + `<div class="timeline-playhead" id="rc-playhead" style="left:0%"></div>`;
  },

  previewSegment(start, end, candId) {
    if (!this._player) return;
    // 同步选中：让播放的候选也被高亮（列表 + 时间轴）
    if (candId) {
      const c = (this._candidatesData || []).find(x => x.id === candId);
      if (c) {
        this._currentCandidate = c;
        this.renderCandidates(this._candidatesData || []);
        this.renderTimeline(this._candidatesData || [], this._currentVideo?.duration);
      }
    }
    this._player.currentTime = start;
    Utils.safePlay(this._player);
    const onTU = () => {
      if (!this._player || this._player.currentTime >= end) {
        this._player.pause();
        this._player.removeEventListener('timeupdate', onTU);
      }
    };
    this._player.addEventListener('timeupdate', onTU);
  },

  // 初筛核心：通过/拒绝/撤销
  async approve(candidateId, isApproved) {
    try {
      await API.approveCandidate(candidateId, isApproved);
      // 局部更新候选列表（不重渲染整个）
      if (this._candidatesData) {
        const c = this._candidatesData.find(x => x.id === candidateId);
        if (c) {
          c.approved = isApproved;
          // 撤销通过时同步清掉 rejected（不应同时为 true）
          if (!isApproved) c.rejected = false;
        }
      }
      this.renderCandidates(this._candidatesData || []);
      this.renderTimeline(this._candidatesData || [], this._currentVideo?.duration);
      Utils.toast(isApproved ? '✓ 已通过' : '↩ 已撤销通过', isApproved ? 'success' : 'info', 1000);
    } catch (e) {
      Utils.toast(`操作失败: ${e.message}`, 'error');
    }
  },

  // 拒绝候选
  async reject(candidateId, isRejected = true) {
    try {
      await API.rejectCandidate(candidateId, isRejected);
      if (this._candidatesData) {
        const c = this._candidatesData.find(x => x.id === candidateId);
        if (c) {
          c.rejected = isRejected;
          // 拒绝时同步清掉 approved
          if (isRejected) c.approved = false;
        }
      }
      this.renderCandidates(this._candidatesData || []);
      this.renderTimeline(this._candidatesData || [], this._currentVideo?.duration);
      Utils.toast(isRejected ? '✗ 已拒绝' : '↩ 已撤销拒绝', isRejected ? 'info' : 'success', 1000);
    } catch (e) {
      Utils.toast(`操作失败: ${e.message}`, 'error');
    }
  },

  // 通过的候选 → 跳到精切台，自动填入 start/end
  toFineCut(candidateId, start, end) {
    State.set('pendingFineCut', { candidateId, start, end });
    Utils.toast('已选择该片段，前往精切工作台', 'success');
    setTimeout(() => App.switchModule('fine-cut'), 600);
  },
};
