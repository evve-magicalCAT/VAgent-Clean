/* Vagent · 弹窗、迁移浮层、表单
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, API, S, esc, ic, paint, toast } from './core.js';
/* ---------- 4.8 弹窗 ---------- */
export function ensureModalHost() {
  if ($('#modalMask')) return;
  const el = document.createElement('div');
  el.id = 'modalMask';
  el.className = 'absolute inset-0 z-[70] hidden bg-[#07080A]/60 backdrop-blur-[1px]';
  el.innerHTML = `<div id="modalHost" class="absolute left-1/2 top-1/2 max-h-[calc(100%-64px)] w-[560px] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[12px] border border-line2 bg-[#101114] shadow-[0_40px_100px_-30px_rgba(0,0,0,.98)]"></div>`;
  $('#frame').appendChild(el);
}
export function openModal(html, width = '560px') {
  ensureModalHost();
  const host = $('#modalHost');
  host.style.width = width + 'px';
  host.innerHTML = html;
  $('#modalMask').classList.remove('hidden');
  paint(host);
}
export function closeModal() {
  const m = $('#modalMask');
  if (m) m.classList.add('hidden');
}
export const modalHead = (icon, title, sub = '') => `
  <div class="flex items-center gap-2 border-b border-line px-4 py-3">
    <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border border-line bg-raise">${ic(icon, 'h-3.5 w-3.5 text-amber')}</span>
    <h3 class="text-[13px] font-medium">${esc(title)}</h3>
    ${sub ? `<span class="truncate text-[10px] text-dim">${esc(sub)}</span>` : ''}
    <button data-action="modal-close" class="ml-auto text-dim transition hover:text-txt" aria-label="关闭">${ic('x', 'h-4 w-4')}</button>
  </div>`;
export const modalFoot = (cancelLabel, confirmLabel, action, id = '', danger = false) => `
  <div class="flex items-center justify-end gap-2 border-t border-line bg-panel/60 px-4 py-3">
    <button data-action="modal-close" class="rounded-lg border border-line2 px-3 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">${esc(cancelLabel)}</button>
    <button data-action="${action}" ${id ? `data-id="${id}"` : ''} class="${danger ? 'bg-danger text-white' : 'grad-amber text-[#1B0E05]'} flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-medium">${esc(confirmLabel)}</button>
  </div>`;
export const inputCls = 'mt-1.5 w-full rounded-md border border-line2 bg-[#0C0D10] px-2.5 py-2 text-[12px] text-txt placeholder:text-dim';
export const labelCls = 'text-[10.5px] text-sub';

export function projectModal(p) {
  openModal(`
    ${modalHead(p ? 'pencil-line' : 'folder-plus', p ? '编辑项目' : '新建项目', p ? p.name : '项目是一切的起点')}
    <div class="px-4 py-3">
      <label class="block ${labelCls}">项目名<input id="mName" value="${esc(p ? p.name : '')}" placeholder="输入项目名称" class="${inputCls}" /></label>
      <label class="mt-3 block ${labelCls}">项目概括
        <textarea id="mDesc" rows="2" placeholder="一句话描述这部片（可选）" class="${inputCls} min-h-[64px] resize-none">${esc(p ? p.desc : '')}</textarea>
      </label>
      <p class="mt-3 flex items-start gap-1.5 rounded-md border border-line bg-card px-2.5 py-2 text-[10px] leading-relaxed text-dim">
        ${ic('info', 'mt-[1px] h-3 w-3 shrink-0')}新建的项目会自动带一个子项目；封面自动取资产库最新一张设定图，并显示这里的项目概括。
      </p>
    </div>
    ${modalFoot('取消', p ? '保存' : '创建项目', 'project-save', p ? p.id : '')}
  `);
}

