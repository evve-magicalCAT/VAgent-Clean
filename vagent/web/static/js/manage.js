/* Vagent · 项目管理视图
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, S, clamp, currentProject, emptyBlock, emptyLine, esc, ic } from './core.js';
/* ---------- 4.1 项目管理 ---------- */
export function coverArt(p) {
  const c = (p && p.cover) || { art: 'city', grad: '#141519', ink: '#8FA8BC' };
  const base = `<svg viewBox="0 0 380 72" preserveAspectRatio="none" class="absolute inset-0 h-full w-full" style="color:${c.ink}" aria-hidden="true">`;
  if (c.art === 'sun') {
    return base + `<circle cx="296" cy="46" r="19" fill="#FFD9A6" opacity=".5"/><path d="M0 56h380v16H0z" fill="#1A1209" opacity=".55"/><path d="M0 56h380" stroke="#FFD9A6" stroke-opacity=".45" stroke-width="1"/><path d="M118 56l16-26h44l16 26z" fill="#0F0B05" opacity=".55"/><rect x="140" y="34" width="34" height="14" rx="2" fill="#0F0B05" opacity=".7"/></svg>`;
  }
  if (c.art === 'frame') {
    return base + `<rect x="0" y="52" width="380" height="20" fill="#0F0E0A" opacity=".5"/><rect x="120" y="14" width="140" height="38" fill="currentColor" opacity=".14"/><path d="M120 14h140v38H120z" fill="none" stroke="currentColor" stroke-opacity=".28"/><circle cx="190" cy="34" r="11" fill="currentColor" opacity=".3"/></svg>`;
  }
  if (c.art === 'neon') {
    return base + `<rect x="0" y="50" width="380" height="22" fill="currentColor" opacity=".12"/><rect x="40" y="22" width="70" height="30" fill="currentColor" opacity=".22"/><rect x="52" y="28" width="40" height="5" fill="#F5813C" opacity=".55"/><rect x="240" y="18" width="90" height="34" fill="currentColor" opacity=".2"/><rect x="258" y="26" width="54" height="6" fill="#FF9A5C" opacity=".4"/></svg>`;
  }
  if (c.art === 'boxes') {
    return base + `<rect x="0" y="54" width="380" height="18" fill="currentColor" opacity=".12"/><rect x="30" y="34" width="42" height="26" fill="currentColor" opacity=".26"/><rect x="78" y="40" width="30" height="20" fill="currentColor" opacity=".2"/><rect x="250" y="30" width="46" height="30" fill="currentColor" opacity=".24"/><rect x="302" y="42" width="26" height="18" fill="currentColor" opacity=".18"/></svg>`;
  }
  if (c.art === 'bw') {
    return base + `<rect x="0" y="54" width="380" height="18" fill="currentColor" opacity=".1"/><rect x="18" y="22" width="34" height="32" fill="currentColor" opacity=".22"/><rect x="60" y="34" width="22" height="20" fill="currentColor" opacity=".16"/><rect x="250" y="18" width="40" height="36" fill="currentColor" opacity=".2"/><rect x="300" y="30" width="26" height="24" fill="currentColor" opacity=".14"/></svg>`;
  }
  return base + `<rect x="0" y="52" width="380" height="20" fill="currentColor" opacity=".10"/><rect x="24" y="26" width="46" height="26" fill="currentColor" opacity=".18"/><rect x="80" y="34" width="24" height="18" fill="currentColor" opacity=".12"/><rect x="286" y="20" width="60" height="32" fill="currentColor" opacity=".16"/><rect x="300" y="30" width="32" height="6" fill="#F5813C" opacity=".75"/><g stroke="#ffffff" stroke-opacity=".12" stroke-width="1"><path d="M40 0l-14 72M120 0l-14 72M200 0l-14 72M280 0l-14 72M356 0l-14 72"/></g></svg>`;
}

