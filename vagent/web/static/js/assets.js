/* Vagent · 资产库视图与编辑抽屉
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, S, clamp, currentProject, emptyBlock, esc, ic, paint } from './core.js';
/* ---------- 4.3 资产库 ---------- */
function versionedUrl(url, version) {
  if (!url || !version) return url;
  const stamp = String(version).replace(/\D/g, '');
  if (!stamp) return url;
  return url + (url.includes('?') ? '&' : '?') + 'v=' + stamp;
}

export function previewEl(p, fit = 'cover', version = '') {
  if (p.kind === 'img') {
    const fitClass = fit === 'contain' ? 'object-contain' : 'object-cover';
    return `<img src="${esc(versionedUrl(p.url, version))}" alt="${esc(p.label || '生成图')}" loading="lazy"
      class="absolute inset-0 h-full w-full ${fitClass}"
      onerror="this.style.display='none'">`;
  }
  if (p.kind === 'fig') return `<svg class="h-[86px] w-[56px]" style="color:#4A525C"><use href="#${p.sym}"/></svg>`;
  if (p.kind === 'scn') return `<svg class="h-[76px] w-[84px]" style="color:#454D57"><use href="#${p.sym}"/></svg>`;
  return `<div class="absolute inset-0" style="background:${p.bg || 'linear-gradient(160deg,#2A323A,#0E1216)'}"></div>`;
}

export function previewTiles(a) {
  const pv = (a.preview && a.preview.length) ? a.preview : null;
  const single = a.type === '场景';
  if (!pv) {
    if (single) {
      return `<div class="col-span-3 flex h-full items-center justify-center">
        <span class="text-[9px] text-dim">还没有概念图</span>
      </div>`;
    }
    return ['正面', '侧面', '背面'].map(label => `
      <div class="relative flex items-end justify-center pb-2">
        <span class="mb-4 text-[9px] text-dim">${label}</span>
      </div>`).join('');
  }
  if (single) {
    const p = pv[0];
    const tag = p.kind === 'img' ? 'rounded-[3px] bg-black/55 px-1 py-[1px] text-txt' : 'text-dim';
    return `<div class="relative col-span-3 flex items-end justify-center">
      ${previewEl(p, 'cover', a.updatedAt)}
      <span class="absolute bottom-1 left-1.5 text-[9px] ${tag}">${esc(p.label || '概念图')}</span>
    </div>`;
  }
  if (pv.length === 1) {
    const p = pv[0];
    const tag = p.kind === 'img' ? 'rounded-[3px] bg-black/55 px-1 py-[1px] text-txt' : 'text-dim';
    return `<div class="relative col-span-3 flex items-end justify-center">
      ${previewEl(p, 'cover', a.updatedAt)}
      <span class="absolute bottom-1 left-1.5 text-[9px] ${tag}">${esc(p.label || '设定图')}</span>
    </div>`;
  }
  return pv.slice(0, 3).map(p => {
    // 真图底下的标签要加暗底，否则灰字压在白底照片上看不清；占位图保持原样
    const tag = p.kind === 'img' ? 'rounded-[3px] bg-black/55 px-1 py-[1px] text-txt' : 'text-dim';
    return `
    <div class="relative flex items-end justify-center pb-2">
      ${previewEl(p, 'cover', a.updatedAt)}
      <span class="absolute bottom-1 left-1.5 text-[9px] ${tag}">${esc(p.label)}</span>
    </div>`;
  }).join('');
}