export function subModal() {
  openModal(`
    ${modalHead('git-branch', '新建子项目', S.current.name || '')}
    <div class="px-4 py-3">
      <label class="block ${labelCls}">名称<input id="mSubName" placeholder="给这一集起个名字" class="${inputCls}" /></label>
      <p class="mt-3 flex items-start gap-1.5 rounded-md border border-line bg-card px-2.5 py-2 text-[10px] leading-relaxed text-dim">
        ${ic('git-branch', 'mt-[1px] h-3 w-3 shrink-0')}子项目默认继承父项目资产，也可以拥有自己的私有资产。
      </p>
    </div>
    ${modalFoot('取消', '创建子项目', 'sub-save')}
  `);
}

export function assetModal() {
  openModal(`
    ${modalHead('layers', '新建资产', '角色 / 场景 / 风格')}
    <div class="px-4 py-3">
      <label class="block ${labelCls}">名称<input id="mAssetName" placeholder="输入资产名称" class="${inputCls}" /></label>
      <div class="mt-3 grid grid-cols-2 gap-3">
        <label class="block ${labelCls}">类型
          <select id="mAssetType" class="${inputCls}">
            <option>角色</option><option>场景</option><option>风格</option><option>其他</option>
          </select>
        </label>
        <label class="block ${labelCls}">归属
          <select id="mAssetScope" class="${inputCls}">
            <option value="private">本项目私有</option>
            <option value="inherit">项目级（所有子项目继承）</option>
          </select>
        </label>
      </div>
      <label class="mt-3 block ${labelCls}">提示词<textarea id="mAssetDesc" rows="4" placeholder="外貌、服装、神态、光线……" class="${inputCls}"></textarea></label>
      <label class="mt-3 flex items-center gap-2 text-[11px] text-sub">
        <input id="mAssetLocked" type="checkbox" class="h-3.5 w-3.5 accent-[#F5813C]" />创建后立即锁定（不可被 AI 改写）
      </label>
    </div>
    ${modalFoot('取消', '创建资产', 'asset-save-new')}
  `);
}

export function confirmModal({ icon = 'alert-triangle', title, desc, label, action, id, danger = true }) {
  openModal(`
    ${modalHead(icon, title)}
    <div class="px-4 py-4">
      <p class="text-[12px] leading-relaxed text-sub">${esc(desc)}</p>
      <p class="mt-1.5 text-[10px] text-dim">这个操作不可撤销。</p>
    </div>
    ${modalFoot('取消', label, action, id, danger)}
  `, '460px');
}

/* 迁移浮层（复用页面里已有的 #migrateModal） */
export async function openMigrate(ids, mode = 'copy') {
  if (!ids || !ids.length) return toast('先选择要迁移的资产', 'warn');
  let all;
  try {
    all = (await API.get('/api/assets?scope=all')).assets || [];
  } catch (err) {
    return toast('读取资产失败：' + err.message, 'warn');
  }
  const source = S.assets.find(a => ids.includes(a.id)) || all.find(a => ids.includes(a.id));
  S.migrate.ids = ids.slice();
  S.migrate.mode = mode;
  S.migrate.conflicts = {};
  S.migrate.allAssets = all;
  const targets = S.projects.filter(p => p.id !== (source ? source.projectId : S.current.projectId));
  S.migrate.target = targets.length ? targets[0].id : '';
  ids.forEach(id => {
    const me = all.find(a => a.id === id);
    const dup = me && S.migrate.target
      ? all.find(a => a.projectId === S.migrate.target && a.name === me.name)
      : null;
    S.migrate.conflicts[id] = dup ? 'keep' : 'keep';
    if (me && me.locked) S.migrate.conflicts[id + ':lock'] = 'lock';
  });
  $('#migrateMask').classList.remove('hidden');
  $('#migrateModal').classList.remove('hidden');
  renderMigrate();
}

export function migrateTargetAssets() {
  return (S.migrate.allAssets || []).filter(a => a.projectId === S.migrate.target);
}

