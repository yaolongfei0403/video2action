/* API 客户端 - 封装所有后端调用 */
const API = (() => {
  const BASE = '';  // 同源
  const headers = { 'Content-Type': 'application/json' };

  async function request(method, path, body = null, isForm = false) {
    const opts = { method, headers: isForm ? {} : { ...headers } };
    if (body && !isForm) opts.body = JSON.stringify(body);
    if (body && isForm) opts.body = body;
    const r = await fetch(BASE + path, opts);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    if (r.status === 204) return null;
    return r.json();
  }

  return {
    base: BASE,

    // ============== Dashboard ==============
    metrics:           () => request('GET', '/api/dashboard/metrics'),
    recent:            () => request('GET', '/api/dashboard/recent'),
    categoryStats:     () => request('GET', '/api/dashboard/category-stats'),
    taskProgress:      () => request('GET', '/api/dashboard/task-progress'),

    // ============== Tasks ==============
    listTasks:         (params = {}) => {
      const q = new URLSearchParams(params).toString();
      return request('GET', `/api/tasks${q ? '?' + q : ''}`);
    },
    getTask:           (id) => request('GET', `/api/tasks/${id}`),
    createTask:        (data) => request('POST', '/api/tasks', data),
    advanceTask:       (id, data) => request('POST', `/api/tasks/${id}/advance`, data),
    deleteTask:        (id) => request('DELETE', `/api/tasks/${id}`),

    // ============== Video Import ==============
    importLocal:       (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return request('POST', '/api/import/local', fd, true);
    },
    importGuid:        (data) => request('POST', '/api/import/guid', data),
    importHistory:     () => request('GET', '/api/import/history'),
    getVideo:          (id) => request('GET', `/api/import/video/${id}`),

    // ============== Rough Cut ==============
    runRoughCut:       (data) => request('POST', '/api/rough-cut/run', data),
    roughCutQueue:     () => request('GET', '/api/rough-cut/queue'),
    approvedCandidates:() => request('GET', '/api/rough-cut/approved'),
    listCandidates:    (videoId) => request('GET', `/api/rough-cut/candidates/${videoId}`),
    approveCandidate:  (id, approved) => request('POST', `/api/rough-cut/approve/${id}?approved=${approved}`),
    rejectCandidate:   (id, rejected = true) => request('POST', `/api/rough-cut/reject/${id}?rejected=${rejected}`),

    // ============== Fine Cut ==============
    trimClip:          (data) => request('POST', '/api/fine-cut/trim', data),
    listClips:         (params = {}) => {
      const q = new URLSearchParams(params).toString();
      return request('GET', `/api/fine-cut/clips${q ? '?' + q : ''}`);
    },
    getClip:           (id) => request('GET', `/api/fine-cut/clip/${id}`),

    // ============== Target ==============
    clickTarget:       (data) => request('POST', '/api/target/click', data),
    addTarget:         (data) => request('POST', '/api/target/add', data),
    listTargets:       (clipId) => request('GET', `/api/target/list/${clipId}`),
    listPendingTargets:() => request('GET', '/api/clips/pending-targets'),
    extractFrames:     (clipId, count = 8) => request('GET', `/api/clips/${clipId}/frames?count=${count}`),
    annotateClip:      (clipId, data) => request('POST', `/api/clips/${clipId}/annotate`, data),
    clipQueue:         () => request('GET', '/api/clips/queue'),
    queueAll:          () => request('GET', '/api/clips/queue/all'),
    start4DForClip:    (clipId) => request('POST', `/api/clips/${clipId}/start-4d`),

    // ============== 4D ==============
    propagateMasks:    (data) => request('POST', '/api/4d/mask', data),
    reconstruct4D:     (data) => request('POST', '/api/4d/reconstruct', data),
    get4DStatus:       (taskId) => request('GET', `/api/4d/status/${taskId}`),
    processNext4D:     () => request('POST', '/api/4d/process-next'),

    // ============== Tagging ==============
    vlmDescribe:       (data) => request('POST', '/api/tagging/vlm', data),
    saveTags:          (data) => request('POST', '/api/tagging/save', data),
    indexClip:         (clipId) => request('POST', `/api/tagging/index?clip_id=${clipId}`),

    // ============== Assets ==============
    listAssets:        (params = {}) => {
      const q = new URLSearchParams(params).toString();
      return request('GET', `/api/assets${q ? '?' + q : ''}`);
    },
    getAsset:          (id) => request('GET', `/api/assets/${id}`),
    deleteAsset:       (id) => request('DELETE', `/api/assets/${id}`),

    // ============== Search ==============
    searchText:        (data) => request('POST', '/api/search/text', data),
    referenceForGen:   (data) => request('POST', '/api/search/reference', data),
    searchStats:       () => request('GET', '/api/search/stats'),

    // ============== Completed ==============
    getCompletion:     (taskId) => request('GET', `/api/completed/${taskId}`),
  };
})();
