/* Vagent · 个人中心抽屉内容
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, $$, API, S, emptyLine, esc, ic, paint } from './core.js';
/* ---------- 4.6 个人中心 ---------- */
export function renderDrawer() {
  const d = S.drawer;
  const api = S.settings.api || {};
  const field = (label, inner, key) => `
    <div class="flex items-center gap-3" data-cfg-field="${label}">
      <span class="w-[74px] shrink-0 text-[11px] text-sub">${label}</span>
      ${inner}
    </div>`;
  const box = 'flex h-[28px] flex-1 items-center gap-2 rounded-[7px] border border-line2 bg-[#0C0D10] px-2.5';
  const sel = (name, value, options) => `
    <select data-cfg="${name}" class="min-w-0 flex-1 appearance-none bg-transparent text-[11.5px] text-txt">
      ${(options || []).map(o => `<option ${o === value ? 'selected' : ''}>${esc(o)}</option>`).join('')}
      ${value && !(options || []).includes(value) ? `<option selected>${esc(value)}</option>` : ''}
    </select>${ic('chevron-down', 'h-3 w-3 shrink-0 text-dim')}`;

  const group = (key, icon, title, body, footer) => {
    const cfg = api[key] || {};
    const warn = (cfg.status || {}).warn;
    return `
    <section data-api-group="${key}" class="overflow-hidden rounded-[10px] border ${warn ? 'border-amber/25' : 'border-line'} bg-card">
      <div class="flex h-9 items-center gap-2 border-b ${warn ? 'border-amber/20' : 'border-line'} px-3.5">
        ${ic(icon, 'h-3.5 w-3.5 shrink-0 text-sub')}
        <span class="text-[12.5px] font-medium">${title}</span>
        <span class="ml-1.5 flex items-center gap-1.5 text-[10px] ${warn ? 'text-amber2' : 'text-ok'}">
          <span class="h-1.5 w-1.5 rounded-full ${warn ? 'bg-amber' : 'bg-ok'}"></span>${esc((cfg.status || {}).text || '未配置')}
        </span>
        <div class="ml-auto flex items-center gap-2.5">
          <button type="button" data-action="api-test" data-id="${key}" class="flex h-[23px] items-center gap-1 rounded-[6px] border border-line2 px-2 text-[10px] text-sub transition hover:border-amber/40 hover:text-amber2">
            ${ic('plug-zap', 'h-2.5 w-2.5')}测试连接
          </button>
          <button type="button" data-action="drawer-collapse" data-id="${key}" class="text-dim transition hover:text-sub">
            ${ic(d.collapsed[key] ? 'chevron-down' : 'chevron-up', 'h-3.5 w-3.5 shrink-0')}
          </button>
        </div>
      </div>
      ${d.collapsed[key] ? '' : `<div class="flex flex-col gap-[6px] px-3.5 py-2">${body}</div>`}
      ${footer ? `<div class="flex items-center gap-1.5 border-t ${warn ? 'border-amber/20' : 'border-line/60'} px-3.5 py-[4px] text-[10px] ${warn ? 'text-amber2/90' : 'text-dim'}">${footer}</div>` : ''}
    </section>`;
  };

  const apiKeyRow = (key, cfg) => `
    <div class="flex h-[28px] flex-1 items-center gap-0.5 rounded-[7px] border border-line2 bg-[#0C0D10] pl-2.5 pr-1">
      <input type="text" data-cfg="api_key" value="${esc(cfg.api_key || '')}" placeholder="粘贴 API Key" class="min-w-0 flex-1 truncate bg-transparent font-mono text-[11.5px] tracking-tight text-txt placeholder:text-dim" />
      <button type="button" data-action="key-reveal" data-id="${key}" class="flex h-6 shrink-0 items-center justify-center rounded-[5px] px-1 text-dim transition hover:bg-raise hover:text-sub" aria-label="显示密钥">${ic('eye', 'h-3 w-3')}</button>
      <button type="button" data-action="key-copy" data-id="${key}" class="flex h-6 shrink-0 items-center justify-center rounded-[5px] px-1 text-dim transition hover:bg-raise hover:text-sub" aria-label="复制密钥">${ic('copy', 'h-3 w-3')}</button>
    </div>`;

  const apiHtml = `
    <div class="flex flex-col gap-2">
      ${group('llm', 'sparkles', '主 Agent · 语言', `
        ${field('服务商', `<div class="${box}">${sel('provider', api.llm && api.llm.provider, (api.llm || {}).providers)}</div>`)}
        ${field('API Key', apiKeyRow('llm', api.llm || {}))}
        ${field('Base URL', `<div class="${box}"><input type="text" data-cfg="base_url" value="${esc((api.llm || {}).base_url || '')}" placeholder="https://api.example.com/v1" class="min-w-0 flex-1 truncate bg-transparent font-mono text-[11px] text-txt placeholder:text-dim" /></div>`)}
        ${field('上下文容量（token）', `<div class="${box}"><input type="number" min="1" step="1" data-cfg="context_limit" value="${esc(String(api.llm?.context_limit || ''))}" placeholder="当前模型或接入点的上限" class="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-txt placeholder:text-dim" /></div>`)}
        ${field('默认模型', `<div class="${box}">${sel('model', (api.llm || {}).model, (api.llm || {}).models)}</div>`)}
      `, `${ic('lock', 'h-2.5 w-2.5 shrink-0')}密钥只保存在本地数据库，不会上传`)}

      ${group('img', 'image', '图片 Agent · 图片', `
        ${field('服务商', `<div class="${box}">${sel('provider', (api.img || {}).provider, (api.img || {}).providers)}</div>`)}
        ${field('API Key', apiKeyRow('img', api.img || {}))}
        ${field('Base URL', `<div class="${box}"><input type="text" data-cfg="base_url" value="${esc((api.img || {}).base_url || '')}" placeholder="https://..." class="min-w-0 flex-1 truncate bg-transparent font-mono text-[11px] text-txt placeholder:text-dim" /></div>`)}
        ${field('默认模型', `<div class="${box}">${sel('model', (api.img || {}).model, (api.img || {}).models)}</div>`)}
        ${field('并发上限', `<div class="${box}"><input type="number" min="1" max="8" data-cfg="concurrency" value="${Number((api.img || {}).concurrency) || 3}" class="min-w-0 flex-1 bg-transparent text-[11.5px] tabular-nums text-txt" /><span class="text-[10px] text-dim">张 / 次</span></div>`)}
      `, `${ic('lock', 'h-2.5 w-2.5 shrink-0')}密钥只保存在本地数据库，不会上传`)}

      ${group('video', 'film', '视频 Agent · 视频', `
        ${field('服务商', `<div class="${box}">${sel('provider', (api.video || {}).provider, (api.video || {}).providers)}</div>`)}
        ${field('API Key', apiKeyRow('video', api.video || {}))}
        ${field('Base URL', `<div class="${box}"><input type="text" data-cfg="base_url" value="${esc((api.video || {}).base_url || '')}" placeholder="https://..." class="min-w-0 flex-1 truncate bg-transparent font-mono text-[11px] text-txt placeholder:text-dim" /></div>`)}
        ${field('默认模型', `<div class="${box}">${sel('model', (api.video || {}).model, (api.video || {}).models)}</div>`)}
        ${field('时长上限', `<div class="${box}">${sel('max_duration', (api.video || {}).max_duration, ['10 秒', '5 秒'])}</div>`)}
      `, `${ic('alert-triangle', 'h-2.5 w-2.5 shrink-0')}${esc((api.video || {}).note || '还没有测试过连接')}
          <button type="button" data-action="api-test" data-id="video" class="ml-1 text-[10px] text-amber2 underline decoration-amber/40 underline-offset-2">重新测试</button>`)}

      <p class="px-1 text-[10px] leading-relaxed text-dim">暂时不发起真实网络请求：测试连接只检查本地配置是否完整；接入模型后替换 /api/settings/api/test 即可。</p>
    </div>`;

  /* API 用量：只统计调用次数，不展示任何个人信息 */
  const groups = (S.apiUsage && S.apiUsage.groups) || {};
  const usageCard = (key, label, icon) => {
    const g = groups[key] || { calls: 0, today: 0, last: '' };
    return `
      <div class="rounded-[10px] border border-line bg-card px-3 py-2.5">
        <div class="flex items-center gap-1.5">${ic(icon, 'h-3 w-3 text-dim')}<span class="text-[10.5px] text-sub">${label}</span></div>
        <p class="mt-2 text-[22px] font-medium leading-none tabular-nums">${Number(g.calls || 0)}<span class="ml-1 text-[10px] font-normal text-dim">次</span></p>
        <p class="mt-1.5 text-[9.5px] tabular-nums text-dim">今日 ${Number(g.today || 0)} 次${g.last ? ' · ' + esc(g.last.slice(5, 16)) : ''}</p>
      </div>`;
  };
  const recentRows = ((S.apiUsage && S.apiUsage.recent) || []).map(r => `
    <div class="flex items-center gap-2 border-t border-line/60 px-4 py-[7px] text-[10.5px] first:border-t-0">
      <span class="w-[60px] shrink-0 text-[9.5px] tabular-nums text-dim">${esc((r.at || '').slice(11, 16))}</span>
      <span class="shrink-0 rounded-[4px] border border-line2 px-1.5 py-[1px] text-[9px] text-sub">${esc(r.provider === 'img' ? '图片' : r.provider === 'video' ? '视频' : '语言')}</span>
      <span class="min-w-0 flex-1 truncate text-sub">${esc(r.model || '—')}</span>
      <span class="shrink-0 text-[9px] ${r.ok ? 'text-ok' : 'text-danger'}">${r.ok ? '成功' : '失败'}</span>
    </div>`).join('');

  const usage = `
    <div class="flex flex-col gap-3">
      <div class="flex items-center gap-2">
        <span class="text-[11.5px] font-medium">API 调用</span>
        <span class="ml-auto text-[10px] text-dim">共 ${Number((S.apiUsage && S.apiUsage.total) || 0)} 次</span>
      </div>
      <div class="grid grid-cols-3 gap-2">
        ${usageCard('llm', '语言模型', 'sparkles')}
        ${usageCard('img', '图片模型', 'image')}
        ${usageCard('video', '视频模型', 'film')}
      </div>
      <section class="rounded-[10px] border border-line bg-card">
        <div class="flex h-9 items-center justify-between border-b border-line px-4">
          <span class="text-[11.5px] font-medium">最近调用</span>
          <span class="text-[10px] text-dim">最多 6 条 · 不记录请求内容</span>
        </div>
        ${recentRows || emptyLine('还没有调用记录，发一条消息或生成一次就会出现在这里')}
      </section>
      <p class="px-1 text-[10px] leading-relaxed text-dim">本月总花费 ¥${Number(S.spend.monthTotal || 0).toFixed(2)}：当前只统计调用次数，计费与预算尚未接入。</p>
    </div>`;

  $('#drawerBody').innerHTML = d.tab === 'api' ? apiHtml : usage;
  paint($('#drawerBody'));

  $$('[data-tab]').forEach(t => {
    const on = t.dataset.tab === d.tab;
    t.classList.toggle('text-txt', on);
    t.classList.toggle('font-medium', on);
    t.classList.toggle('text-sub', !on);
    const ink = t.querySelector('[data-ink]');
    if (ink) ink.classList.toggle('hidden', !on);
  });
}

export function openDrawer() {
  S.drawer.open = true;
  $('#drawerMask').classList.remove('hidden');
  $('#drawer').classList.remove('translate-x-full');
  $('#avatarBtn').setAttribute('aria-expanded', 'true');
  renderDrawer();
  paint($('#drawer'));
}
export function closeDrawer() {
  S.drawer.open = false;
  $('#drawerMask').classList.add('hidden');
  $('#drawer').classList.add('translate-x-full');
  $('#avatarBtn').setAttribute('aria-expanded', 'false');
}