export function renderMigrate() {
  const ids = S.migrate.ids;
  const mode = S.migrate.mode;
  const target = S.projects.find(p => p.id === S.migrate.target);
  const tAssets = migrateTargetAssets();
  const all = S.migrate.allAssets || [];
  let add = 0, overwrite = 0, skip = 0;

  const rows = ids.map(id => {
    const a = all.find(x => x.id === id) || { name: id, type: '资产' };
    const dup = tAssets.find(x => x.name === a.name);
    const v = S.migrate.conflicts[id] || 'keep';
    if (dup) {
      if (v === 'overwrite') overwrite++;
      else if (v === 'skip') skip++;
      else add++;
    } else add++;

    return `
      <div class="rounded-lg border border-line bg-card px-2.5 py-2">
        <div class="flex items-center gap-2">
          ${ic(a.type === '角色' ? 'user-round' : a.type === '场景' ? 'store' : 'box', 'h-3 w-3 shrink-0 text-sub')}
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-1.5 text-[11.5px] text-txt">
              <span class="truncate">${esc(a.name)}</span>
              ${a.locked ? `<span class="flex shrink-0 items-center gap-1 rounded-[3px] bg-amber/10 px-1 py-[1px] text-[8.5px] text-amber2">${ic('lock', 'h-[7px] w-[7px]')}已锁定</span>` : ''}
            </p>
            <p class="mt-[2px] text-[9.5px] text-dim">${dup ? '目标项目已存在同名资产，需要决定怎么处理' : '无冲突 · 目标项目没有同名资产'}</p>
          </div>
          ${dup ? `<div class="flex shrink-0 items-center rounded-[6px] border border-line2 bg-panel p-0.5 text-[9.5px]">
            ${[['keep', '保留两者'], ['overwrite', '覆盖'], ['skip', '跳过']].map(([val, label]) => `
              <button data-action="migrate-conflict" data-id="${id}" data-value="${val}" class="rounded-[4px] px-1.5 py-[3px] transition ${v === val ? 'bg-raise text-txt' : 'text-sub hover:text-txt'}">${label}</button>`).join('')}
          </div>` : `<span class="flex shrink-0 items-center gap-1 rounded-[4px] border border-ok/30 bg-ok/10 px-1.5 py-[3px] text-[9.5px] text-ok">${ic('check', 'h-2.5 w-2.5')}直接迁移</span>`}
        </div>
        ${a.locked ? `<p class="mt-1.5 flex items-center gap-1 border-t border-line/70 pt-1.5 text-[9px] leading-[1.5] text-dim">
          ${ic('info', 'h-2.5 w-2.5 shrink-0')}锁定策略：
          <button data-action="migrate-lock" data-id="${id}" data-value="lock" class="rounded px-1 ${S.migrate.conflicts[id + ':lock'] !== 'unlock' ? 'text-amber2' : 'text-dim'}">保持锁定</button>
          <span class="text-dim">/</span>
          <button data-action="migrate-lock" data-id="${id}" data-value="unlock" class="rounded px-1 ${S.migrate.conflicts[id + ':lock'] === 'unlock' ? 'text-amber2' : 'text-dim'}">迁移后解锁</button>
        </p>` : ''}
      </div>`;
  }).join('');

  const targetOptions = S.projects.filter(p => p.id !== (S.current.projectId)).map(p => `
    <button data-action="migrate-target" data-id="${p.id}" class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11.5px] transition ${p.id === S.migrate.target ? 'bg-raise text-txt' : 'text-sub hover:bg-raise/60'}">
      <span class="h-4 w-4 shrink-0 rounded-[3px]" style="background:${p.cover.grad}"></span>
      <span class="truncate">${esc(p.name)}</span>
      <span class="ml-auto shrink-0 text-[9.5px] text-dim">${p.subsCount} 个子项目 · ${p.assets} 项资产</span>
      ${p.id === S.migrate.target ? ic('check', 'h-3 w-3 text-amber') : ''}
    </button>`).join('');

  $('#migrateModal').innerHTML = `
    <div class="flex items-center gap-2 border-b border-line px-4 py-3">
      <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border border-line bg-raise">${ic('arrow-right-left', 'h-3.5 w-3.5 text-amber')}</span>
      <h3 class="text-[13px] font-medium">迁移 ${ids.length} 项资产</h3>
      <span class="flex items-center gap-1 rounded-[4px] border border-line px-1.5 py-[1px] text-[9.5px] text-dim">${ic('box', 'h-2.5 w-2.5')}${esc(S.current.name || '当前项目')} / ${esc(S.current.sub || '未分集')}</span>
      <button data-action="migrate-close" class="ml-auto text-dim transition hover:text-txt" aria-label="关闭">${ic('x', 'h-4 w-4')}</button>
    </div>

    <div class="px-4 py-3">
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-sub">1 · 目标项目</span>
        <span class="h-px flex-1 bg-line"></span>
      </div>
      <div class="mt-2 max-h-[132px] overflow-y-auto hide-scroll rounded-lg border border-line2 bg-card p-1">
        ${S.projects.length <= 1 ? `<div class="px-2 py-3 text-center text-[10.5px] text-dim">只有一个项目，先新建一个再迁移</div>` : targetOptions}
      </div>
      ${target ? `<p class="mt-1.5 flex items-center gap-1 text-[9.5px] text-dim">${ic('check', 'h-2.5 w-2.5 text-ok')}已选择「${esc(target.name)}」· 共 ${target.subsCount} 个子项目</p>` : ''}

      <div class="mt-3 flex items-center gap-2">
        <span class="text-[11px] text-sub">2 · 方式</span>
        <span class="h-px flex-1 bg-line"></span>
      </div>
      <div class="mt-2 grid grid-cols-2 items-stretch gap-2.5">
        <button data-action="migrate-mode" data-id="copy" class="rounded-lg border p-2.5 text-left transition ${mode === 'copy' ? 'border-amber/50 bg-amber/8' : 'border-line bg-card hover:border-line2'}">
          <div class="flex items-center gap-1.5">
            ${ic('copy', `h-3.5 w-3.5 ${mode === 'copy' ? 'text-amber2' : 'text-sub'}`)}
            <span class="text-[12px] font-medium ${mode === 'copy' ? 'text-amber2' : 'text-txt'}">复制</span>
            <span class="ml-auto flex h-3.5 w-3.5 items-center justify-center rounded-full ${mode === 'copy' ? 'bg-amber2' : 'border border-line2'}">
              ${mode === 'copy' ? ic('check', 'h-2.5 w-2.5 text-[#1B0E05]') : ''}
            </span>
          </div>
          <p class="mt-1 text-[10px] leading-[1.55] text-sub">原项目保留，目标项目得到副本，之后两边各自独立。</p>
        </button>
        <button data-action="migrate-mode" data-id="move" class="rounded-lg border p-2.5 text-left transition ${mode === 'move' ? 'border-amber/50 bg-amber/8' : 'border-line bg-card hover:border-line2'}">
          <div class="flex items-center gap-1.5">
            ${ic('scissors', `h-3.5 w-3.5 ${mode === 'move' ? 'text-amber2' : 'text-sub'}`)}
            <span class="text-[12px] font-medium ${mode === 'move' ? 'text-amber2' : 'text-txt'}">移动</span>
            <span class="ml-auto flex h-3.5 w-3.5 items-center justify-center rounded-full ${mode === 'move' ? 'bg-amber2' : 'border border-line2'}">
              ${mode === 'move' ? ic('check', 'h-2.5 w-2.5 text-[#1B0E05]') : ''}
            </span>
          </div>
          <p class="mt-1 text-[10px] leading-[1.55] text-sub">从原项目移除，原项目不再保留这 ${ids.length} 项。</p>
        </button>
      </div>

      <div class="mt-2 rounded-lg border px-2.5 py-2 ${mode === 'move' ? 'border-danger/30 bg-danger/10' : 'border-line bg-card'}">
        <p class="flex items-start gap-1.5 text-[9.5px] leading-[1.55] ${mode === 'move' ? 'text-danger' : 'text-dim'}">
          ${ic(mode === 'move' ? 'alert-triangle' : 'shield-check', 'mt-[1px] h-2.5 w-2.5 shrink-0')}
          <span>${mode === 'move'
            ? '移动会切断原项目的引用：原项目里用到这些资产的镜头会失去设定，需要重新绑定。'
            : '复制不会影响原项目：原项目的镜头引用保持不变，副本在目标项目里独立演进。'}</span>
        </p>
      </div>

      <div class="mt-3 flex items-center gap-2">
        <span class="text-[11px] text-sub">3 · 冲突处理</span>
        <span class="rounded-[4px] border border-line px-1 py-[1px] text-[9px] text-dim">${overwrite || skip ? '按你的选择处理' : '无冲突'}</span>
        <span class="h-px flex-1 bg-line"></span>
      </div>
      <div class="mt-2 flex max-h-[190px] flex-col gap-1.5 overflow-y-auto hide-scroll">${rows}</div>
    </div>

    <div class="flex items-center gap-3 border-t border-line bg-panel/60 px-4 py-3">
      <p class="text-[10.5px] text-sub">将新增 <span class="text-txt">${add} 项</span>、覆盖 <span class="text-txt">${overwrite} 项</span>、跳过 <span class="text-txt">${skip} 项</span></p>
      <div class="ml-auto flex items-center gap-2">
        <button data-action="migrate-close" class="rounded-lg border border-line2 px-3 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">取消</button>
        <button data-action="migrate-confirm" ${S.migrate.target ? '' : 'disabled'} class="grad-amber flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-medium text-[#1B0E05] ${S.migrate.target ? '' : 'opacity-60'}">
          ${ic('arrow-right-left', 'h-3.5 w-3.5')}确认迁移
        </button>
      </div>
    </div>`;
  paint($('#migrateModal'));
}

