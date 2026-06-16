/* Module 5: Fine Cut - 精切工作台
   右侧展示所有「已通过粗切、待精切」的候选（按 video 分组）。
   点击候选 → 加载到左侧编辑器 → 调整后 [✂ 执行精切]。
*/
const FineCut = {
  _player: null,
  _approvedGroups: null,  // [{video_id, video_name, video_url, candidates: [...]}]
  _currentCandidate: null, // 当前选中的候选
  _currentVideoId: null,   // 当前编辑的视频

  async render() {
    const root = document.createElement('div');
    const video = State.get('currentVideo');
    const pending = State.get('pendingFineCut') || { start: 0, end: 0 };
    const dur = video?.duration || 0;
    root.innerHTML = `
      <div class="flex items-end justify-between mb-4">
        <div>
          <h2 class="text-xl font-semibold text-white">精切工作台</h2>
          <p class="text-[12px] text-gray-500 mt-1">从右侧选择「已通过粗切」的候选 · 调整起止点后执行精切</p>
        </div>
        <button class="btn btn-sm" onclick="FineCut.loadApprovedCandidates()">
          <i class="fas fa-sync"></i>刷新列表
        </button>
      </div>
      <div class="module-grid" style="grid-template-columns: 2fr 1fr; gap:16px;">
        <!-- 左侧: 视频 + 编辑器 -->
        <div class="card">
          <h3 class="card-title">
            视频预览
            <span id="fc-current-name" class="text-xs text-muted" style="font-weight:normal;"></span>
            <span id="fc-candidate-badge" class="text-xs text-brand-green" style="font-weight:normal; margin-left:8px; display:none;">
              <i class="fas fa-check-circle"></i> 来自粗切候选
            </span>
          </h3>
          <div style="background:#000; border-radius:12px; overflow:hidden; min-height:320px; display:flex; align-items:center; justify-content:center; position:relative;">
            <video id="fc-player" style="width:100%; max-height:480px; display:none;" controls preload="metadata" playsinline></video>
            <div id="fc-empty" class="empty" style="color:#6b7280;">
              <i class="fas fa-hand-pointer"></i>
              <div>从右侧列表选择一段候选开始精切</div>
            </div>
          </div>
          <div class="row" style="gap:12px; margin-top:12px;">
            <span id="fc-time" class="text-xs text-mono text-muted">00:00 / 00:00</span>
            <button class="btn btn-sm" id="fc-play" onclick="FineCut.togglePlay()"><i class="fas fa-play"></i>播放</button>
          </div>
          <h3 class="card-title" style="margin-top:16px;">时间轴编辑器 <span class="text-xs text-muted" style="font-weight:normal;">· 拖拽紫色手柄调整起止点 · 点击空白跳转 · 中段拖动平移</span></h3>
          <div class="row" style="gap:12px; margin-bottom:12px;">
            <label class="text-xs text-muted">开始 (秒)</label>
            <input type="number" id="fc-start" class="input" value="${pending.start.toFixed(2)}" min="0" step="0.1" style="width:120px;">
            <label class="text-xs text-muted">结束 (秒)</label>
            <input type="number" id="fc-end" class="input" value="${pending.end.toFixed(2)}" min="0" step="0.1" style="width:120px;">
            <button class="btn btn-primary" onclick="FineCut.trim()">
              <i class="fas fa-cut"></i>执行精切
            </button>
            <button class="btn btn-sm" onclick="FineCut.previewSegment()" title="预览选区">
              <i class="fas fa-play"></i>预览
            </button>
          </div>
          <!-- 时长显示（自动随 start/end 更新） -->
          <div class="row" style="gap:8px; margin-bottom:10px; align-items:center;">
            <i class="fas fa-clock text-brand-purple text-xs"></i>
            <span class="text-xs text-muted">时长</span>
            <span id="fc-duration" class="text-mono text-brand-purple" style="font-size:18px; font-weight:600;">--</span>
            <span class="text-xxs text-muted" id="fc-duration-detail"></span>
            <span class="flex-1"></span>
            <span class="text-xxs text-muted">
              <i class="fas fa-info-circle"></i>
              拖动把手时按住 <kbd style="background:rgba(139,92,246,0.2); padding:1px 5px; border-radius:3px; font-size:10px;">Shift</kbd> 精细调节 (10ms)
            </span>
          </div>
          <div class="timeline-bar" id="fc-timeline" style="height:64px; position:relative;">
            <!-- 选区 -->
            <div class="timeline-seg" id="fc-selected" style="cursor:grab;"></div>
            <!-- 左侧拖拽手柄 (开始) -->
            <div class="fc-handle fc-handle-left" id="fc-handle-left" title="拖动调整开始点"></div>
            <!-- 右侧拖拽手柄 (结束) -->
            <div class="fc-handle fc-handle-right" id="fc-handle-right" title="拖动调整结束点"></div>
            <!-- 播放头 -->
            <div class="timeline-playhead" id="fc-playhead" style="left:0%; z-index:20;"></div>
            <!-- 时间刻度 (可选) -->
            <div class="fc-tick" style="left:0%;"><span>00:00</span></div>
            <div class="fc-tick" style="left:25%;"><span></span></div>
            <div class="fc-tick" style="left:50%;"><span id="fc-tick-mid">--:--</span></div>
            <div class="fc-tick" style="left:75%;"><span></span></div>
            <div class="fc-tick" style="left:100%;"><span id="fc-tick-end">--:--</span></div>
          </div>
        </div>

        <!-- 右侧: 已通过粗切的候选 (按 video 分组) -->
        <div class="card">
          <h3 class="card-title">
            已通过粗切 · 待精切
            <span class="text-xs text-muted" id="fc-approved-count" style="font-weight:normal;"></span>
          </h3>
          <div id="fc-approved" class="col scroll-y" style="max-height:600px;">
            <div class="empty"><i class="fas fa-spinner spin"></i>加载中…</div>
          </div>
          <hr style="border-color:rgba(61,79,111,0.4); margin:12px 0;">
          <h3 class="card-title" style="font-size:12px;">已精切完成</h3>
          <div id="fc-clips" class="col scroll-y" style="max-height:200px;">
            <div class="empty">暂无</div>
          </div>
        </div>
      </div>
    `;
    setTimeout(() => {
      this.bindPlayer();
      this.loadApprovedCandidates();
      this.loadClips();
      // 如果有 pending 候选（从粗切点过来的），自动选中
      if (pending.candidateId) this.selectCandidateById(pending.candidateId);
    }, 50);
    return root;
  },

  bindPlayer() {
    this._player = document.getElementById('fc-player');
    if (!this._player) return;
    const dur = this._currentVideo()?.duration || 0;
    this._player.addEventListener('timeupdate', () => {
      if (!this._player) return;
      const t = this._player.currentTime;
      Utils.setText('fc-time', `${Utils.formatTime(t)} / ${Utils.formatTime(dur)}`);
      const pct = dur > 0 ? (t / dur * 100) : 0;
      const head = document.getElementById('fc-playhead');
      if (head) head.style.left = pct + '%';
    });
    this._player.addEventListener('play', () => Utils.setHTML('fc-play', '<i class="fas fa-pause"></i>暂停'));
    this._player.addEventListener('pause', () => Utils.setHTML('fc-play', '<i class="fas fa-play"></i>播放'));
    ['fc-start', 'fc-end'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', () => this.updateTimelinePreview());
    });
    this.bindTimeline();
    this.updateTicks();
  },

  // 时间刻度文字
  updateTicks() {
    const dur = this._currentVideo()?.duration || 0;
    Utils.setText('fc-tick-mid', dur ? Utils.formatTime(dur / 2) : '--:--');
    Utils.setText('fc-tick-end', dur ? Utils.formatTime(dur) : '--:--');
  },

  // 时间轴拖拽交互
  bindTimeline() {
    const tl = document.getElementById('fc-timeline');
    const handleL = document.getElementById('fc-handle-left');
    const handleR = document.getElementById('fc-handle-right');
    const seg = document.getElementById('fc-selected');
    if (!tl || !handleL || !handleR) return;

    // 精度配置
    const SNAP_STEP = 0.05;        // 普通模式：每 50ms 吸附
    const FINE_STEP = 0.01;        // Shift 精细模式：每 10ms 吸附
    const MIN_GAP_SEC = 0.1;       // 起止最小间隔 100ms
    const KEY_STEP = 0.1;          // 键盘 ←/→ 单步
    const KEY_STEP_LARGE = 1.0;    // 键盘 Shift+←/→ 大步

    const getDur = () => this._currentVideo()?.duration || 0;
    const getPct = (clientX) => {
      const rect = tl.getBoundingClientRect();
      const x = clientX - rect.left;
      return Math.max(0, Math.min(100, (x / rect.width) * 100));
    };
    const pctToSec = (pct) => (pct / 100) * getDur();

    // 应用：snap + min gap + 边界
    const apply = (side, sec) => {
      const dur = getDur();
      sec = Math.max(0, Math.min(dur, sec));
      const otherSide = side === 'L' ? 'R' : 'L';
      const otherHandle = otherSide === 'L' ? handleL : handleR;
      const otherPct = parseFloat(otherHandle.dataset.pct || (otherSide === 'L' ? 0 : 100));
      const otherSec = pctToSec(otherPct);
      if (side === 'L' && sec > otherSec - MIN_GAP_SEC) sec = otherSec - MIN_GAP_SEC;
      if (side === 'R' && sec < otherSec + MIN_GAP_SEC) sec = otherSec + MIN_GAP_SEC;
      sec = Math.max(0, Math.min(dur, sec));
      const inputId = side === 'L' ? 'fc-start' : 'fc-end';
      const el = document.getElementById(inputId);
      if (el) el.value = sec.toFixed(2);
      this.updateTimelinePreview();
      return sec;
    };

    // 拖拽过程中显示跟随的 tooltip（"00:12.34"）
    const showTip = (handle, sec) => {
      let tip = handle.querySelector('.fc-handle-tip');
      if (!tip) {
        tip = document.createElement('div');
        tip.className = 'fc-handle-tip';
        handle.appendChild(tip);
      }
      tip.textContent = Utils.formatTime(sec) + (sec.toFixed ? ` (${sec.toFixed(2)}s)` : '');
      tip.style.display = 'block';
    };
    const hideTip = (handle) => {
      const tip = handle.querySelector('.fc-handle-tip');
      if (tip) tip.style.display = 'none';
    };

    // 通用拖拽函数（绝对定位，不累积误差）
    const makeDrag = (handle, side) => (e) => {
      e.preventDefault();
      e.stopPropagation();
      handle.classList.add('dragging');
      try { handle.focus({ preventScroll: true }); } catch (_) {}
      // 让视频跟随把手：拖 start 时 seek 到 start；拖 end 时 seek 到 end - 0.5s
      // 这样用户能"实时预览"拖到位置的内容
      const previewSeek = (sec) => {
        if (!this._player) return;
        const target = side === 'L' ? sec : Math.max(0, sec - 0.5);
        try {
          this._player.currentTime = target;
          Utils.safePlay(this._player);
        } catch (e) { /* ignore */ }
      };
      const onMove = (ev) => {
        const curX = ev.touches ? ev.touches[0].clientX : ev.clientX;
        const pct = getPct(curX);
        const step = ev.shiftKey ? FINE_STEP : SNAP_STEP;
        let sec = pctToSec(pct);
        // snap 到步长倍数
        sec = Math.round(sec / step) * step;
        sec = apply(side, sec);
        showTip(handle, sec);
        previewSeek(sec);
      };
      const onUp = () => {
        handle.classList.remove('dragging');
        hideTip(handle);
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.removeEventListener('touchmove', onMove);
        document.removeEventListener('touchend', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.addEventListener('touchmove', onMove, { passive: false });
      document.addEventListener('touchend', onUp);
    };

    // 鼠标/触摸 拖拽
    const dragL = makeDrag(handleL, 'L');
    const dragR = makeDrag(handleR, 'R');
    handleL.addEventListener('mousedown', dragL);
    handleL.addEventListener('touchstart', dragL, { passive: false });
    handleR.addEventListener('mousedown', dragR);
    handleR.addEventListener('touchstart', dragR, { passive: false });

    // 键盘：focus 时 ←/→ 调节（fine/step）
    handleL.setAttribute('tabindex', '0');
    handleR.setAttribute('tabindex', '0');
    const onKey = (side) => (e) => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const step = e.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
      const inputId = side === 'L' ? 'fc-start' : 'fc-end';
      const el = document.getElementById(inputId);
      if (!el) return;
      let sec = parseFloat(el.value) || 0;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') sec -= step;
      else sec += step;
      sec = apply(side, sec);
      showTip(side === 'L' ? handleL : handleR, sec);
      // 键盘调节也实时 seek
      if (this._player) {
        const target = side === 'L' ? sec : Math.max(0, sec - 0.5);
        try {
          this._player.currentTime = target;
          Utils.safePlay(this._player);
        } catch (_) { /* ignore */ }
      }
    };
    const keyL = onKey('L');
    const keyR = onKey('R');
    handleL.addEventListener('keydown', keyL);
    handleR.addEventListener('keydown', keyR);
    // 失焦时隐藏 tooltip
    [handleL, handleR].forEach(h => h.addEventListener('blur', () => hideTip(h)));

    // 拖拽选区中段 (平移整体)
    if (seg) {
      const startMove = (e) => {
        if (e.target !== seg) return;  // 只在选区本体上
        e.preventDefault();
        const startX = (e.touches ? e.touches[0].clientX : e.clientX);
        const startSec = {
          start: parseFloat(document.getElementById('fc-start').value) || 0,
          end: parseFloat(document.getElementById('fc-end').value) || 0,
        };
        const dur = getDur();
        const segWidth = startSec.end - startSec.start;
        const onMove = (ev) => {
          const curX = (ev.touches ? ev.touches[0].clientX : ev.clientX);
          const dx = (curX - startX) / tl.getBoundingClientRect().width * dur;
          let newStart = startSec.start + dx;
          let newEnd = startSec.end + dx;
          if (newStart < 0) { newStart = 0; newEnd = segWidth; }
          if (newEnd > dur) { newEnd = dur; newStart = dur - segWidth; }
          document.getElementById('fc-start').value = newStart.toFixed(2);
          document.getElementById('fc-end').value = newEnd.toFixed(2);
          this.updateTimelinePreview();
          // 中段平移时也让视频跟随到新起点
          if (this._player) {
            try {
              this._player.currentTime = newStart;
              Utils.safePlay(this._player);
            } catch (_) { /* ignore */ }
          }
        };
        const onUp = () => {
          seg.style.cursor = 'grab';
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.removeEventListener('touchmove', onMove);
          document.removeEventListener('touchend', onUp);
        };
        seg.style.cursor = 'grabbing';
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend', onUp);
      };
      seg.addEventListener('mousedown', startMove);
      seg.addEventListener('touchstart', startMove);
    }

    // 点击空白区域 → 跳转
    tl.addEventListener('click', (e) => {
      // 只在点击空白处触发 (不在手柄或选区上)
      if (e.target === handleL || e.target === handleR || e.target === seg) return;
      const pct = getPct(e.clientX);
      const sec = pctToSec(pct);
      if (this._player) this._player.currentTime = sec;
    });
  },

  _currentVideo() {
    if (!this._currentVideoId) return null;
    return this._approvedGroups?.find(g => g.video_id === this._currentVideoId) || null;
  },

  togglePlay() {
    if (!this._player) return;
    if (this._player.paused) Utils.safePlay(this._player);
    else this._player.pause();
  },

  async loadApprovedCandidates() {
    const el = document.getElementById('fc-approved');
    if (!el) return;
    try {
      const r = await API.approvedCandidates();
      this._approvedGroups = r.groups || [];
      this.renderApproved();
    } catch (e) {
      el.innerHTML = `<div class="empty text-brand-red">${e.message}</div>`;
    }
  },

  renderApproved() {
    const el = document.getElementById('fc-approved');
    if (!el) return;
    const groups = this._approvedGroups || [];
    Utils.setText('fc-approved-count', `共 ${groups.reduce((s, g) => s + g.candidates.length, 0)} 条`);
    if (groups.length === 0) {
      el.innerHTML = '<div class="empty"><i class="fas fa-inbox"></i>暂无已通过候选</div><p class="text-xs text-muted text-center mt-2">到「粗切工作台」点 ✓ 通过</p>';
      return;
    }
    el.innerHTML = groups.map((g, gi) => {
      const isActive = this._isVideoActive(g.video_id);
      return `
      <div class="col" style="margin-bottom:8px;">
        <div class="row fc-video-group ${isActive ? 'fc-video-group-active' : ''}"
             style="padding:8px 10px; background:${isActive ? 'rgba(139,92,246,0.2)' : 'rgba(20,28,47,0.5)'}; border-radius:6px; cursor:pointer; gap:8px;"
             onclick="FineCut.selectVideo('${g.video_id}')"
             title="点击切换到该视频">
          <i class="fas fa-video ${isActive ? 'text-brand-purple' : 'text-brand-blue'} text-xs"></i>
          <span class="text-xs text-white truncate flex-1">${g.video_name}</span>
          <span class="text-xs text-muted">${g.candidates.length} 段</span>
          ${isActive ? '<i class="fas fa-play text-brand-purple text-[10px]"></i>' : ''}
        </div>
        ${g.candidates.map(c => `
          <div class="list-item ${this._isSelected(g.video_id, c.id) ? 'selected' : ''}"
               style="margin-left:8px; padding:6px 8px;"
               onclick="FineCut.selectCandidate('${g.video_id}', '${c.id}')">
            <div class="w-9 h-6 rounded bg-brand-purple/30 flex items-center justify-center flex-shrink-0">
              <i class="fas fa-play text-white/60 text-[7px]"></i>
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-xs text-white text-mono">${c.start_sec.toFixed(1)}s → ${c.end_sec.toFixed(1)}s</div>
              <div class="text-xxs text-muted">${c.duration_sec.toFixed(1)}s · score=${c.score.toFixed(2)}</div>
            </div>
            <i class="fas fa-arrow-right text-xs text-brand-purple"></i>
          </div>
        `).join('')}
      </div>
    `;
    }).join('');
  },

  _isSelected(videoId, candidateId) {
    return this._currentCandidate &&
           this._currentCandidate.video_id === videoId &&
           this._currentCandidate.id === candidateId;
  },

  // 视频组头是否被选中（即左侧正在显示该视频）
  _isVideoActive(videoId) {
    return this._currentVideoId === videoId;
  },

  // 切换视频（不选择具体候选）：把左侧 player 切到该视频的源片
  selectVideo(videoId) {
    const group = this._approvedGroups.find(g => g.video_id === videoId);
    if (!group) return;
    this._currentVideoId = videoId;
    this._currentCandidate = null;  // 切视频时清掉候选选择
    State.set('currentVideo', {
      id: group.video_id,
      guid: group.video_name,
      url: group.video_url,
      duration: group.duration,
      fps: group.fps,
    });
    const player = document.getElementById('fc-player');
    const empty = document.getElementById('fc-empty');
    if (player && group.video_url) {
      Utils.resetPlayer(player);
      player.src = group.video_url;
      player.style.display = 'block';
      if (empty) empty.style.display = 'none';
      this.bindPlayer();
      player.addEventListener('error', () => {
        Utils.toast(`视频加载失败: ${group.video_url}`, 'error');
      }, { once: true });
      // 自动播放：等视频可以播放了再 play
      const onCanPlay = () => {
        Utils.safePlay(player);
        player.removeEventListener('canplay', onCanPlay);
      };
      player.addEventListener('canplay', onCanPlay, { once: true });
    }
    Utils.setText('fc-current-name', `· ${group.video_name}`);
    // 清空时间输入
    const startEl = document.getElementById('fc-start');
    const endEl = document.getElementById('fc-end');
    if (startEl) startEl.value = '0.00';
    if (endEl) endEl.value = '0.00';
    // 隐藏「来自粗切」徽章（因为还没选候选）
    const badge = document.getElementById('fc-candidate-badge');
    if (badge) badge.style.display = 'none';
    this.updateTimelinePreview();
    this.renderApproved();
    Utils.toast(`已切换到: ${group.video_name}`, 'info', 1200);
  },

  selectCandidateById(candidateId) {
    for (const g of this._approvedGroups || []) {
      for (const c of g.candidates) {
        if (c.id === candidateId) {
          this.selectCandidate(g.video_id, c.id);
          return;
        }
      }
    }
  },

  selectCandidate(videoId, candidateId) {
    const group = this._approvedGroups.find(g => g.video_id === videoId);
    if (!group) return;
    const cand = group.candidates.find(c => c.id === candidateId);
    if (!cand) return;

    this._currentVideoId = videoId;
    this._currentCandidate = cand;

    // 设置 currentVideo (用于 trim API)
    State.set('currentVideo', {
      id: group.video_id,
      guid: group.video_name,
      url: group.video_url,
      duration: group.duration,
      fps: group.fps,
    });

    // 加载视频
    const player = document.getElementById('fc-player');
    const empty = document.getElementById('fc-empty');
    if (player && group.video_url) {
      // 切换 src 前先 reset，避免 play() 跨 src 串扰触发 interrupted
      Utils.resetPlayer(player);
      player.src = group.video_url;
      player.style.display = 'block';
      if (empty) empty.style.display = 'none';
      this.bindPlayer();
      player.addEventListener('error', () => {
        Utils.toast(`视频加载失败: ${group.video_url}`, 'error');
      }, { once: true });
      // 自动播放：等视频可以播放了再 play
      const onCanPlay = () => {
        Utils.safePlay(player);
        player.removeEventListener('canplay', onCanPlay);
      };
      player.addEventListener('canplay', onCanPlay, { once: true });
    }
    Utils.setText('fc-current-name', `· ${group.video_name}`);

    // 填入 start/end
    const startEl = document.getElementById('fc-start');
    const endEl = document.getElementById('fc-end');
    if (startEl) startEl.value = cand.start_sec.toFixed(2);
    if (endEl) endEl.value = cand.end_sec.toFixed(2);

    // 关键修复：seek 视频到候选的 start_sec，让左侧预览到对应位置
    if (player && player.src) {
      try {
        player.currentTime = cand.start_sec;
        // 点击候选即自动播放：让用户立即看到候选的"开头"画面
        Utils.safePlay(player);
      } catch (e) { /* ignore */ }
    }

    // 显示「来自粗切」徽章
    const badge = document.getElementById('fc-candidate-badge');
    if (badge) badge.style.display = '';

    this.updateTimelinePreview();
    this.renderApproved();  // 重新渲染以高亮

    Utils.toast(`已选中候选: ${cand.start_sec.toFixed(1)}s → ${cand.end_sec.toFixed(1)}s`, 'info', 1200);
  },

  updateTimelinePreview() {
    const start = parseFloat(document.getElementById('fc-start')?.value) || 0;
    const end = parseFloat(document.getElementById('fc-end')?.value) || 0;
    const video = this._currentVideo();
    if (!video || !video.duration) return;
    const dur = video.duration;
    const startPct = Math.max(0, Math.min(100, (start / dur) * 100));
    const endPct = Math.max(0, Math.min(100, (end / dur) * 100));
    const width = Math.max(0, endPct - startPct);
    const seg = document.getElementById('fc-selected');
    const hL = document.getElementById('fc-handle-left');
    const hR = document.getElementById('fc-handle-right');
    if (seg) {
      seg.style.left = startPct + '%';
      seg.style.width = width + '%';
      seg.classList.add('tl-purple');
    }
    if (hL) {
      hL.style.left = startPct + '%';
      hL.dataset.pct = startPct;
      hL.style.display = width > 0 ? 'flex' : 'none';
    }
    if (hR) {
      hR.style.left = endPct + '%';
      hR.dataset.pct = endPct;
      hR.style.display = width > 0 ? 'flex' : 'none';
    }
    // 同步"时长"字段
    const durationEl = document.getElementById('fc-duration');
    const detailEl = document.getElementById('fc-duration-detail');
    if (durationEl) {
      const trimmed = Math.max(0, end - start);
      durationEl.textContent = Utils.formatTime(trimmed);
      // 红色 = 不足 5s（最小精切长度）
      durationEl.style.color = trimmed < 5 && trimmed > 0 ? '#ef4444' : '';
      if (detailEl) {
        if (trimmed <= 0) {
          detailEl.textContent = '';
        } else {
          detailEl.textContent = `(${trimmed.toFixed(2)}s · 共 ${Math.round(dur)}s 中 ${(trimmed/dur*100).toFixed(1)}%)`;
        }
      }
    }
  },

  async trim() {
    const video = State.get('currentVideo');
    if (!video) { Utils.toast('请先从右侧选择候选', 'error'); return; }
    const start = parseFloat(document.getElementById('fc-start').value);
    const end = parseFloat(document.getElementById('fc-end').value);
    if (end <= start) { Utils.toast('结束时间必须大于开始时间', 'error'); return; }
    try {
      const r = await Utils.safe(() => API.trimClip({
        video_id: video.id,
        start_sec: start,
        end_sec: end,
      }), '精切失败');
      Utils.toast(`✓ 精切完成: ${(end - start).toFixed(2)}s · 已入队`, 'success');
      State.set('currentClip', r.clip);
      // 从 approved 列表中移除该候选
      this._currentCandidate = null;
      Utils.setHTML('fc-candidate-badge', '');
      const badge = document.getElementById('fc-candidate-badge');
      if (badge) badge.style.display = 'none';
      this.loadApprovedCandidates();
      this.loadClips();
      // 自动跳到 Target Studio 选帧
      setTimeout(() => App.switchModule('target'), 800);
    } catch {}
  },

  async loadClips() {
    const el = document.getElementById('fc-clips');
    if (!el) return;
    try {
      const r = await API.listClips({ limit: 20 });
      if (r.clips.length === 0) { el.innerHTML = '<div class="empty text-xs">暂无</div>'; return; }
      el.innerHTML = r.clips.slice(0, 8).map(c => `
        <div class="list-item" style="padding:4px 8px;" onclick="FineCut.openClip('${c.id}')">
          <i class="fas fa-film text-brand-green text-xs"></i>
          <div class="flex-1 min-w-0">
            <div class="text-xs text-white text-mono">${c.start_sec.toFixed(1)}s → ${c.end_sec.toFixed(1)}s</div>
            <div class="text-xxs text-muted">${c.duration.toFixed(1)}s · ${c.id.slice(0, 6)}</div>
          </div>
          <span class="status-badge ${c.status === 'indexed' ? 'completed' : 'processing'}" style="font-size:9px;">${c.status}</span>
        </div>
      `).join('');
    } catch (e) {
      el.innerHTML = `<div class="empty text-xs text-brand-red">${e.message}</div>`;
    }
  },

  openClip(clipId) {
    // 跳到 Target Studio 让用户标注
    State.set('currentClipId', clipId);
    Utils.toast('已选中已精切片段，前往 Target Studio 标注', 'success');
    setTimeout(() => App.switchModule('target'), 600);
  },
};