export function assetCard(a) {
  const sel = S.selected.has(a.id);
  const archived = !!a.archived;

  if (a.ai === 'generating') {
    return `
      <article class="relative overflow-hidden rounded-[10px] border border-line bg-card">
        <div class="relative h-[118px] bg-[#0C0D10]">
          <div class="grid h-full grid-cols-3 divide-x divide-line/60">
            <div class="skeleton"></div><div class="skeleton" style="animation-delay:.2s"></div><div class="skeleton" style="animation-delay:.4s"></div>
          </div>
          <div class="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-base/70">
            ${ic('loader-circle', 'h-4 w-4 animate-spin text-amber')}
            <p class="text-[10.5px] text-txt">正在生成三视图 ${a.progress || 0}%</p>
            <div class="h-[3px] w-[104px] overflow-hidden rounded-full bg-line"><div class="grad-amber h-full rounded-full" style="width:${a.progress || 0}%"></div></div>
          </div>
        </div>
        <div class="px-3 py-2.5">
          <div class="flex items-center gap-1.5">
            <h3 class="truncate text-[12.5px] font-medium text-txt">${esc(a.name)}</h3>
            <span class="shrink-0 rounded-[4px] border border-line px-1 py-[1px] text-[9px] text-dim">${esc(a.type)}</span>
          </div>
          <p class="mt-1 line-clamp-2 text-[10.5px] leading-[1.6] text-dim">${esc(a.desc || '还没有提示词')}</p>
        </div>
      </article>`;
  }

  return `
    <article data-action="asset-card" data-id="${a.id}" class="group relative cursor-pointer overflow-hidden rounded-[10px] border ${sel ? 'border-amber/45 ring-1 ring-amber/25' : archived ? 'border-line/60 opacity-80' : 'border-line hover:border-line2'} bg-card">
      <div class="group/preview relative grid h-[118px] grid-cols-3 divide-x divide-line/60 bg-[#0C0D10]">
        <button data-action="asset-check" data-id="${a.id}" class="absolute left-1.5 top-1.5 z-10 flex h-[15px] w-[15px] items-center justify-center rounded-[4px] shadow-[0_1px_5px_rgba(0,0,0,.7)] transition ${sel ? 'bg-amber text-[#1B0E05]' : 'border border-line2 bg-base/80 text-transparent opacity-0 group-hover:opacity-100'}">
          ${ic('check', 'h-[10px] w-[10px]')}
        </button>
        <span class="absolute bottom-1 right-1.5 z-10 flex items-center gap-1 rounded-[4px] border border-line2 bg-base/85 px-1.5 py-[2px] text-[9px] ${a.source === 'inherit' ? 'text-sub' : 'text-dim'}">
          ${ic(a.source === 'inherit' ? 'git-branch' : 'user-round', 'h-[8px] w-[8px]')}${a.source === 'inherit' ? '继承' : '私有'}
        </span>
        ${a.locked ? `<span class="absolute right-1.5 top-1.5 flex items-center gap-1 rounded-[4px] bg-amber/10 px-1.5 py-[2px] text-[9px] text-amber2">${ic('lock', 'h-[8px] w-[8px]')}已锁定</span>` : ''}
        ${previewTiles(a)}
        <div class="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex translate-y-full items-center border-t border-line2 bg-[#191A1F] opacity-0 transition duration-200 group-hover/preview:pointer-events-auto group-hover/preview:translate-y-0 group-hover/preview:opacity-100">
          <button data-action="asset-edit" data-id="${a.id}" class="flex flex-1 flex-col items-center gap-1 py-1.5 text-[9px] text-sub">${ic('pencil-line', 'h-3 w-3')}编辑</button>
          <span class="h-6 w-px bg-line"></span>
          <button data-action="asset-regen-preview" data-id="${a.id}" class="flex flex-1 flex-col items-center gap-1 py-1.5 text-[9px] text-sub">${ic('refresh-cw', 'h-3 w-3')}重生成</button>
          <span class="h-6 w-px bg-line"></span>
          <button data-action="asset-migrate" data-id="${a.id}" class="flex flex-1 flex-col items-center gap-1 py-1.5 text-[9px] text-amber2">${ic('arrow-right-left', 'h-3 w-3')}迁移</button>
          <span class="h-6 w-px bg-line"></span>
          <button data-action="asset-copy" data-id="${a.id}" class="flex flex-1 flex-col items-center gap-1 py-1.5 text-[9px] text-sub">${ic('copy', 'h-3 w-3')}复制</button>
          <span class="h-6 w-px bg-line"></span>
          <button data-action="asset-delete" data-id="${a.id}" class="flex flex-1 flex-col items-center gap-1 py-1.5 text-[9px] text-danger/90">${ic('trash-2', 'h-3 w-3')}删除</button>
        </div>
      </div>
      <div class="px-3 py-2.5">
        <div class="flex items-center gap-1.5">
          <h3 class="truncate text-[12.5px] font-medium text-txt">${esc(a.name)}</h3>
          <span class="shrink-0 rounded-[4px] border border-line px-1 py-[1px] text-[9px] text-dim">${esc(a.type)}</span>
          <span class="ml-auto flex shrink-0 items-center gap-1 text-[9.5px] text-dim">
            ${a.archived ? '已归档' : a.locked ? `${a.uses || 0} 个镜头在用` : `${ic('unlock', 'h-2.5 w-2.5')}可修改`}
          </span>
        </div>
        <p class="mt-1 line-clamp-2 min-h-[30px] text-[10.5px] leading-[1.6] text-sub">${a.desc ? esc(a.desc) : '<span class="text-dim">还没有提示词</span>'}</p>
        ${auditLine(a)}
        <div class="mt-2 flex items-center gap-1.5 rounded-md border border-line/70 bg-panel/50 px-1.5 py-1">
          ${a.locked
            ? `<span class="flex cursor-not-allowed items-center gap-1 rounded-[4px] border border-line px-1.5 py-[2px] text-[9.5px] text-dim opacity-55">${ic('sparkles', 'h-2.5 w-2.5')}AI 丰富描述</span>`
            : `<button data-action="asset-enrich" data-id="${a.id}" class="flex items-center gap-1 rounded-[4px] border border-line2 bg-raise px-1.5 py-[2px] text-[9.5px] text-sub transition hover:text-txt">${ic('sparkles', 'h-2.5 w-2.5 text-amber')}AI 丰富描述</button>`}
          <button data-action="asset-generate" data-id="${a.id}" class="ml-auto flex shrink-0 items-center gap-1 rounded-[4px] border border-amber/40 bg-amber/12 px-2 py-[3px] text-[9.5px] text-amber2 transition hover:bg-amber/20">
            ${ic('play', 'h-2.5 w-2.5')}开始生成
          </button>
        </div>
      </div>
    </article>`;
}