export function treeItem(p) {
  const selected = S.current.projectId === p.id;
  const subs = (p.subs || []).map(s => {
    const active = S.current.subId === s.id;
    const tone = active ? 'border border-amber/30 bg-amber/10 text-amber2'
      : selected ? 'text-sub hover:bg-raise/60 hover:text-txt' : 'text-dim hover:bg-raise/60 hover:text-sub';
    const meta = active ? `<span class="ml-auto shrink-0 text-[9.5px] text-amber2/80">${s.assets} 资产</span>`
      : `<span class="ml-auto shrink-0 text-[9.5px] text-dim">${s.shots} 镜头</span>`;
    return `<button data-action="select-sub" data-id="${s.id}" class="flex w-full items-center gap-2 rounded-md px-2 py-[6px] text-left text-[11.5px] transition ${tone}">
      <span class="truncate">${esc(s.name)}</span>${meta}</button>`;
  }).join('');

  return `
    <div class="${selected ? 'rounded-lg bg-raise' : 'rounded-lg'} px-2 py-[7px] transition hover:bg-raise/50">
      <button data-action="select-project" data-id="${p.id}" class="flex w-full items-center gap-2 text-left">
        <span class="h-4 w-4 shrink-0 rounded-[3px]" style="background:${p.cover.grad}"></span>
        <span class="truncate text-[12.5px] ${selected ? 'font-medium text-txt' : 'text-sub'}">${esc(p.name)}</span>
        ${p.archived ? '<span class="shrink-0 rounded-[3px] border border-line px-1 py-[1px] text-[8.5px] text-dim">已归档</span>' : ''}
        <span class="ml-auto shrink-0 text-[9.5px] text-dim">${p.subsCount} 个子项目</span>
      </button>
    </div>
    ${(p.subs || []).length ? `<div class="ml-[13px] border-l border-line pl-2.5 ${selected ? 'pt-1' : ''}">${subs}</div>` : ''}`;
}

export function projectCard(p) {
  const active = S.current.projectId === p.id;
  return `
    <article class="group relative overflow-hidden rounded-[10px] border ${active ? 'ring-1 ring-amber/45 ' : ''}${p.archived ? 'border-line/70 bg-card/70 opacity-75 saturate-[.35]' : 'border-line bg-card transition hover:border-line2'}">
      <div class="relative h-[188px] overflow-hidden" style="background:${p.cover.grad}">
        ${p.cover.image
          ? `<img src="${esc(p.cover.image)}" alt="${esc(p.name)}" loading="lazy" class="absolute inset-0 h-full w-full object-contain p-2" onerror="this.style.display='none'" />`
          : coverArt(p)}
        <div class="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-transparent"></div>
        <span class="absolute left-2.5 top-2 rounded-[4px] bg-black/35 px-1.5 py-[2px] text-[9px] text-white/75">${esc(p.kind)}</span>
        ${p.archived && !active ? `<span class="absolute right-2.5 top-2 flex items-center gap-1 rounded-[4px] border border-line2 bg-base/85 px-1.5 py-[2px] text-[9px] text-sub">${ic('archive', 'h-[8px] w-[8px]')}已归档</span>` : ''}
      </div>
      ${active ? `<div class="pointer-events-none absolute inset-0 z-10 rounded-[10px] bg-amber/10"></div>
        <span class="absolute right-2.5 top-2 z-20 flex items-center gap-1 rounded-[4px] border border-amber/45 bg-base/85 px-1.5 py-[2px] text-[9px] text-amber2">${ic('folder-open', 'h-[8px] w-[8px]')}已打开</span>` : ''}
      <div class="px-3 py-2.5">
        <div class="flex items-center gap-1.5">
          <h3 class="truncate text-[13px] font-medium text-txt">${esc(p.name)}</h3>
          <span class="shrink-0 rounded-[3px] border border-line px-1 py-[1px] text-[8.5px] text-dim">${esc(p.kind)}</span>
        </div>
        <p class="mt-1 line-clamp-2 min-h-[34px] text-[10.5px] leading-[1.6] text-sub">${(() => {
          const summary = (p.desc || (p.cover && p.cover.summary) || '').trim();
          return summary ? esc(summary) : '<span class="text-dim">还没有描述</span>';
        })()}</p>
        <div class="mt-2 flex items-center gap-2.5 text-[10px] text-dim">
          <span class="flex items-center gap-1">${ic('corner-down-right', 'h-2.5 w-2.5')}${p.subsCount} 子项目</span>
          <span class="h-2.5 w-px bg-line"></span>
          <span class="flex items-center gap-1">${ic('film', 'h-2.5 w-2.5')}${p.shots} 镜头</span>
          <span class="h-2.5 w-px bg-line"></span>
          <span class="flex items-center gap-1">${ic('layers', 'h-2.5 w-2.5')}${p.assets} 资产</span>
        </div>
      </div>
      <div class="relative flex items-center gap-2 border-t border-line px-3 py-2">
        <span class="truncate text-[9.5px] text-dim">${esc((p.edited || '').replace('T', ' '))}</span>
        <div class="absolute inset-0 z-20 flex items-center justify-end gap-1.5 bg-[#191A1F]/97 px-3 opacity-0 transition group-hover:opacity-100">
          <button data-action="open-project" data-id="${p.id}" class="rounded-[4px] border border-amber/40 bg-amber/12 px-1.5 py-[2px] text-[9.5px] text-amber2">打开</button>
          <button data-action="project-rename" data-id="${p.id}" class="rounded-[4px] border border-line2 px-1.5 py-[2px] text-[9.5px] text-sub">重命名</button>
          <button data-action="project-archive" data-id="${p.id}" class="rounded-[4px] border border-line2 px-1.5 py-[2px] text-[9.5px] text-sub">${p.archived ? '恢复' : '归档'}</button>
          <button data-action="project-delete" data-id="${p.id}" class="rounded-[4px] border border-danger/40 px-1.5 py-[2px] text-[9.5px] text-danger/90">删除</button>
        </div>
      </div>
    </article>`;
}

