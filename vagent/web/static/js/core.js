/* Vagent · 工具函数、全局状态、接口客户端
   只在本模块内改动，跨模块依赖走上面的 import。 */
/* ---------- 1 工具 ---------- */
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
export const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const ic = (name, cls) => `<i data-lucide="${name}" class="${cls}"></i>`;

export function paint(root = document) {
  if (window.lucide) lucide.createIcons();
}

export function toast(msg, type = 'info') {
  const host = $('#toastHost');
  if (!host) return;
  const el = document.createElement('div');
  const icon = type === 'ok' ? 'check-circle-2' : type === 'warn' ? 'alert-triangle' : 'info';
  const color = type === 'ok' ? 'text-ok' : type === 'warn' ? 'text-amber2' : 'text-sub';
  el.className = 'toast pointer-events-auto flex w-full items-start gap-2 rounded-[9px] border border-line2 bg-[#191A1F]/97 px-3 py-2.5 text-[11.5px] leading-snug text-txt shadow-[0_20px_40px_-18px_rgba(0,0,0,.95)] backdrop-blur';
  el.innerHTML = `<i data-lucide="${icon}" class="mt-[1px] h-3.5 w-3.5 shrink-0 ${color}"></i><span class="min-w-0 flex-1">${esc(msg)}</span>`;
  host.appendChild(el);
  paint(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, 2400);
}

export const fmtDur = n => `${Number(n || 0).toFixed(1)}s`;
export const totalDur = () => S.shots.reduce((a, s) => a + Number(s.dur || 0), 0);
export function timeLabel(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/* 空状态：整块虚线卡片 */
export function emptyBlock({ icon = 'inbox', title, desc = '', action = '', label = '', hint = '' }) {
  return `
    <div class="flex flex-col items-center justify-center gap-2.5 rounded-[10px] border border-dashed border-line2 bg-card/40 px-8 py-10 text-center">
      <span class="flex h-10 w-10 items-center justify-center rounded-full border border-line2 bg-raise">${ic(icon, 'h-4.5 w-4.5 text-sub')}</span>
      <p class="text-[13px] font-medium text-txt">${esc(title)}</p>
      ${desc ? `<p class="max-w-[360px] text-[11px] leading-relaxed text-dim">${esc(desc)}</p>` : ''}
      ${action ? `<button data-action="${action}" class="grad-amber mt-1 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium text-[#1B0E05]">${ic('plus', 'h-3.5 w-3.5')}${esc(label)}</button>` : ''}
      ${hint ? `<p class="mt-0.5 text-[10px] text-dim">${esc(hint)}</p>` : ''}
    </div>`;
}

export function emptyLine(text) {
  return `<div class="flex flex-col items-center justify-center gap-1.5 px-4 py-6 text-center">
    <p class="text-[10.5px] text-dim">${esc(text)}</p>
  </div>`;
}

/* ---------- 2 状态 ---------- */
export const S = {
  view: 'manage',
  ready: false,
  projects: [], assets: [], shots: [], materials: [], messages: [],
  assetStats: { total: 0, inherit: 0, private: 0, locked: 0, generating: 0 },
  current: { projectId: '', subId: '', name: '', sub: '', tag: '' },
  account: {},
  apiUsage: { groups: {}, recent: [], total: 0 },
  settings: { api: {} },
  usage: { total: 0, budget: 0, usedPct: 0, remaining: 0, generatedShots: 0, quotaLeftPct: 100 },
  spend: { monthTotal: 0, monthBefore: 0, budget: 0, usedPct: 0, categories: [], daily: [], topProjects: [], records: [] },
  savedAt: '',
  assetScope: 'project',
  assetType: 'all',
  assetStatus: 'all',
  assetQuery: '',
  selected: new Set(),
  editingAsset: '',
  chatPending: false,
  clarify: null,
  finalPending: false,
  confirmKind: '',
  proposalClicked: {},
  draftClicked: {},
  refShotId: '',
  autoMode: sessionStorage.getItem('vagent.autoMode') === 'on',
  autoRun: null,
  pendingAssets: [],
  video: { shotId: '', playhead: 0, playing: false, tool: 'select', raf: 0 },
  drawer: { open: false, tab: 'api', collapsed: { llm: false, img: false, video: false } },
  migrate: { open: false, ids: [], mode: 'copy', target: '', conflicts: {} },
  undo: [],
  aiPending: null,
  assetAudit: {},
  busy: {}
};

/* ---------- 3 接口 ---------- */
export const API = {
  async req(method, url, body) {
    let res;
    try {
      res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body)
      });
    } catch (e) {
      const err = new Error('网络异常：无法连接后端服务');
      err.status = 0;
      throw err;
    }
    let json = null;
    try { json = await res.json(); } catch (e) { json = null; }
    if (!json) {
      const err = new Error(`后端返回了非 JSON 响应（HTTP ${res.status}）`);
      err.status = res.status;
      throw err;
    }
    if (!json.ok) {
      const err = new Error((json.error && json.error.message) || `请求失败（HTTP ${res.status}）`);
      err.code = json.error && json.error.code;
      err.status = res.status;
      throw err;
    }
    return json.data;
  },
  get(url) { return this.req('GET', url); },
  post(url, body) { return this.req('POST', url, body); },
  put(url, body) { return this.req('PUT', url, body); },
  patch(url, body) { return this.req('PATCH', url, body); },
  del(url) { return this.req('DELETE', url); }
};

