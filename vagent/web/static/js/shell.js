/* Vagent · 视图注册与切换、刷新、项目切换器、个人中心开关
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, $$, API, S, applyBoot, esc, hideBootGate, ic, paint, showBootError, toast } from './core.js';
import { renderManage } from './manage.js';
import { renderChat, scrollChatToBottom } from './chat.js';
import { renderAssetDrawer, renderAssets, renderBatchBar } from './assets.js';
import { renderVideo } from './video.js';
import { renderConfirm } from './confirm.js';
export async function refresh(opts = {}) {
  const d = await API.get('/api/bootstrap');
  applyBoot(d);
  /* bootstrap 默认返回「本项目」范围，保持用户当前选择的范围 */
  if (S.assetScope && S.assetScope !== 'project') {
    try {
      const a = await API.get('/api/assets?scope=' + encodeURIComponent(S.assetScope));
      S.assets = a.assets || S.assets;
      S.assetStats = a.stats || S.assetStats;
    } catch (e) { /* 忽略：退回默认范围 */ }
  }
  renderRail();
  renderAllViews();
  renderRecent();
  if (opts.view) switchView(opts.view);
  paint();
  if (opts.toast) toast(opts.toast, opts.type || 'ok');
}

export async function boot() {
  try {
    const d = await API.get('/api/bootstrap');
    applyBoot(d);
    S.ready = true;
    renderAll();
    hideBootGate();
  } catch (err) {
    showBootError(err);
  }
}

export const NAV = [
  { id: 'manage', icon: 'folder-kanban', label: '项目管理' },
  { id: 'chat', icon: 'message-square', label: '对话' },
  { id: 'assets', icon: 'layers', label: '资产库' },
  { id: 'video', icon: 'film', label: '视频' },
  { id: 'confirm', icon: 'clapperboard', label: '成片确认' }
];

export function renderRail() {
  $('#rail').innerHTML = NAV.map(n => {
    const active = S.view === n.id;
    return `
      <button data-view="${n.id}" class="relative flex flex-col items-center gap-1 rounded-lg py-2.5 transition ${active ? 'bg-raise text-txt' : 'text-sub hover:bg-raise/60 hover:text-txt'}">
        <span class="absolute left-0 top-1/2 h-6 w-[2px] -translate-y-1/2 rounded-full ${active ? 'bg-amber' : 'bg-transparent'}"></span>
        <i data-lucide="${n.icon}" class="h-[17px] w-[17px] ${active ? 'text-amber' : ''}"></i>
        <span class="text-[10px] leading-none ${active ? 'font-medium' : ''}">${n.label}</span>
      </button>`;
  }).join('');
}

/* 当前项目 / 子项目 */

export function renderRecent() {
  const host = $('#recentList');
  if (!host) return;
  const q = ($('#projSearch') && $('#projSearch').value || '').trim().toLowerCase();
  const list = S.projects.filter(p => !p.archived && (!q || p.name.toLowerCase().includes(q)));
  host.innerHTML = (list.length ? list.map(p => `
    <button data-action="switch-project" data-id="${p.id}" class="flex w-full items-center gap-2.5 px-3 py-2 text-left transition hover:bg-raise/70">
      <span class="h-6 w-6 shrink-0 rounded-[5px]" style="background:${p.cover.grad}"></span>
      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-1.5">
          <span class="truncate text-[12px] text-txt">${esc(p.name)}</span>
          <span class="shrink-0 rounded-[3px] border border-line px-1 py-[1px] text-[8.5px] text-dim">${esc(p.kind)}</span>
        </span>
        <span class="mt-[2px] block truncate text-[9.5px] text-dim">${p.subsCount} 个子项目 · ${p.shots} 个镜头</span>
      </span>
      ${S.current.projectId === p.id ? ic('check', 'h-3 w-3 shrink-0 text-amber') : ''}
    </button>`).join('') : `<div class="px-4 py-5 text-center text-[10.5px] text-dim">${q ? '没有匹配的项目' : '还没有项目'}</div>`) + `
    <div class="border-t border-line p-1">
      <button data-action="project-new" class="flex w-full items-center gap-2 rounded-md px-2.5 py-[7px] text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">${ic('plus', 'h-3.5 w-3.5')}新建项目</button>
      <button data-action="sub-new" class="flex w-full items-center gap-2 rounded-md px-2.5 py-[7px] text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">${ic('git-branch', 'h-3.5 w-3.5')}新建子项目</button>
      <button data-action="projects-all" class="flex w-full items-center gap-2 rounded-md px-2.5 py-[7px] text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">${ic('arrow-right', 'h-3.5 w-3.5')}全部项目</button>
    </div>`;
  paint(host);
}

export const RENDER = {
  manage: renderManage,
  chat: renderChat,
  assets: renderAssets,
  video: renderVideo,
  confirm: renderConfirm
};

export function switchView(id) {
  S.view = id;
  const root = $('#viewRoot');
  $$('.view', root).forEach(v => v.classList.remove('is-active'));
  const el = $(`.view[data-view="${id}"]`, root);
  if (el) el.classList.add('is-active');
  renderRail();
  paint($('#rail'));
  if (id === 'chat') {
    scrollChatToBottom();
    $$('#chatThread img').forEach(img => { if (!img.complete) img.addEventListener('load', scrollChatToBottom); });
  }
}

export function mountView(id) {
  const el = $(`.view[data-view="${id}"]`, $('#viewRoot'));
  if (!el) return;
  el.innerHTML = RENDER[id]();
  paint(el);
  if (id === 'assets') { renderAssetDrawer(); renderBatchBar(); }
  if (id === 'chat') scrollChatToBottom();
}

export function renderAllViews() {
  NAV.forEach(n => mountView(n.id));
}

export function renderAll() {
  const root = $('#viewRoot');
  root.innerHTML = NAV.map(n => `<section class="view" data-view="${n.id}"></section>`).join('');
  renderRail();
  renderAllViews();
  switchView(S.view);
  renderRecent();
}

export function openSwitcher() {
  $('#switcherPanel').classList.remove('hidden');
  $('#switcherBtn').setAttribute('aria-expanded', 'true');
  renderRecent();
  paint($('#switcherPanel'));
}
export function closeSwitcher() {
  const p = $('#switcherPanel');
  if (!p || p.classList.contains('hidden')) return;
  p.classList.add('hidden');
  $('#switcherBtn').setAttribute('aria-expanded', 'false');
}