function auditLine(a) {
  // 出图后的体检结果只挂在卡片上提醒，不拦流程、不改资产状态
  const gaps = (S.assetAudit && S.assetAudit[a.id]) || [];
  if (!gaps.length) return '';
  return `<p class="mt-1 flex items-start gap-1 rounded-[5px] border border-amber/25 bg-amber/10 px-1.5 py-1 text-[9.5px] leading-[1.5] text-amber2">
    ${ic('triangle-alert', 'mt-[1px] h-2.5 w-2.5 shrink-0')}
    <span class="line-clamp-2">体检发现 ${gaps.length} 处要改：${esc(gaps[0])}</span>
  </p>`;
}

export function filteredAssets() {
  let list = S.assets.slice();
  if (S.assetType !== 'all') list = list.filter(a => a.type === S.assetType);
  if (S.assetStatus === 'locked') list = list.filter(a => a.locked);
  if (S.assetStatus === 'unlocked') list = list.filter(a => !a.locked);
  if (S.assetStatus === 'generating') list = list.filter(a => a.ai === 'generating');
  if (S.assetQuery) {
    const q = S.assetQuery.toLowerCase();
    list = list.filter(a => (a.name || '').toLowerCase().includes(q) || (a.desc || '').toLowerCase().includes(q));
  }
  return list;
}