export function closeMigrate() {
  S.migrate.open = false;
  $('#migrateMask').classList.add('hidden');
  $('#migrateModal').classList.add('hidden');
}

/* ---------- 4.9 单图灯箱：双击任意图片放大 ---------- */
export function ensureLightbox() {
  if ($('#lightbox')) return;
  const el = document.createElement('div');
  el.id = 'lightbox';
  el.className = 'absolute inset-0 z-[95] hidden items-center justify-center bg-[#07080A]/95 p-10';
  el.setAttribute('data-lightbox-close', '1');
  el.innerHTML = `
    <img id="lightboxImg" alt="" class="max-h-full max-w-full rounded-[6px] object-contain shadow-[0_40px_100px_-30px_rgba(0,0,0,.98)]" />
    <button type="button" data-lightbox-close class="absolute right-5 top-5 flex h-8 w-8 items-center justify-center rounded-[8px] border border-line2 bg-panel/80 text-sub transition hover:text-txt" aria-label="关闭大图">${ic('x', 'h-4 w-4')}</button>
    <p class="absolute bottom-3 left-1/2 -translate-x-1/2 text-[10px] text-dim">点击任意处关闭</p>`;
  $('#frame').appendChild(el);
}

export function openLightbox(src, alt = '') {
  if (!src) return;
  ensureLightbox();
  const box = $('#lightbox');
  const img = $('#lightboxImg');
  img.src = src;
  img.alt = alt;
  box.classList.remove('hidden');
  box.classList.add('flex');
  paint(box);
}

export function closeLightbox() {
  const box = $('#lightbox');
  if (!box) return;
  box.classList.add('hidden');
  box.classList.remove('flex');
  const img = $('#lightboxImg');
  if (img) img.src = '';
}

export function lightboxOpen() {
  const box = $('#lightbox');
  return !!box && !box.classList.contains('hidden');
}
