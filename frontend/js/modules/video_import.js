/* Module 3: Video Import - 视频接入 (本地 + GUID) */
const VideoImport = {
  async render() {
    const root = document.createElement('div');
    root.innerHTML = `
      <div class="flex items-end justify-between mb-5">
        <div>
          <h2 class="text-xl font-semibold text-white">视频接入</h2>
          <p class="text-[12px] text-gray-500 mt-1">支持本地视频文件上传与远端 GUID 批量拉取</p>
        </div>
        <button class="btn" onclick="VideoImport.loadHistory()"><i class="fas fa-history"></i>刷新历史</button>
      </div>
      <div class="row" style="gap:0; border-bottom:1px solid rgba(61,79,111,0.4); margin-bottom:16px;">
        <button class="tab-btn active" data-tab="local" onclick="VideoImport.switchTab('local')">
          <i class="fas fa-cloud-arrow-up mr-1.5"></i>本地视频导入
        </button>
        <button class="tab-btn" data-tab="guid" onclick="VideoImport.switchTab('guid')">
          <i class="fas fa-link mr-1.5"></i>GUID 批量导入
        </button>
      </div>
      <div id="tab-local">
        <div class="module-grid" style="grid-template-columns: 3fr 2fr; gap:16px;">
          <div class="card">
            <h3 class="card-title">上传本地视频文件</h3>
            <div class="upload-zone" id="uploadZone" style="padding:40px; text-align:center; border-radius:12px;">
              <i class="fas fa-cloud-arrow-up" style="font-size:36px; color:#3b82f6;"></i>
              <p style="margin:8px 0 4px; font-size:13px; color:white;">点击或拖拽视频文件到此处</p>
              <p style="margin:0 0 16px; font-size:11px; color:#6b7280;">支持 MP4 / MOV / AVI / MKV</p>
              <input type="file" id="fileInput" accept="video/*" style="display:none">
              <button class="btn btn-primary" onclick="document.getElementById('fileInput').click()">
                <i class="fas fa-folder-open"></i>选择文件
              </button>
            </div>
          </div>
          <div class="card">
            <h3 class="card-title">最近导入</h3>
            <div id="history-list" class="col" style="max-height:300px; overflow-y:auto;">
              <div class="empty">加载中…</div>
            </div>
          </div>
        </div>
      </div>
      <div id="tab-guid" style="display:none;">
        <div class="module-grid" style="grid-template-columns: 3fr 2fr; gap:16px;">
          <div class="card">
            <h3 class="card-title">GUID 批量拉取</h3>
            <p class="text-xs text-muted" style="margin-bottom:8px;">支持逗号 / 换行分隔批量导入</p>
            <textarea id="guidText" class="textarea" rows="6" placeholder="guid_001, guid_002, guid_003...">guid_001, guid_002, guid_003
guid_004, guid_005</textarea>
            <div class="row" style="margin-top:12px; gap:8px;">
              <button class="btn btn-primary btn-block" onclick="VideoImport.doGuidImport()">
                <i class="fas fa-play"></i>开始批量导入
              </button>
            </div>
          </div>
          <div class="card">
            <h3 class="card-title">提示</h3>
            <p class="text-xs text-muted" style="line-height:1.6;">
              • 演示模式下会为每个 GUID 创建一个 pending 视频源<br>
              • 真实环境对接上游 CDN / MinIO<br>
              • 导入后可前往「粗切工作台」自动切片
            </p>
          </div>
        </div>
      </div>
    `;
    setTimeout(() => {
      this.bindEvents();
      this.loadHistory();
    }, 50);
    return root;
  },
  switchTab(name) {
    document.querySelectorAll('[data-tab]').forEach(el => {
      el.classList.toggle('active', el.dataset.tab === name);
    });
    document.getElementById('tab-local').style.display = name === 'local' ? '' : 'none';
    document.getElementById('tab-guid').style.display = name === 'guid' ? '' : 'none';
  },
  bindEvents() {
    const zone = document.getElementById('uploadZone');
    if (zone) {
      zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
      zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
      zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) this.handleFile(e.dataTransfer.files[0]);
      });
    }
    const fi = document.getElementById('fileInput');
    if (fi) fi.addEventListener('change', e => {
      if (e.target.files.length) this.handleFile(e.target.files[0]);
    });
  },
  async handleFile(file) {
    Utils.toast(`上传中: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`, 'info');
    try {
      const r = await Utils.safe(() => API.importLocal(file), '上传失败');
      if (r.auto_rough_cut) {
        Utils.toast(`✓ 上传成功 · 后台自动粗切已入队: ${r.video.guid || r.video.id}`, 'success', 2500);
      } else {
        Utils.toast(`上传成功: ${r.video.guid || r.video.id}`, 'success');
      }
      this.loadHistory();
      State.set('currentVideo', r.video);
    } catch {}
  },
  async doGuidImport() {
    const text = document.getElementById('guidText').value.trim();
    if (!text) { Utils.toast('请输入至少一个 GUID', 'error'); return; }
    const guids = text.split(/[,\n\s]+/).filter(s => s);
    try {
      const r = await Utils.safe(() => API.importGuid({ guids }), '导入失败');
      Utils.toast(`成功创建 ${r.total} 个待处理视频源`, 'success');
      this.loadHistory();
    } catch {}
  },
  async loadHistory() {
    const el = document.getElementById('history-list');
    if (!el) return;
    el.innerHTML = '<div class="empty"><i class="fas fa-spinner spin"></i>加载中…</div>';
    try {
      const r = await API.importHistory();
      if (r.videos.length === 0) {
        Utils.setHTML('history-list', '<div class="empty"><i class="fas fa-inbox"></i>暂无导入</div>');
        return;
      }
      Utils.setHTML('history-list', r.videos.map(v => `
        <div class="list-item" onclick="State.set('currentVideo', ${JSON.stringify(v).replace(/"/g, '&quot;')})">
          <i class="fas fa-file-video text-brand-blue"></i>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-white truncate">${v.guid || v.id}</div>
            <div class="text-xs text-muted">${Utils.formatDuration(v.duration)} · ${v.fps.toFixed(1)} fps</div>
          </div>
          <span class="status-badge ${v.status === 'downloaded' ? 'completed' : 'pending'}">${v.status}</span>
        </div>
      `).join(''));
    } catch (e) {
      Utils.setHTML('history-list', `<div class="empty text-brand-red">${e.message}</div>`);
    }
  },
};