export function renderAssetGrid() {
  const list = filteredAssets();
  const st = S.assetStats || { inherit: 0, locked: 0 };
  const cards = list.map(assetCard).join('') + `
    <button data-action="asset-new" class="flex h-[212px] flex-col items-center justify-center gap-2 rounded-[10px] border border-dashed border-line2 text-center transition hover:border-amber/40 hover:bg-card/60">
      <span class="flex h-8 w-8 items-center justify-center rounded-full border border-line2">${ic('plus', 'h-4 w-4 text-sub')}</span>
      <span class="text-[12px] text-sub">新建资产</span>
      <span class="px-8 text-[10px] leading-relaxed text-dim">手动填写提示词，或从最近的对话里提取</span>
    </button>`;

  const empty = S.assets.length === 0;
  return {
    html: `<div class="grid grid-cols-3 gap-3 pb-14">${empty ? `
      <div class="col-span-3">${emptyBlock({
        icon: 'layers', title: '资产库还是空的',
        desc: '把不可修改的设定（角色、场景、风格）存成资产并锁定，后续镜头会复用同一套描述。',
        action: 'asset-new', label: '新建资产'
      })}</div>` : cards}</div>`,
    summary: `${S.assets.length} 项资产 · ${st.inherit || 0} 项继承自父项目 · ${st.locked || 0} 项已锁定 · 显示 ${list.length} 项`
  };
}

