/* Module 6: Target Studio - 目标标注
   布局 (自上而下):
     1) 顶部条: 标题 + 当前 Clip 摘要 + 三个动作按钮 (刷新 / 添加 Target / 完成→4D)
     2) 三栏工作区
        左 (260): 点类型切换 + 当前 Target 标注列表 + 所有 Target 概览
        中 (flex): 大画布 + 帧工具栏 (撤销 / 清空) + 候选帧缩略图带
        右 (300): 待标注 Clip 列表 + 每个 Clip 的标注进度
*/
const Target = {
  objIdCounter: 1,
  _clip: null,                 // 当前选中的 clip
  _clips: [],                  // 待标注 clip 列表
  _frames: [],                 // base64 数组
  _timestamps: [],             // 对应时间戳（相对 clip 起点的秒数）
  _currentFrameIdx: 0,         // 当前显示在主画布的帧索引
  _pointType: 'positive',      // 'positive' | 'negative'
  _annotations: [],            // [{obj_id, frame_idx, point_type, x, y}] 当前 clip 的所有标注
  _nextObjId: 1,               // 下一个 obj_id

  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <!-- ============ 顶部 ============ -->
      <div class="tg-header">
        <div class="tg-header-left">
          <div class="tg-header-title">
            <i class="fas fa-bullseye text-brand-purple"></i>
            <span>Target Studio · <span class="text-muted">首帧标注</span></span>
          </div>
          <div class="tg-header-sub">
            右侧选 clip → 中间展示首帧与候选帧 → 在帧上点正/负向点 → 添加 target
          </div>
        </div>
        <div class="tg-header-clip" id="tg-clip-summary" hidden>
          <span class="text-muted">当前 Clip</span>
          <span class="tg-clip-id text-mono text-white" id="tg-sum-id">-</span>
          <span class="tg-clip-meta text-muted" id="tg-sum-meta">-</span>
          <span class="tg-clip-progress" id="tg-sum-progress">
            <i class="fas fa-circle-dot text-brand-green"></i>
            <span id="tg-sum-ann">0</span> 标注
          </span>
        </div>
        <div class="tg-header-actions">
          <button class="btn btn-sm" onclick="Target.refreshClipList()" title="刷新 Clip 列表">
            <i class="fas fa-sync"></i><span>刷新</span>
          </button>
          <button class="btn btn-primary" id="tg-add-target-btn" onclick="Target.addTarget()" disabled>
            <i class="fas fa-plus-circle"></i><span>添加 Target</span>
          </button>
          <button class="btn btn-success" id="tg-confirm-btn" onclick="Target.confirmAndEnqueue()" disabled>
            <i class="fas fa-check-double"></i><span>完成 → 4D</span>
          </button>
        </div>
      </div>

      <!-- ============ 三栏工作区 ============ -->
      <div class="tg-workspace">

        <!-- 左: 点类型 + 当前 Obj 标注 -->
        <div class="card tg-col tg-col-left">
          <h3 class="card-title">点类型</h3>
          <div class="tg-pt-toggle">
            <button class="tg-pt-btn tg-pt-pos active" id="pt-pos" onclick="Target.setPointType('positive')" title="正向点（目标）">
              <i class="fas fa-plus"></i><span>正向点</span>
            </button>
            <button class="tg-pt-btn tg-pt-neg" id="pt-neg" onclick="Target.setPointType('negative')" title="负向点（排除）">
              <i class="fas fa-minus"></i><span>负向点</span>
            </button>
          </div>
          <div class="tg-pt-hint text-xxs text-muted">在右侧画布单击添加;切换类型仅影响新点击</div>

          <div class="tg-section">
            <div class="tg-section-head">
              <h3 class="card-title" style="margin:0;">当前 Target</h3>
              <span class="tg-section-count" id="tg-ann-count">-</span>
            </div>
            <div id="tg-current-annotations" class="tg-ann-list">
              <div class="text-xs text-muted" style="padding:8px 4px;">尚无标注 - 在中间画布上点击</div>
            </div>
          </div>

          <div class="tg-section">
            <div class="tg-section-head">
              <h3 class="card-title" style="margin:0;">所有 Target</h3>
              <span class="tg-section-count" id="tg-all-count">0</span>
            </div>
            <div id="tg-all-annotations" class="tg-ann-list">
              <div class="text-xs text-muted" style="padding:8px 4px;">尚无 target</div>
            </div>
          </div>

          <div class="tg-section tg-tips">
            <div class="card-title" style="font-size:11px; margin-bottom:6px;">操作提示</div>
            <ul class="tg-tip-list">
              <li><b>选 Clip:</b> 右侧列表单击切换</li>
              <li><b>选帧:</b> 下方候选帧,首帧为默认</li>
              <li><b>标注:</b> 在画布上单击,正向/负向点切换实时生效</li>
              <li><b>完成:</b> 顶部 [完成 → 4D] 入队下游处理</li>
            </ul>
          </div>
        </div>

        <!-- 中: 首帧主画布 + 候选帧缩略图 -->
        <div class="card tg-col tg-col-mid">
          <div class="tg-canvas-head">
            <h3 class="card-title" style="margin:0;">
              标注画布
              <span class="text-xs text-muted" id="tg-canvas-info" style="font-weight:normal;"></span>
            </h3>
            <div class="tg-canvas-meta text-xxs text-muted" id="tg-canvas-resolution"></div>
          </div>
          <div class="tg-canvas" id="target-canvas">
            <img id="target-image" alt="target frame" />
            <div id="target-empty" class="empty">
              <i class="fas fa-hand-pointer"></i>
              <div>请从右侧选择 clip</div>
              <div class="text-xxs text-muted" style="margin-top:6px;">选中后将自动抽取 8 帧候选</div>
            </div>
          </div>
          <div class="tg-canvas-toolbar">
            <span class="text-xs text-mono text-muted" id="tg-frame-info">未选帧</span>
            <span class="tg-canvas-toolbar-spacer"></span>
            <button class="btn btn-sm" onclick="Target.undoLastClick()" title="撤销最近一次点击">
              <i class="fas fa-undo"></i><span>撤销</span>
            </button>
            <button class="btn btn-sm" onclick="Target.clearClicksOnFrame()" title="清除当前帧的全部标注">
              <i class="fas fa-eraser"></i><span>清空本帧</span>
            </button>
          </div>

          <div class="tg-section-head" style="margin-top:14px;">
            <h3 class="card-title" style="margin:0; font-size:12px;">候选帧</h3>
            <span class="tg-section-count" id="tg-frame-count">0 帧</span>
          </div>
          <div class="tg-frames-strip" id="tg-frames">
            <div class="empty" style="grid-column:1 / -1;">加载中…</div>
          </div>
        </div>

        <!-- 右: 待标注 clip 列表 -->
        <div class="card tg-col tg-col-right">
          <div class="tg-section-head">
            <h3 class="card-title" style="margin:0;">待标注 Clips</h3>
            <span class="tg-section-count" id="tg-clip-count">0</span>
          </div>
          <div id="tg-clip-list" class="tg-clip-list">
            <div class="empty"><i class="fas fa-spinner spin"></i>加载中…</div>
          </div>
        </div>

      </div>
    `;
    setTimeout(() => this.init(), 50);
    return root;
  },

  async init() {
    this.objIdCounter = 1;
    this._pointType = 'positive';
    this._currentFrameIdx = 0;
    await this.refreshClipList();
    this.bindCanvasClick();
  },

  // ============== 右侧：待标注 clip 列表 ==============

  async refreshClipList() {
    const el = document.getElementById('tg-clip-list');
    if (!el) return;
    try {
      const r = await API.listPendingTargets();
      this._clips = r.clips || [];
      Utils.setText('tg-clip-count', `${this._clips.length}`);
      if (this._clips.length === 0) {
        el.innerHTML = `
          <div class="empty">
            <i class="fas fa-inbox"></i>
            <div>暂无待标注 clip</div>
          </div>
          <p class="text-xxs text-muted text-center" style="margin-top:8px;">到「精切工作台」创建一个</p>`;
        return;
      }
      el.innerHTML = this._clips.map(c => {
        const isActive = this._clip && this._clip.id === c.id;
        // status: 'fine_cut' (待标注) / 'annotated' (已标注)
        const isAnnotated = c.status === 'annotated';
        const statusCls = isAnnotated ? 'status-badge completed' : 'status-badge processing';
        const statusLabel = isAnnotated ? '已标注' : '待标注';
        return `
          <div class="tg-clip-item ${isActive ? 'selected' : ''}" data-clip-id="${c.id}"
               onclick="Target.selectClip('${c.id}')">
            <div class="tg-clip-item-top">
              <span class="text-xs text-mono text-white">${c.id.slice(0, 10)}</span>
              <span class="${statusCls}">${statusLabel}</span>
            </div>
            <div class="tg-clip-item-time text-xs text-mono">
              <span class="text-white">${c.start_sec.toFixed(2)}s</span>
              <i class="fas fa-arrow-right text-xxs text-muted"></i>
              <span class="text-white">${c.end_sec.toFixed(2)}s</span>
              <span class="text-muted">· ${c.duration.toFixed(2)}s</span>
            </div>
            <div class="tg-clip-item-foot text-xxs text-muted">
              <i class="fas fa-bullseye text-brand-purple"></i>
              <span>${c.annotation_count}</span> 个标注
            </div>
          </div>`;
      }).join('');
    } catch (e) {
      el.innerHTML = `<div class="empty text-brand-red">${e.message}</div>`;
    }
  },

  async selectClip(clipId) {
    const c = this._clips.find(x => x.id === clipId);
    if (!c) return;
    this._clip = c;
    // 重新拉一次 clip 详情（含 annotations）
    try {
      const full = await API.getClip(clipId);
      this._clip = full;
      this._annotations = (full.annotations || []).map(a => ({ ...a }));
      const maxObj = this._annotations.reduce((m, a) => Math.max(m, a.obj_id || 0), 0);
      this._nextObjId = maxObj + 1;
    } catch (e) {
      Utils.toast(`加载 clip 失败: ${e.message}`, 'error');
      return;
    }
    // 重新渲染列表高亮
    document.querySelectorAll('#tg-clip-list .tg-clip-item').forEach(el => {
      el.classList.toggle('selected', el.dataset.clipId === clipId);
    });
    // 顶部摘要
    this.renderClipSummary();
    // 加载候选帧
    await this.loadFrames(clipId);
    // 加载已有标注渲染
    this.renderCurrentAnnotations();
    this.renderAllAnnotations();
    // 默认显示首帧
    this.showFrame(0);
    // 启用按钮
    document.getElementById('tg-add-target-btn').disabled = false;
    document.getElementById('tg-confirm-btn').disabled = false;
  },

  renderClipSummary() {
    const sumEl = document.getElementById('tg-clip-summary');
    if (!sumEl || !this._clip) return;
    sumEl.hidden = false;
    Utils.setText('tg-sum-id', this._clip.id.slice(0, 10));
    Utils.setText('tg-sum-meta',
      `${this._clip.start_sec.toFixed(2)}s → ${this._clip.end_sec.toFixed(2)}s · ${this._clip.duration.toFixed(2)}s`);
    Utils.setText('tg-sum-ann', this._annotations.length);
  },

  // ============== 中间：候选帧与画布 ==============

  async loadFrames(clipId) {
    const el = document.getElementById('tg-frames');
    if (!el) return;
    el.innerHTML = '<div class="empty" style="grid-column:1 / -1;"><i class="fas fa-spinner spin"></i>抽帧中…</div>';
    try {
      const r = await API.extractFrames(clipId, 8);
      this._frames = r.frames || [];
      this._timestamps = r.timestamps || [];
      Utils.setText('tg-frame-count', `${this._frames.length} 帧`);
      if (this._frames.length === 0) {
        el.innerHTML = '<div class="empty" style="grid-column:1 / -1;">无法抽帧</div>';
        return;
      }
      el.innerHTML = this._frames.map((b64, i) => {
        const cnt = this._annotations.filter(a => a.frame_idx === i).length;
        const isCurrent = i === this._currentFrameIdx;
        return `
          <div class="tg-frame ${isCurrent ? 'selected' : ''}"
               data-idx="${i}"
               onclick="Target.showFrame(${i})">
            <img src="data:image/jpeg;base64,${b64}" alt="frame ${i + 1}">
            <div class="tg-frame-time">${(this._timestamps[i] || 0).toFixed(2)}s</div>
            <div class="tg-frame-idx">#${i + 1}</div>
            ${cnt > 0 ? `<div class="tg-frame-badge">${cnt}</div>` : ''}
          </div>`;
      }).join('');
    } catch (e) {
      el.innerHTML = `<div class="empty text-brand-red" style="grid-column:1 / -1;">${e.message}</div>`;
    }
  },

  showFrame(idx) {
    if (idx < 0 || idx >= this._frames.length) return;
    this._currentFrameIdx = idx;
    const img = document.getElementById('target-image');
    const empty = document.getElementById('target-empty');
    if (img) {
      img.src = 'data:image/jpeg;base64,' + this._frames[idx];
      img.style.display = 'block';
      // 绘制已有标注点
      this.drawAnnotationMarkers();
      // 图片加载完成后写入分辨率
      const onLoad = () => {
        const w = img.naturalWidth || img.width;
        const h = img.naturalHeight || img.height;
        const resEl = document.getElementById('tg-canvas-resolution');
        if (resEl) resEl.textContent = `${w} × ${h}`;
        img.removeEventListener('load', onLoad);
      };
      if (img.complete && img.naturalWidth) onLoad();
      else img.addEventListener('load', onLoad, { once: true });
    }
    if (empty) empty.style.display = 'none';
    Utils.setText('tg-frame-info', `第 ${idx + 1}/${this._frames.length} 帧 · ${(this._timestamps[idx] || 0).toFixed(2)}s`);
    Utils.setText('tg-canvas-info', `第 ${idx + 1} 帧 · ${(this._timestamps[idx] || 0).toFixed(2)}s · 在图上点击`);
    document.querySelectorAll('.tg-frame').forEach((el, i) => {
      el.classList.toggle('selected', i === idx);
    });
  },

  // 在主画布上绘制当前帧的标注点（绿色加号 / 红色减号）
  drawAnnotationMarkers() {
    const canvas = document.getElementById('target-canvas');
    const img = document.getElementById('target-image');
    if (!canvas || !img) return;
    // 清掉旧的 marker
    canvas.querySelectorAll('.tg-marker').forEach(m => m.remove());
    // 当前帧的标注
    const anns = this._annotations.filter(a => a.frame_idx === this._currentFrameIdx);
    if (anns.length === 0) return;
    // 等图片加载完再绘制坐标
    const draw = () => {
      const rect = img.getBoundingClientRect();
      const canvasRect = canvas.getBoundingClientRect();
      const offsetX = rect.left - canvasRect.left;
      const offsetY = rect.top - canvasRect.top;
      // img 是按原始分辨率渲染后被 max-width 缩放，需要把标注坐标 (x, y in frame pixels) 映射到显示坐标
      const iw = img.naturalWidth || img.width;
      const ih = img.naturalHeight || img.height;
      const scaleX = rect.width / iw;
      const scaleY = rect.height / ih;
      anns.forEach(a => {
        const dot = document.createElement('div');
        dot.className = `tg-marker ${a.point_type === 'positive' ? 'tg-marker-pos' : 'tg-marker-neg'}`;
        dot.style.left = (offsetX + a.x * scaleX) + 'px';
        dot.style.top = (offsetY + a.y * scaleY) + 'px';
        dot.textContent = a.point_type === 'positive' ? '+' : '−';
        // obj_id 角标
        const tag = document.createElement('div');
        tag.className = 'tg-marker-tag';
        tag.textContent = '#' + a.obj_id;
        tag.style.left = (offsetX + a.x * scaleX + 10) + 'px';
        tag.style.top = (offsetY + a.y * scaleY - 18) + 'px';
        canvas.appendChild(dot);
        canvas.appendChild(tag);
      });
    };
    if (img.complete) draw();
    else img.addEventListener('load', draw, { once: true });
  },

  // ============== 点击画布 ==============

  bindCanvasClick() {
    const canvas = document.getElementById('target-canvas');
    if (!canvas) return;
    canvas.addEventListener('click', (e) => this.handleCanvasClick(e));
  },

  async handleCanvasClick(e) {
    if (!this._clip) {
      Utils.toast('请先在右侧选择 clip', 'error');
      return;
    }
    const img = document.getElementById('target-image');
    if (!img || img.style.display === 'none') return;
    const canvas = document.getElementById('target-canvas');
    const imgRect = img.getBoundingClientRect();
    const cw = imgRect.width;
    const ch = imgRect.height;
    if (cw === 0 || ch === 0) return;
    // 鼠标位置要在图片范围内
    if (e.clientX < imgRect.left || e.clientX > imgRect.right ||
        e.clientY < imgRect.top  || e.clientY > imgRect.bottom) return;
    const localX = e.clientX - imgRect.left;
    const localY = e.clientY - imgRect.top;
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    const x = Math.round((localX / cw) * iw);
    const y = Math.round((localY / ch) * ih);
    const obj_id = this._nextObjId;
    const pt = this._pointType;
    const frame_idx = this._currentFrameIdx;
    const annotation = { obj_id, frame_idx, point_type: pt, x, y };
    // 乐观更新：先 push 到本地
    this._annotations.push(annotation);
    this.drawAnnotationMarkers();
    this.renderCurrentAnnotations();
    this.renderAllAnnotations();
    this.renderClipSummary();
    // 更新候选帧角标
    this.refreshFrameBadge(frame_idx);
    // 持久化
    try {
      await Utils.safe(() => API.annotateClip(this._clip.id, {
        annotations: this._annotations,
      }), '保存标注失败');
      Utils.toast(`✓ 已标注 obj #${obj_id} (${pt}) at (${x}, ${y})`, 'success', 1200);
    } catch (err) {
      // 回滚
      this._annotations = this._annotations.filter(a => a !== annotation);
      this.drawAnnotationMarkers();
      this.renderCurrentAnnotations();
      this.renderClipSummary();
      console.warn('annotate failed:', err);
    }
  },

  refreshFrameBadge(frameIdx) {
    const cell = document.querySelector(`.tg-frame[data-idx="${frameIdx}"]`);
    if (!cell) return;
    const cnt = this._annotations.filter(a => a.frame_idx === frameIdx).length;
    let badge = cell.querySelector('.tg-frame-badge');
    if (cnt > 0) {
      if (!badge) {
        badge = document.createElement('div');
        badge.className = 'tg-frame-badge';
        cell.appendChild(badge);
      }
      badge.textContent = cnt;
    } else if (badge) {
      badge.remove();
    }
  },

  undoLastClick() {
    if (this._annotations.length === 0) return;
    const removed = this._annotations.pop();
    this._nextObjId = Math.max(1, removed.obj_id);
    this.drawAnnotationMarkers();
    this.renderCurrentAnnotations();
    this.renderAllAnnotations();
    this.renderClipSummary();
    this.refreshFrameBadge(removed.frame_idx);
    // 持久化
    if (this._clip) {
      API.annotateClip(this._clip.id, { annotations: this._annotations }).catch(() => {});
    }
    Utils.toast('已撤销最后一个标注', 'info', 800);
  },

  clearClicksOnFrame() {
    if (!this._clip) return;
    const before = this._annotations.length;
    this._annotations = this._annotations.filter(a => a.frame_idx !== this._currentFrameIdx);
    const after = this._annotations.length;
    if (before === after) {
      Utils.toast('当前帧无标注', 'info', 800);
      return;
    }
    this.drawAnnotationMarkers();
    this.renderCurrentAnnotations();
    this.renderAllAnnotations();
    this.renderClipSummary();
    this.refreshFrameBadge(this._currentFrameIdx);
    API.annotateClip(this._clip.id, { annotations: this._annotations }).catch(() => {});
    Utils.toast(`已清空本帧 ${before - after} 个标注`, 'info', 1200);
  },

  // ============== 左侧：标注列表 ==============

  renderCurrentAnnotations() {
    const el = document.getElementById('tg-current-annotations');
    if (!el) return;
    const currentObj = this._nextObjId - 1;
    const anns = this._annotations.filter(a => a.obj_id === currentObj);
    Utils.setText('tg-ann-count', `#${currentObj} · ${anns.length} 点`);
    if (anns.length === 0) {
      el.innerHTML = '<div class="text-xs text-muted" style="padding:8px 4px;">尚无标注 - 在中间画布上点击</div>';
      return;
    }
    el.innerHTML = anns.map((a, i) => `
      <div class="tg-ann-row">
        <span class="tg-ann-badge ${a.point_type === 'positive' ? 'tg-ann-pos' : 'tg-ann-neg'}">${a.point_type === 'positive' ? '+' : '−'}</span>
        <span class="text-xs text-mono text-muted">@ ${a.frame_idx + 1}帧</span>
        <span class="text-xxs text-mono text-muted">${(this._timestamps[a.frame_idx] || 0).toFixed(2)}s</span>
        <span class="tg-ann-coord text-xxs text-mono text-white">(${a.x}, ${a.y})</span>
      </div>`).join('');
  },

  renderAllAnnotations() {
    const el = document.getElementById('tg-all-annotations');
    if (!el) return;
    if (this._annotations.length === 0) {
      el.innerHTML = '<div class="text-xs text-muted" style="padding:8px 4px;">尚无 target</div>';
      Utils.setText('tg-all-count', '0');
      return;
    }
    // 按 obj_id 分组
    const grouped = {};
    this._annotations.forEach(a => {
      grouped[a.obj_id] = grouped[a.obj_id] || [];
      grouped[a.obj_id].push(a);
    });
    const ids = Object.keys(grouped).sort((a, b) => Number(a) - Number(b));
    Utils.setText('tg-all-count', `${ids.length}`);
    el.innerHTML = ids.map(oid => {
      const list = grouped[oid];
      const pos = list.filter(a => a.point_type === 'positive').length;
      const neg = list.filter(a => a.point_type === 'negative').length;
      const isCurrent = Number(oid) === this._nextObjId - 1;
      return `
        <div class="tg-all-row ${isCurrent ? 'current' : ''}">
          <span class="tg-obj-tag ${pos > 0 ? 'tg-obj-tag-ok' : 'tg-obj-tag-empty'}">#${oid}</span>
          <span class="text-xxs text-brand-green">+${pos}</span>
          <span class="text-xxs text-brand-red">−${neg}</span>
          <span class="tg-all-spacer"></span>
          <span class="text-xxs text-muted">${list.length} 点</span>
        </div>`;
    }).join('');
  },

  // ============== 点类型切换 ==============

  setPointType(t) {
    this._pointType = t;
    const pos = document.getElementById('pt-pos');
    const neg = document.getElementById('pt-neg');
    if (pos) pos.classList.toggle('active', t === 'positive');
    if (neg) neg.classList.toggle('active', t === 'negative');
  },

  // ============== 添加 Target / 完成 4D ==============

  addTarget() {
    if (!this._clip) { Utils.toast('请先选择 clip', 'error'); return; }
    const currentObj = this._nextObjId - 1;
    const currentAnns = this._annotations.filter(a => a.obj_id === currentObj);
    if (currentAnns.length === 0) {
      Utils.toast(`当前 obj #${currentObj} 没有任何标注，请在画布上点击添加`, 'error');
      return;
    }
    // 推一个新的 obj_id，给下一个 target 用
    this._nextObjId += 1;
    this.renderCurrentAnnotations();
    this.renderAllAnnotations();
    Utils.toast(`✓ Target #${currentObj} 已添加（${currentAnns.length} 点）`, 'success', 1500);
  },

  async confirmAndEnqueue() {
    if (!this._clip) { Utils.toast('请先选择 clip', 'error'); return; }
    if (this._annotations.length === 0) {
      Utils.toast('请至少添加 1 个标注', 'error');
      return;
    }
    try {
      const r = await Utils.safe(() => API.listTargets(this._clip.id), '读取标注失败');
      Utils.toast(`✓ ${r.targets.length} 个 target 已入队 → 4D 处理`, 'success');
      setTimeout(() => App.switchModule('4d'), 800);
    } catch (e) {
      console.warn(e);
    }
  },
};