export function applyBoot(d) {
  S.projects = d.projects || [];
  S.assets = d.assets || [];
  S.assetStats = d.assetStats || S.assetStats;
  S.shots = d.shots || [];
  S.materials = d.materials || [];
  S.messages = d.messages || [];
  S.historyLimit = d.historyLimit;
  S.autoRun = d.autoRun || null;
  S.current = d.currentProject || { projectId: '', subId: '', name: '', sub: '', tag: '' };
  S.account = d.account || {};
  if (d.apiUsage) S.apiUsage = d.apiUsage;
  if (d.settings) S.settings = d.settings;
  if (d.usage) S.usage = d.usage;
  if (d.spend) S.spend = d.spend;
  S.savedAt = d.savedAt || '';

  if (!S.current.subId) S.current.subId = '';
  if (!S.video.shotId || !S.shots.some(s => s.id === S.video.shotId)) {
    S.video.shotId = S.shots.length ? S.shots[0].id : '';
  }
  if (S.editingAsset && !S.assets.some(a => a.id === S.editingAsset)) S.editingAsset = '';
  S.selected.forEach(id => { if (!S.assets.some(a => a.id === id)) S.selected.delete(id); });
  if (S.pendingAssets.length) {
    S.pendingAssets = S.pendingAssets.filter(id => S.assets.some(a => a.id === id));
  }

  const sn = $('#switcherName'), ss = $('#switcherSub'), st = $('#switcherTag');
  if (sn) sn.textContent = S.current.name || '还没有项目';
  if (ss) ss.textContent = S.current.sub || '新建一个开始';
  if (st) st.textContent = S.current.tag || '—';

  const usageEl = $('#usageTotal');
  if (usageEl) usageEl.textContent = `${Number(S.apiUsage.total || 0)} 次`;

  const saved = $('#drawerSavedAt');
  if (saved) saved.textContent = S.savedAt ? `上次保存 ${S.savedAt.slice(5, 16)}` : '尚未保存过设置';
}

export function hideBootGate() {
  const g = $('#bootGate');
  if (g) g.remove();
}
export function showBootError(err) {
  const spin = $('#bootSpinner'); if (spin) spin.classList.add('hidden');
  const text = $('#bootText'); if (text) text.textContent = '数据未能载入，界面暂时无法渲染';
  const box = $('#bootError'); if (box) { box.classList.remove('hidden'); box.classList.add('flex'); }
  const t = $('#bootErrorText'); if (t) t.textContent = (err && err.message) || '未知错误';
}

export function currentProject() {
  return S.projects.find(p => p.id === S.current.projectId) || null;
}
export function currentSub() {
  const p = currentProject();
  return p ? (p.subs || []).find(s => s.id === S.current.subId) || null : null;
}