export function renderAssets() {
  const grid = renderAssetGrid();
  const scopeBtn = (id, icon, label) => {
    const on = S.assetScope === id;
    return `<button data-action="asset-scope" data-id="${id}" class="flex items-center gap-1 rounded-[6px] px-2 py-[3px] text-[11px] transition ${on
      ? 'border border-amber/40 bg-amber/12 text-amber2' : 'text-sub hover:text-txt'}">${ic(icon, 'h-2.5 w-2.5')}${label}</button>`;
  };
  const typeBtn = (id, icon, label, count) => {
    const on = S.assetType === id;
    return `<button data-action="asset-type" data-id="${id}" class="flex items-center gap-2 rounded-lg px-2.5 py-2 text-[12.5px] transition ${on ? 'bg-raise text-txt' : 'text-sub hover:bg-raise/60 hover:text-txt'}">
      ${ic(icon, `h-3.5 w-3.5 ${on ? 'text-amber' : ''}`)}${label}
      <span class="ml-auto rounded-[4px] bg-panel px-1.5 py-[1px] text-[10px] ${on ? 'text-sub' : 'text-dim'}">${count}</span></button>`;
  };
  const statusRow = (id, icon, label, count) => `
    <button data-action="asset-status" data-id="${id}" class="flex w-full items-center gap-2 rounded-md px-1 py-[3px] text-left text-[12px] transition ${S.assetStatus === id ? 'text-amber2' : 'text-sub hover:text-txt'}">
      ${ic(icon, 'h-3 w-3')}${label}<span class="ml-auto text-[10px] text-dim">${count}</span></button>`;

  const proj = currentProject();
  const draftIds = S.pendingAssets || [];
  const draftBar = draftIds.length ? `
      <div class="mt-2.5 flex items-center gap-2 rounded-[10px] border border-amber/30 bg-amber/8 px-3 py-2">
        ${ic('clipboard-check', 'h-3.5 w-3.5 shrink-0 text-amber')}
        <span class="shrink-0 text-[11.5px] text-txt">已按分镜创建 ${draftIds.length} 项资产草稿</span>
        <span class="min-w-0 truncate text-[10px] text-dim">在右侧检查描述，改完点确认，再生成三视图</span>
        <button data-action="asset-confirm-drafts" class="grad-amber ml-auto flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1 text-[11.5px] font-medium text-[#1B0E05]">${ic('image-plus', 'h-3 w-3')}确认并生成设定图</button>
        <button data-action="asset-dismiss-drafts" class="shrink-0 rounded-lg border border-line2 px-2 py-1 text-[11px] text-sub transition hover:text-txt">暂不生成</button>
      </div>` : '';
  return `
  <div class="flex h-full min-h-0">
    <aside class="flex w-[188px] shrink-0 flex-col border-r border-line bg-[#0E0F12] py-4">
      <p class="px-4 text-[10px] tracking-[0.14em] text-dim">分类</p>
      <nav class="mt-2 flex flex-col gap-0.5 px-2">
        ${typeBtn('all', 'box', '全部', S.assets.length)}
        ${typeBtn('角色', 'user-round', '角色', S.assets.filter(a => a.type === '角色').length)}
        ${typeBtn('场景', 'store', '场景', S.assets.filter(a => a.type === '场景').length)}
        ${typeBtn('风格', 'palette', '风格', S.assets.filter(a => a.type === '风格').length)}
        ${typeBtn('其他', 'box', '其他', S.assets.filter(a => a.type === '其他').length)}
      </nav>
      <div class="mx-2 mt-4 border-t border-line pt-3">
        <p class="px-1 text-[10px] tracking-[0.14em] text-dim">状态</p>
        <div class="mt-2 flex flex-col gap-1 px-1">
          ${statusRow('all', 'layers', '全部状态', S.assets.length)}
          ${statusRow('locked', 'lock', '已锁定', S.assets.filter(a => a.locked).length)}
          ${statusRow('unlocked', 'unlock', '可修改', S.assets.filter(a => !a.locked).length)}
          ${statusRow('generating', 'loader', '生成中', S.assets.filter(a => a.ai === 'generating').length)}
        </div>
      </div>
      <div class="mx-2 mt-auto rounded-lg border border-line bg-card p-2.5">
        <p class="flex items-center gap-1.5 text-[10.5px] text-sub">${ic('lock', 'h-3 w-3 text-amber/80')}什么是锁定？</p>
        <p class="mt-1 text-[10px] leading-relaxed text-dim">锁定的设定在重新生成镜头时不会被改动，保证所有镜头里是同一件风衣、同一块门头。</p>
      </div>
    </aside>

    <main class="flex min-w-0 flex-1 flex-col px-5 py-4">
      <div class="flex items-center gap-2 text-[10.5px] text-dim">
        <span class="flex min-w-0 items-center gap-1.5">${ic('box', 'h-3 w-3')}<span class="truncate">${esc(proj ? proj.name : '还没有项目')}</span></span>
        ${ic('chevron-right', 'h-2.5 w-2.5 text-dim')}
        <span class="truncate">${esc(S.current.sub || '未分集')}</span>
        ${ic('chevron-right', 'h-2.5 w-2.5 text-dim')}
        <span class="text-sub">资产库</span>
        <div class="ml-auto flex items-center gap-2.5">
          <span class="text-[9.5px] text-dim">「本项目」= 当前子项目 + 继承的资产；跨项目操作请切到「全部项目」</span>
          <div class="flex h-7 items-center rounded-lg border border-line bg-card p-0.5">
            ${scopeBtn('project', 'folder', '本项目')}
            ${scopeBtn('inherit', 'git-branch', '含继承')}
            ${scopeBtn('all', 'layers', '全部项目')}
          </div>
        </div>
      </div>

      <div class="mt-2.5 flex items-center gap-3">
        <div>
          <h2 class="text-[20px] font-semibold leading-none tracking-tight">资产库</h2>
          <p id="assetSummary" class="mt-1.5 text-[11px] text-dim">${grid.summary}</p>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <label class="flex h-8 w-[196px] items-center gap-2 rounded-lg border border-line bg-card px-2.5">
            ${ic('search', 'h-3.5 w-3.5 text-dim')}
            <input id="assetSearch" type="text" value="${esc(S.assetQuery)}" placeholder="搜索名称或提示词" class="w-full bg-transparent text-[12px] text-txt placeholder:text-dim" />
          </label>
          <button data-action="asset-new" class="grad-amber flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium text-[#1B0E05]">${ic('plus', 'h-3.5 w-3.5')}新建资产</button>
        </div>
      </div>

      ${draftBar}

      <div class="hide-scroll mt-3 min-h-0 flex-1 overflow-y-auto">
        <div id="assetGrid">${grid.html}</div>
      </div>

      <div id="batchBar" class="pointer-events-none absolute bottom-3 left-[204px] z-30"></div>
    </main>

    <aside id="assetDrawer" class="flex w-[392px] shrink-0 flex-col overflow-hidden border-l border-line2 bg-[#0E0F12]"></aside>
  </div>`;
}