export function renderManage() {
  const proj = currentProject();
  const subs = proj ? (proj.subs || []) : [];
  const subCount = S.projects.reduce((a, p) => a + (p.subs || []).length, 0);
  const allAssets = S.projects.length ? null : [];
  const domain = [
    { label: '当前范围资产', value: S.assets.length, unit: '项' },
    { label: '继承自父项目', value: S.assetStats.inherit || 0, unit: '项' },
    { label: '已锁定', value: S.assetStats.locked || 0, unit: '项' },
    { label: '已归档项目', value: S.projects.filter(p => p.archived).length, unit: '个' }
  ];

  const tree = S.projects.length
    ? S.projects.map(treeItem).join('')
    : `<div class="px-3 py-6 text-center">
         <p class="text-[11px] text-dim">还没有项目</p>
         <p class="mt-1 text-[10px] text-dim">从「新建项目」开始</p>
       </div>`;

  const cards = S.projects.length
    ? `<div class="grid grid-cols-2 gap-4">${S.projects.map(projectCard).join('')}</div>`
    : emptyBlock({
      icon: 'folder-plus', title: '还没有任何项目',
      desc: '一个项目对应一部片子；项目下可以建多个子项目（分集），资产库在项目内共享。',
      action: 'project-new', label: '新建项目'
    });

  const subRows = !proj
    ? emptyLine('先在左侧选择或新建一个项目')
    : subs.length ? subs.map(s => {
      const active = S.current.subId === s.id;
      const badge = s.status === '已完成'
        ? `<span class="flex shrink-0 items-center gap-1 rounded-[3px] border border-ok/30 bg-ok/10 px-1 py-[1px] text-[8.5px] text-ok">${ic('check', 'h-[7px] w-[7px]')}已完成</span>`
        : s.status === '进行中'
          ? `<span class="flex shrink-0 items-center gap-1 rounded-[3px] border border-amber/30 bg-amber/10 px-1 py-[1px] text-[8.5px] text-amber2"><span class="live-dot h-1 w-1 rounded-full bg-amber2"></span>进行中</span>`
          : `<span class="shrink-0 rounded-[3px] border border-line px-1 py-[1px] text-[8.5px] text-dim">草稿</span>`;
      return `
        <div class="${active ? 'bg-raise/40' : ''} px-3 py-2.5">
          <div class="flex items-center gap-2">
            <span class="truncate text-[12px] ${active ? 'font-medium text-txt' : 'text-sub'}">${esc(s.name)}</span>
            ${badge}
            <button data-action="select-sub" data-id="${s.id}" class="ml-auto flex shrink-0 items-center gap-0.5 text-[10px] ${active ? 'text-amber2' : 'text-dim'} transition hover:text-amber2">打开${ic('chevron-right', 'h-3 w-3')}</button>
          </div>
          <div class="mt-1.5 flex items-center gap-2 text-[9.5px] text-dim">
            <span>${s.shots} 镜头${s.dur ? ' · ' + s.dur : ''}</span>
            <span class="flex items-center gap-1 rounded-[3px] border border-line px-1 py-[1px]">${ic('git-branch', 'h-2.5 w-2.5')}${s.assets} 项资产</span>
          </div>
        </div>`;
    }).join('')
      : emptyLine('这个项目还没有子项目');

  return `
  <div class="flex h-full min-h-0">
    <aside class="flex w-[272px] shrink-0 flex-col border-r border-line bg-[#0E0F12]">
      <div class="flex h-11 items-center justify-between border-b border-line px-4">
        <span class="text-[11px] tracking-[0.12em] text-sub">项目</span>
        <span class="text-[10px] text-dim">${S.projects.length} 个 · ${subCount} 个子项目</span>
      </div>
      <div class="hide-scroll min-h-0 flex-1 overflow-y-auto px-2 py-2.5">
        ${tree}
        <div class="mx-1 mt-3 border-t border-line pt-2">
          <button data-action="project-new" class="flex w-full items-center gap-1.5 rounded-md px-2 py-[7px] text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">
            ${ic('plus', 'h-3.5 w-3.5')}新建项目
          </button>
        </div>
      </div>
      <div class="border-t border-line px-3 py-3">
        <p class="flex items-start gap-1.5 text-[10px] leading-relaxed text-dim">
          ${ic('info', 'mt-[1px] h-3 w-3 shrink-0')}归档的项目不出现在切换器里，资产仍可被引用。
        </p>
      </div>
    </aside>

    <main class="hide-scroll min-w-0 flex-1 overflow-y-auto px-6 py-5">
      <div class="flex items-start gap-4">
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h1 class="text-[20px] font-semibold leading-none tracking-tight">项目管理</h1>
            <span class="rounded-[4px] border border-line px-1.5 py-[1px] text-[9.5px] text-dim">共 ${S.projects.length} 个项目 · ${subCount} 个子项目</span>
          </div>
          <p class="mt-2 text-[11.5px] text-sub">每个项目的资产库互相独立，可跨项目迁移；子项目默认继承父项目资产。</p>
        </div>
        <button data-action="project-new" class="grad-amber ml-auto flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] font-medium text-[#1B0E05]">
          ${ic('plus', 'h-3.5 w-3.5')}新建项目
        </button>
      </div>

      <div class="mt-5">${cards}</div>

      <div class="mt-4 rounded-[10px] border border-line bg-card">
        <div class="flex items-center gap-2 border-b border-line px-3 py-2">
          ${ic('arrow-right-left', 'h-3 w-3 text-amber/80')}
          <span class="text-[11px] text-sub">最近的资产迁移</span>
          <span class="ml-auto text-[9.5px] text-dim">跨项目导入的资产会记在这里</span>
        </div>
        <div class="divide-y divide-line/60">
          ${(() => {
            const imported = S.assets.filter(a => a.from);
            if (!imported.length) return emptyLine('还没有跨项目迁移记录');
            return imported.slice(0, 6).map(a => `
              <div class="flex items-center gap-2.5 px-3 py-[7px]">
                <span class="text-[11px] text-txt">${esc(a.name)}</span>
                ${ic('arrow-right', 'h-2.5 w-2.5 shrink-0 text-dim')}
                <span class="text-[11px] text-sub">来自「${esc(a.from)}」</span>
                <span class="rounded-[3px] border border-line px-1 py-[1px] text-[8.5px] text-dim">副本</span>
                <span class="ml-auto text-[9.5px] text-dim">${esc(a.updatedAt || '')}</span>
              </div>`).join('');
          })()}
        </div>
      </div>

      <div class="mt-4 grid grid-cols-4 divide-x divide-line rounded-[10px] border border-line bg-card">
        ${domain.map(d => `
          <div class="px-3 py-2.5">
            <p class="text-[9.5px] text-dim">${esc(d.label)}</p>
            <p class="mt-1 text-[15px] font-medium leading-none">${d.value}<span class="ml-1 text-[9.5px] text-sub">${d.unit}</span></p>
          </div>`).join('')}
      </div>

      <p class="mt-3 flex items-center gap-1.5 pb-2 text-[10px] text-dim">
        ${ic('archive', 'h-3 w-3')}归档只是从最近列表里收起，资产仍可被其他项目引用或迁移。
      </p>
    </main>

    <aside class="flex w-[344px] shrink-0 flex-col overflow-hidden border-l border-line bg-[#0E0F12]">
      <div class="flex items-center gap-2 border-b border-line px-3 py-2.5">
        <span class="text-[12px] font-medium">子项目</span>
        ${proj ? `<span class="flex min-w-0 items-center gap-1 rounded-[4px] border border-line px-1.5 py-[1px] text-[9px] text-dim">
          <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-amber/70"></span><span class="truncate">${esc(proj.name)}</span>
        </span>` : ''}
        <button data-action="sub-new" ${proj ? '' : 'disabled'} class="ml-auto flex shrink-0 items-center gap-1 rounded-md border border-line2 px-1.5 py-[3px] text-[10px] ${proj ? 'text-sub transition hover:border-amber/40 hover:text-amber2' : 'text-dim opacity-50'}">
          ${ic('plus', 'h-3 w-3')}新建子项目
        </button>
      </div>
      <div class="hide-scroll min-h-0 flex-1 divide-y divide-line/70 overflow-y-auto">${subRows}</div>
      <div class="mt-auto border-t border-line bg-panel/40 px-3 py-2.5">
        <p class="flex items-start gap-1.5 text-[10px] leading-relaxed text-dim">
          ${ic('git-branch', 'mt-[1px] h-3 w-3 shrink-0 text-amber/70')}子项目默认继承父项目资产，也可以拥有自己的私有资产。
        </p>
      </div>
    </aside>
  </div>`;
}