export function renderAssetDrawer() {
  const host = $('#assetDrawer');
  if (!host) return;
  const a = S.assets.find(x => x.id === S.editingAsset);
  if (!a) {
    host.innerHTML = `
      <div class="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
        ${ic('pencil-line', 'h-3.5 w-3.5 text-dim')}
        <span class="text-[12.5px] font-medium text-sub">编辑资产</span>
      </div>
      <div class="flex flex-1 flex-col items-center justify-center gap-2 px-8 text-center">
        <span class="flex h-10 w-10 items-center justify-center rounded-full border border-line2 bg-raise">${ic('mouse-pointer-click', 'h-4 w-4 text-dim')}</span>
        <p class="text-[12px] text-sub">还没有选择资产</p>
        <p class="text-[10.5px] leading-relaxed text-dim">点资产卡片的「编辑」，或直接点卡片，这里会显示提示词与结构化属性。</p>
      </div>`;
    return;
  }
  const aiPending = S.aiPending && S.aiPending.assetId === a.id ? S.aiPending : null;
  host.innerHTML = `
    <div class="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
      ${ic('pencil-line', 'h-3.5 w-3.5 text-amber')}
      <span class="text-[12.5px] font-medium">编辑资产</span>
      <span class="max-w-[110px] truncate rounded-[4px] border border-line px-1.5 py-[1px] text-[10px] text-sub">${esc(a.name)}</span>
      <span class="flex shrink-0 items-center gap-1 rounded-[4px] border border-line px-1.5 py-[2px] text-[9.5px] text-sub">
        ${ic(a.locked ? 'lock' : 'unlock', 'h-[8px] w-[8px]')}${a.locked ? '已锁定' : '可修改'}
      </span>
      <span class="ml-auto flex shrink-0 items-center gap-1 text-[9.5px] text-dim">${ic('link-2', 'h-2.5 w-2.5')}${a.refShots.length} 个镜头在用</span>
      <button data-action="asset-close" class="text-dim transition hover:text-txt">${ic('x', 'h-3.5 w-3.5')}</button>
    </div>

    <div class="hide-scroll min-h-0 flex-1 overflow-y-auto px-4 py-3.5">
      <div class="relative overflow-hidden rounded-lg border border-line2 bg-[#0C0D10]">
        <div class="grid h-[86px] grid-cols-3 divide-x divide-line/70">${previewTiles(a)}</div>
        <button data-action="asset-fullscreen" data-id="${a.id}" class="absolute right-2 top-2 flex items-center gap-1 rounded-md border border-line2 bg-base/80 px-1.5 py-[3px] text-[9px] text-sub backdrop-blur transition hover:border-amber/45 hover:text-txt">
          ${ic('maximize-2', 'h-2.5 w-2.5')}全屏
        </button>
      </div>

      <div class="mt-3.5">
        <label class="block text-[11px] text-sub">${a.type === '角色' ? '角色名称' : '资产名称'}
          <input data-asset-name="${a.id}" value="${esc(a.name)}" placeholder="给这个${a.type === '角色' ? '角色' : '资产'}命名" class="mt-1.5 w-full rounded-lg border border-line2 bg-card px-2.5 py-2 text-[11.5px] text-txt placeholder:text-dim outline-none transition focus:border-amber/45" />
        </label>

        <div class="mt-3.5">
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-sub">提示词</span>
          <span class="rounded-[4px] border border-line px-1 py-[1px] text-[9px] text-dim">影响三视图</span>
          <div class="ml-auto flex items-center gap-1.5">
            <button data-action="asset-from-chat" class="flex items-center gap-1 rounded-md border border-line bg-raise px-1.5 py-[4px] text-[10px] text-sub transition hover:border-line2 hover:text-txt">
              ${ic('message-square-dashed', 'h-2.5 w-2.5')}从对话中提取
            </button>
            <button data-action="asset-enrich" data-id="${a.id}" ${a.locked ? 'disabled' : ''} class="flex items-center gap-1 rounded-md border border-line2 bg-raise px-1.5 py-[4px] text-[10px] ${a.locked ? 'cursor-not-allowed text-dim opacity-55' : 'text-txt transition hover:border-amber/45 hover:text-amber2'}">
              ${ic('sparkles', 'h-2.5 w-2.5 text-amber')}AI 丰富描述
            </button>
          </div>
        </div>

        <div class="mt-1.5 rounded-lg border border-line2 bg-card p-2.5">
          <textarea rows="4" data-asset-prompt="${a.id}" placeholder="描述这个角色的外观、服装、神态……" class="w-full resize-none bg-transparent text-[11.5px] leading-[1.7] text-txt placeholder:text-dim">${esc(a.desc)}</textarea>
          <div class="mt-1.5 flex items-center justify-between border-t border-line/70 pt-1.5">
            <span class="text-[9px] text-dim">修改后 700ms 自动保存</span>
            <span class="text-[9px] text-dim">${(a.desc || '').length} 字</span>
          </div>
        </div>
        </div>

        ${aiPending ? `
        <div class="mt-1.5 rounded-md border border-amber/25 bg-amber/8 px-2.5 py-2">
          <div class="flex items-start gap-1.5">
            ${ic('git-compare', 'mt-[2px] h-3 w-3 shrink-0 text-amber/80')}
            <p class="min-w-0 flex-1 text-[10px] leading-[1.55] text-sub">待采纳的扩写：<span class="text-txt">${esc(aiPending.previewText)}</span></p>
            <div class="flex shrink-0 items-center gap-1.5">
              <button data-action="asset-ai-accept" class="rounded-md border border-amber/40 bg-amber/12 px-2 py-[3px] text-[10px] text-amber2 transition hover:bg-amber/20">采纳</button>
              <button data-action="asset-ai-revert" class="rounded-md border border-line2 px-2 py-[3px] text-[10px] text-sub transition hover:text-txt">撤销</button>
            </div>
          </div>
          <div class="mt-1.5 flex items-center gap-2 border-t border-line/70 pt-1.5 text-[9px]">
            <button data-action="asset-original" class="text-sub underline decoration-line2 underline-offset-2 transition hover:text-txt">查看原描述</button>
            <button data-action="asset-ai-remove" class="text-dim transition hover:text-danger">还原原描述</button>
          </div>
        </div>` : ''}

        <div class="mt-1.5 rounded-md border border-line bg-card px-2.5 py-2">
          <div class="flex items-center gap-1.5">
            ${ic('tag', 'h-3 w-3 text-sub')}
            <span class="text-[10.5px] text-sub">风格标签</span>
            <button data-action="asset-tag-add" data-id="${a.id}" class="ml-auto rounded-md border border-dashed border-line2 px-2 py-[2px] text-[9.5px] text-dim transition hover:border-amber/40 hover:text-sub">+ 添加</button>
          </div>
          <div class="mt-1.5 flex flex-wrap gap-1">
            ${(a.tags && a.tags.length) ? a.tags.map((t, i) => `
              <span class="flex items-center gap-1 rounded-md border border-line2 bg-raise px-2 py-1 text-[10.5px] text-txt">${esc(t)}<button data-action="asset-tag-del" data-id="${a.id}" data-index="${i}" class="text-dim hover:text-danger">${ic('x', 'h-2.5 w-2.5')}</button></span>`).join('')
              : '<span class="text-[10px] text-dim">还没有标签</span>'}
          </div>
        </div>

        <div class="mt-2 rounded-md border border-line bg-card px-2.5 py-2 text-[10px] leading-relaxed text-dim">
          <p>类型：<span class="text-sub">${esc(a.type)}</span> · 来源：<span class="text-sub">${a.source === 'inherit' ? '继承自父项目' : '本项目私有'}</span></p>
          <p class="mt-1">被引用镜头：<span class="text-sub">${a.refShots.length ? esc(a.refShots.join(' / ')) : '暂无'}</span></p>
        </div>
      </div>
    </div>

    <div class="shrink-0 border-t border-line px-4 py-3">
      <p class="flex items-start gap-1.5 rounded-md border border-amber/20 bg-amber/8 px-2 py-1.5 text-[10px] leading-relaxed text-amber2/90">
        ${ic('alert-triangle', 'mt-[1px] h-3 w-3 shrink-0')}保存后会写回资产库；「同步到所有镜头」会把这些描述作为后续生成的依据。
      </p>
      <button data-action="asset-save-sync" data-id="${a.id}" class="grad-amber mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg py-2 text-[12.5px] font-medium text-[#1B0E05]">
        ${ic('check', 'h-3.5 w-3.5')}保存并同步到所有镜头
      </button>
      <div class="mt-1.5 flex gap-2">
        <button data-action="asset-save" data-id="${a.id}" class="flex-1 rounded-lg border border-line2 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">仅保存到资产库</button>
        ${a.locked
          ? `<button data-action="asset-unlock" data-id="${a.id}" class="flex-1 rounded-lg border border-line2 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">解除锁定</button>`
          : `<button data-action="asset-lock" data-id="${a.id}" class="flex-1 rounded-lg border border-line2 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">锁定设定</button>`}
      </div>
    </div>`;
}

export function renderBatchBar() {
  const host = $('#batchBar');
  if (!host) return;
  const n = S.selected.size;
  if (!n) { host.innerHTML = ''; host.classList.add('pointer-events-none'); return; }
  host.classList.remove('pointer-events-none');
  host.innerHTML = `
    <div class="flex w-[560px] items-center gap-2 rounded-[10px] border border-line2 bg-[#191A1F]/96 px-3 py-2 shadow-[0_24px_48px_-18px_rgba(0,0,0,.95)] backdrop-blur">
      <span class="flex items-center gap-1.5 text-[11.5px] text-txt">
        <span class="flex h-4 w-4 items-center justify-center rounded-[4px] bg-amber text-[#1B0E05]">${ic('check', 'h-2.5 w-2.5')}</span>已选 ${n} 项
      </span>
      <span class="h-4 w-px bg-line2"></span>
      <button data-action="batch-migrate" class="flex items-center gap-1.5 rounded-md border border-amber/45 bg-amber/12 px-2 py-1 text-[11px] text-amber2">
        ${ic('arrow-right-left', 'h-3 w-3')}迁移到其他项目
      </button>
      <button data-action="batch-copy" class="flex items-center gap-1.5 rounded-md border border-line2 px-2 py-1 text-[11px] text-sub transition hover:bg-raise hover:text-txt">
        ${ic('copy', 'h-3 w-3')}复制到其他项目
      </button>
      <button data-action="batch-clear" class="ml-auto flex items-center gap-1 text-[11px] text-dim transition hover:text-sub">
        ${ic('x', 'h-3 w-3')}取消
      </button>
    </div>`;
  paint(host);
}

export function refreshAssetSelection() {
  const grid = renderAssetGrid();
  const g = $('#assetGrid');
  if (g) g.innerHTML = grid.html;
  const sum = $('#assetSummary');
  if (sum) sum.textContent = grid.summary;
  renderBatchBar();
  paint($('#assetsView') || document);
}
