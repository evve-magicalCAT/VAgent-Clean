/* Vagent · 视频视图与时间轴
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, S, currentProject, emptyBlock, esc, fmtDur, ic, timeLabel, totalDur } from './core.js';

/* 镜头清单里的短标题：优先用 Agent 给的 title/name，旧数据回退到提示词第一小句 */
function shotPromptSummary(text) {
  const first =
    String(text || '')
      .split(/[，。；、,.;:：\n]/)
      .map(item => item.trim())
      .find(Boolean) || '';
  const clean = first
    .replace(/^(镜头|第?\s*\d+\s*[镜个]?)\s*[0-9一二三四五六七八九十]*\s*[：:、.\-]?\s*/, '')
    .trim();
  if (!clean) return '';
  return clean.length > 14 ? clean.slice(0, 14) + '…' : clean;
}

function assetThumbUrl(asset) {
  const preview = (asset && asset.preview) || [];
  const item = preview.find(p => p.kind === 'img' && p.url) || preview.find(p => p.url);
  if (!item || !item.url) return '';
  const stamp = String((asset && asset.updatedAt) || '').replace(/\D/g, '');
  return item.url + (stamp ? (item.url.includes('?') ? '&' : '?') + 'v=' + stamp : '');
}

function shotDisplayName(shot) {
  const name = String((shot && shot.name) || '').trim();
  const prompt = String((shot && shot.prompt) || '').trim();
  const fallback = shotPromptSummary(prompt) || `镜头 ${(shot && shot.no) || ''}`;
  if (!name) return fallback;
  const generic =
    /^(我想要|想要|生成|做一个|一个)/.test(name) ||
    /^镜头\s*\d+/.test(name) ||
    name.length > 18;
  return generic && prompt ? shotPromptSummary(prompt) || name : name;
}

/* 有真实成片时，按时间点把这一镜截成 3~4 格拼成胶片条：
   每格用 #t= 媒体片段取该段的画面，取不到帧时露出底层的镜头配色，不会变纯黑。 */
function clipFilmstrip(s, tiles) {
  const n = tiles || (s.dur >= 8 ? 4 : 3);
  const tone = (s.tones || ['#2A323A'])[0];
  const span = Math.max(0.4, Number(s.dur) || 1);
  return `<div class="flex h-full divide-x divide-black/60">${Array.from({ length: n }, (_, i) => {
    const t = (((i + 0.5) / n) * span).toFixed(2);
    return `<div class="relative min-w-0 flex-1 overflow-hidden" style="background:linear-gradient(150deg,${tone},#101418)">
      <video src="${esc(s.clipPath)}#t=${t}" muted playsinline preload="metadata" class="pointer-events-none absolute inset-0 h-full w-full object-cover"></video>
    </div>`;
  }).join('')}</div>`;
}

/* 播放头落在哪个镜头的第几秒（时间轴上是连续的一条，不是单镜预览） */
export function shotAtPlayhead(pct) {
  const shots = S.shots;
  const total = totalDur();
  if (!total || !shots.length) return null;
  const t = clamp01((Number(pct) || 0) / 100) * total;
  let acc = 0;
  for (const s of shots) {
    if (t < acc + s.dur) return { shot: s, offset: Math.max(0, t - acc) };
    acc += s.dur;
  }
  const last = shots[shots.length - 1];
  return { shot: last, offset: Math.max(0, last.dur - 0.05) };
}

function clamp01(v) {
  return Math.max(0, Math.min(1, v || 0));
}

/* ---------- 4.4 视频 ---------- */
export function sceneSvg(shot) {
  const tones = shot.tones || ['#2A323A', '#252C34'];
  const gid = 'pv' + String(shot.id).replace(/[^a-zA-Z0-9]/g, '');
  return `
  <svg viewBox="0 0 520 293" class="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice" role="img" aria-label="镜头 ${esc(shot.no || '')} 画面：${esc(shotDisplayName(shot))}">
    <defs>
      <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${tones[0] || '#161C22'}"/><stop offset="1" stop-color="#0A0D10"/>
      </linearGradient>
      <linearGradient id="${gid}v" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#000" stop-opacity=".55"/><stop offset=".45" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".7"/>
      </linearGradient>
    </defs>
    <rect width="520" height="293" fill="url(#${gid})"/>
    <g style="color:#7A838E" opacity=".55">
      <use href="#shot-${shot.frame || 'street'}" x="60" y="10" width="400" height="250"/>
    </g>
    <g style="color:#07090B" opacity=".9">
      <use href="#fig-front" x="218" y="150" width="84" height="120"/>
    </g>
    <rect width="520" height="293" fill="url(#rainPattern)" opacity=".5"/>
    <rect width="520" height="293" fill="url(#${gid}v)"/>
  </svg>`;
}

export function videoConfigured() {
  return !!(((S.settings.api || {}).video || {}).api_key);
}

export function statusPill(status, opts = {}) {
  if (status === 'confirmed') return `<span class="flex items-center gap-1 rounded-[4px] border border-ok/30 bg-ok/10 px-1.5 py-[2px] text-[9.5px] text-ok">${ic('check', 'h-2.5 w-2.5')}已确认</span>`;
  if (status === 'modified') return `<span class="flex items-center gap-1 rounded-[4px] border border-line2 bg-panel px-1.5 py-[2px] text-[9.5px] text-sub"><span class="h-1.5 w-1.5 rounded-full bg-amber"></span>已修改 · 待确认</span>`;
  if (status === 'redraw') return `<span class="flex items-center gap-1 rounded-[4px] border border-amber/45 bg-amber/10 px-1.5 py-[2px] text-[9.5px] text-amber2">${ic('loader-circle', 'h-2.5 w-2.5 animate-spin')}重绘中 ${opts.progress || 0}%</span>`;
  if (status === 'failed') return `<span class="flex items-center gap-1 rounded-[4px] border border-danger/30 bg-danger/10 px-1.5 py-[2px] text-[9.5px] text-danger">${ic('alert-triangle', 'h-2.5 w-2.5')}生成失败</span>`;
  return `<span class="flex items-center gap-1 rounded-[4px] border border-amber/45 bg-amber/10 px-1.5 py-[2px] text-[9.5px] text-amber2">${ic('circle-dashed', 'h-2.5 w-2.5')}待确认</span>`;
}

export function renderVideo() {
  const shots = S.shots;
  const total = totalDur();
  const proj = currentProject();
  const shot = shots.find(s => s.id === S.video.shotId) || shots[0] || null;
  const start = shot ? shots.slice(0, shots.findIndex(s => s.id === shot.id)).reduce((a, s) => a + s.dur, 0) : 0;
  const cur = total * (S.video.playhead / 100);
  const head = shotAtPlayhead(S.video.playhead);

  const topBar = `
    <div class="flex h-11 shrink-0 items-center gap-3 border-b border-line/70 bg-[#0E0F12] px-6">
      <h2 class="max-w-[280px] truncate text-[13.5px] font-medium">${esc(proj ? proj.name : '还没有项目')}${proj ? ' · ' + esc(proj.kind) : ''}</h2>
      <span class="shrink-0 rounded-[4px] border border-line px-1.5 py-[1px] text-[9.5px] text-dim">${esc(S.current.sub || '未分集')}</span>
      <span class="shrink-0 text-[10.5px] text-dim">${shots.length} 个镜头 · ${total.toFixed(1)}s · 已锁定 ${S.assets.filter(a => a.locked).length} 项设定</span>
      <div class="ml-auto flex items-center gap-2">
        <button data-action="undo" class="flex items-center gap-1.5 rounded-lg border border-line bg-raise px-2.5 py-1 text-[11.5px] text-sub transition hover:border-line2 hover:text-txt">${ic('undo-2', 'h-3 w-3')}撤销</button>
        <button data-action="export" class="flex items-center gap-1.5 rounded-lg border border-line2 px-2.5 py-1 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">${ic('download', 'h-3 w-3')}导出 1080p</button>
        <span class="flex items-center gap-1 text-[10px] text-dim">${ic('history', 'h-3 w-3')}${esc(S.savedAt ? S.savedAt.slice(5, 16) + ' 保存' : '')}</span>
      </div>
    </div>`;

  if (!shots.length) {
    return `<div class="flex h-full min-h-0 flex-col">
      ${topBar}
      <div class="flex flex-1 items-center justify-center px-10">
        <div class="w-full max-w-[560px]">${emptyBlock({
          icon: 'film', title: '还没有镜头',
          desc: '镜头是这部片子的最小单位。可以先在对话里描述，也可以直接新增一个空白镜头再写提示词。',
          action: 'shot-new', label: '新增镜头'
        })}</div>
      </div>
    </div>`;
  }

  const track = shots.map(s => {
    const w = total ? (s.dur / total) * 100 : 0;
    const active = s.id === shot.id;
    const isRedraw = s.status === 'redraw';
    const isFail = s.status === 'failed';
    const border = active ? 'border-amber shadow-[0_0_0_1px_rgba(245,129,60,.35)]'
      : isRedraw ? 'border-amber/50' : isFail ? 'border-danger/40' : 'border-line2';
    return `
      <button data-action="shot-select" data-id="${s.id}" style="width:${w}%" class="group/shot relative overflow-hidden rounded-[5px] border ${border} bg-[#171A1E] text-left transition hover:border-amber/60">
        <div class="relative h-[38px] overflow-hidden ${isRedraw || isFail ? 'opacity-40' : ''}">
          ${s.clipPath
            ? clipFilmstrip(s)
            : `<div class="flex h-full divide-x divide-black/40">${(s.tones || []).map(t => `<div class="flex-1" style="background:linear-gradient(150deg,${t},#101418)"></div>`).join('')}</div>`}
        </div>
        <div class="relative flex items-center gap-1 bg-[#171A1E]/92 px-1.5 pt-1">
          <span class="text-[9.5px] font-medium ${active ? 'text-amber2' : 'text-txt'}">${esc(s.no)}</span>
          <span class="text-[9px] ${active ? 'text-amber2/80' : 'text-sub'}">${fmtDur(s.dur)}</span>
          ${active ? ic('scan-line', 'ml-auto h-2 w-2 text-amber2') : s.locked ? ic('lock', 'ml-auto h-2 w-2 text-dim') : ''}
        </div>
        ${isRedraw ? `<div class="absolute inset-0 flex flex-col items-center justify-center gap-[3px] bg-base/70">${ic('loader-circle', 'h-3 w-3 animate-spin text-amber')}<span class="text-[9px] text-amber2">生成中 ${s.progress}%</span></div>
          <div class="absolute inset-x-0 bottom-0 h-[2px] bg-line"><div class="grad-amber h-full" style="width:${s.progress}%"></div></div>` : ''}
        ${isFail ? `<div class="absolute inset-0 flex flex-col items-center justify-center gap-[2px] bg-[#1A1312]/80"><span class="flex items-center gap-1 text-[9px] text-danger">${ic('alert-triangle', 'h-2.5 w-2.5')}生成失败</span><span class="rounded border border-danger/40 px-1 py-[1px] text-[8px] text-danger/90">点击重试</span></div>` : ''}
      </button>`;
  }).join('');

  const step = total <= 12 ? 2 : total <= 30 ? 5 : 10;
  const tickCount = Math.max(2, Math.ceil(total / step));
  const ticks = Array.from({ length: tickCount + 1 }, (_, i) => i * step);

  const list = shots.map(s => {
    const active = s.id === shot.id;
    const cls = active ? 'border-amber/45 bg-amber/8' : s.status === 'redraw' ? 'border-line/60 bg-card/60'
      : s.status === 'failed' ? 'border-danger/25 bg-danger/5' : 'border-line/60 bg-card/60';
    return `
      <button data-action="shot-select" data-id="${s.id}" class="flex w-full items-center gap-2 rounded-md border ${cls} px-2 py-1.5 text-left transition hover:border-line2">
        <span class="text-[9.5px] ${active ? 'text-amber2' : 'text-dim'}">${esc(s.no)}</span>
        ${s.clipPath
          ? `<video src="${esc(s.clipPath)}#t=0.1" muted playsinline preload="metadata" class="pointer-events-none h-6 w-9 shrink-0 rounded-[3px] bg-[#0C0E11] object-cover"></video>`
          : `<span class="h-6 w-9 shrink-0 rounded-[3px]" style="background:linear-gradient(150deg,${(s.tones || ['#2A323A'])[0]},#12161A)"></span>`}
        <span class="flex-1 truncate text-[10.5px] ${active ? 'text-txt' : 'text-sub'}">${esc(shotDisplayName(s))}</span>
        ${s.status === 'redraw'
          ? `<span class="flex items-center gap-1 text-[9px] text-amber2">${ic('loader-circle', 'h-2.5 w-2.5 animate-spin')}${s.progress}%</span>`
          : `<span class="text-[9px] ${active ? 'text-amber2' : 'text-dim'}">${fmtDur(s.dur)}</span>`}
      </button>`;
  }).join('');

  const refAssets = (shot.refAssets || [])
    .map(id => S.assets.find(a => a.id === id))
    .filter(Boolean);
  const audioMats = S.materials.filter(m => m.kind === '音频');

  return `
  <div class="flex h-full min-h-0 flex-col">
    ${topBar}

    <div class="flex min-h-0 flex-1">
      <div class="flex min-w-0 flex-1 gap-3 px-5 pt-4">
        <div class="w-[486px] shrink-0">
          <div class="relative h-[273px] w-full overflow-hidden rounded-lg border border-line2 bg-[#0A0C0F]">
            ${head && head.shot.clipPath
              ? `<video id="previewVideo" data-shot="${esc(head.shot.id)}" src="${esc(head.shot.clipPath)}#t=${head.offset.toFixed(2)}" playsinline preload="auto" class="absolute inset-0 h-full w-full bg-black object-cover"></video>`
              : sceneSvg(shot)}
            <div class="absolute left-2.5 top-2.5 flex items-center gap-1.5 rounded-md border border-white/10 bg-black/45 px-2 py-1 text-[10px] text-txt backdrop-blur">
              ${ic('clapperboard', 'h-2.5 w-2.5 text-amber')}镜头 ${esc(shot.no)} · ${fmtDur(shot.dur)}
            </div>
            <div class="absolute right-2.5 top-2.5 flex items-center gap-1 rounded-md border border-white/10 bg-black/45 px-1.5 py-1 text-[9.5px] text-sub backdrop-blur">${shot.clipPath ? '已生成 · 16:9' : '16:9 · 1080p'}</div>
            <div class="absolute bottom-2.5 left-2.5 right-2.5 flex items-center gap-2">
              <div class="flex-1 truncate rounded border border-white/10 bg-black/45 px-2 py-1 text-[10px] text-sub backdrop-blur">${esc(shotDisplayName(shot))}：${esc((shot.prompt || '').slice(0, 26))}${(shot.prompt || '').length > 26 ? '…' : ''}</div>
              <button data-action="subtitles" class="flex items-center gap-1 rounded border border-white/10 bg-black/45 px-2 py-1 text-[10px] text-txt backdrop-blur">${ic('captions', 'h-2.5 w-2.5')}字幕</button>
            </div>
          </div>
          <div class="mt-2 flex h-10 items-center gap-3 rounded-lg border border-line bg-card px-3">
            <button data-action="play" class="grad-amber flex h-6 w-6 items-center justify-center rounded-full">${ic(S.video.playing ? 'pause' : 'play', 'h-3 w-3 text-[#1B0E05]')}</button>
            <span class="font-mono text-[10.5px] text-sub"><span id="previewTime">${timeLabel(cur)}</span><span class="text-dim"> / ${timeLabel(total)}</span></span>
            <div class="relative h-[3px] flex-1 rounded-full bg-line">
              <div class="absolute inset-y-0 left-0 rounded-full bg-amber" style="width:${S.video.playhead}%"></div>
              <span class="absolute -top-[3px] h-[9px] w-[9px] -translate-x-1/2 rounded-full bg-amber2 ring-2 ring-card" style="left:${S.video.playhead}%"></span>
            </div>
            ${ic('volume-2', 'h-3.5 w-3.5 text-sub')}
            ${ic('maximize', 'h-3.5 w-3.5 text-sub')}
          </div>
        </div>

        <div class="flex min-w-0 flex-1 flex-col rounded-lg border border-line2 bg-card">
          <div class="flex h-9 shrink-0 items-center gap-2 border-b border-line px-3">
            <span class="flex items-center gap-1.5 text-[12px] font-medium">${ic('scan-line', 'h-3.5 w-3.5 text-amber')}镜头 ${esc(shot.no)} · 详情</span>
            ${shot.status === 'redraw' ? `<span class="flex items-center gap-1 rounded-[4px] border border-line px-1.5 py-[1px] text-[9.5px] text-amber2">${ic('loader-circle', 'h-2.5 w-2.5 animate-spin')}生成中</span>`
              : `<span class="flex items-center gap-1 rounded-[4px] border border-line px-1.5 py-[1px] text-[9.5px] text-sub">${ic('check-circle-2', 'h-2.5 w-2.5')}${shot.status === 'confirmed' ? '已确认' : '待确认'}</span>`}
            <label class="ml-auto flex items-center gap-1 text-[10px] text-dim" title="时间轴时长，1–15 秒；成片按此时长裁切">
              ${ic('timer', 'h-3 w-3')}
              <input data-shot-dur="${shot.id}" type="number" min="1" max="15" step="0.5" value="${Number(shot.dur).toFixed(1)}" class="w-[46px] rounded border border-line2 bg-panel px-1 py-[1px] text-center text-[10px] text-txt outline-none focus:border-amber/45" />
              <span>s · 35mm</span>
            </label>
          </div>
          <div class="flex min-h-0 flex-1 flex-col">
            <div class="hide-scroll flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-3 py-2.5">
            <div class="grid grid-cols-2 gap-2">
              <div class="relative h-[74px] overflow-hidden rounded-md border ${!shot.refMode ? 'border-amber/45 bg-amber/8' : 'border-line bg-[#0C0E11]'}">
                <div class="absolute inset-0" style="background:linear-gradient(160deg,${(shot.tones || ['#2A323A'])[0]} 0%,#11151A 70%)"></div>
                <svg viewBox="0 0 200 125" preserveAspectRatio="xMidYMid slice" class="absolute inset-0 h-full w-full" style="color:#6E7884"><use href="#shot-${shot.frame}"/></svg>
                ${shot.clipPath ? `<video src="${esc(shot.clipPath)}#t=0.1" muted playsinline preload="metadata" class="pointer-events-none absolute inset-0 h-full w-full object-cover"></video>` : ''}
                <div class="absolute inset-x-1 top-1 flex items-center gap-1">
                  <span class="rounded bg-black/50 px-1 py-[1px] text-[8.5px] ${!shot.refMode ? 'text-amber2' : 'text-sub'}">首帧模式</span>
                  <button data-action="shot-ref-mode" data-id="${shot.id}" data-mode="first" class="ml-auto min-w-[52px] rounded-md border ${!shot.refMode ? 'border-amber/60 bg-amber/20 text-amber2' : 'border-line2 bg-base/80 text-sub'} px-2 py-1 text-[10px] font-medium transition hover:border-amber/50 hover:text-amber2">${!shot.refMode ? '已启用' : '启用'}</button>
                </div>
              </div>
              <div class="relative h-[74px] overflow-hidden rounded-md border ${shot.refMode ? 'border-amber/45 bg-amber/8' : 'border-line bg-[#0C0E11]'}">
                <div class="flex h-full flex-col p-1.5">
                  <div class="flex items-center gap-1">
                    <span class="flex items-center gap-1 text-[8.5px] ${shot.refMode ? 'text-amber2' : 'text-sub'}">${ic('layers', 'h-2.5 w-2.5')}资产全能参考模式</span>
                    <button data-action="shot-ref-mode" data-id="${shot.id}" data-mode="asset" class="ml-auto min-w-[52px] rounded-md border ${shot.refMode ? 'border-amber/60 bg-amber/20 text-amber2' : 'border-line2 bg-panel text-sub'} px-2 py-1 text-[10px] font-medium transition hover:border-amber/50 hover:text-amber2">${shot.refMode ? '已启用' : '启用'}</button>
                  </div>
                  ${shot.refMode ? `<div class="mt-1 flex min-w-0 flex-1 items-center gap-1">
                    ${refAssets.length
                      ? refAssets.slice(0, 3).map(a => `<img src="${esc(assetThumbUrl(a))}" alt="${esc(a.name)}" class="h-7 w-9 shrink-0 rounded-[3px] border border-line object-cover" />`).join('')
                      : `<span class="truncate text-[8px] text-dim">Agent 自动选择</span>`}
                    <button data-action="shot-ref-pick" data-id="${shot.id}" class="ml-auto shrink-0 rounded-[3px] border border-line2 bg-panel px-1.5 py-[1px] text-[8px] text-sub transition hover:text-amber2">选择</button>
                  </div>` : `<p class="mt-1 text-[8px] leading-[1.4] text-dim">H3 全能参考<br/>提示词 + 资产图 + 设定</p>`}
                </div>
              </div>
            </div>

            <div>
              <div class="flex items-center gap-1.5">
                <span class="text-[10.5px] text-sub">镜头提示词</span>
                <span class="text-[9.5px] text-dim">只影响这个镜头</span>
                <span class="ml-auto flex items-center gap-1 text-[9.5px] text-dim">${ic('sparkles', 'h-2.5 w-2.5 text-amber')}从对话改写</span>
              </div>
              <div class="mt-1 rounded-md border border-line2 bg-panel px-2 py-1.5 transition focus-within:border-amber/45">
                <textarea data-shot-prompt="${shot.id}" rows="3" placeholder="写这一个镜头要发生什么……" class="w-full resize-none bg-transparent text-[11px] leading-[1.7] text-txt placeholder:text-dim">${esc(shot.prompt)}</textarea>
                <div class="mt-1 flex items-center justify-between border-t border-line/60 pt-1 text-[9px] text-dim">
                  <span>直接改写，700ms 自动保存</span><span>${(shot.prompt || '').length} 字</span>
                </div>
              </div>
            </div>

            </div>
            <div class="shrink-0 border-t border-line/60 px-3 py-2.5">
              ${(shot.status === 'redraw' && shot.providerJob && !shot.clipPath)
                ? `<button data-action="shot-redo" data-id="${shot.id}" disabled class="flex w-full cursor-not-allowed items-center justify-center gap-1.5 rounded-lg border border-amber/40 bg-amber/12 py-2 text-[12.5px] font-medium text-amber2 opacity-80">
                    ${ic('loader-circle', 'h-3.5 w-3.5 animate-spin')}生成中...
                  </button>`
                : `<button data-action="shot-redo" data-id="${shot.id}" class="grad-amber amber-ring flex w-full items-center justify-center gap-1.5 rounded-lg py-2 text-[12.5px] font-medium text-[#1B0E05]">
                    ${ic('rotate-cw', 'h-3.5 w-3.5')}${shot.clipPath ? '重新生成视频' : '生成视频'}
                  </button>`}
              <div class="mt-1.5 grid grid-cols-2 gap-1.5">
                <button data-action="shot-redo-keys" data-id="${shot.id}" class="flex items-center justify-center gap-1.5 rounded-lg border border-line2 py-1.5 text-[11px] text-sub transition hover:bg-raise hover:text-txt">${ic('image', 'h-3 w-3')}${shot.refMode ? (shot.hasFirstFrame ? '重新生成首帧' : '生成首帧') : '确认首帧'}</button>
                <button data-action="shot-split" data-id="${shot.id}" class="flex items-center justify-center gap-1.5 rounded-lg border border-line2 py-1.5 text-[11px] text-sub transition hover:bg-raise hover:text-txt">${ic('split', 'h-3 w-3')}拆分此镜头</button>
              </div>
              <p class="mt-1.5 flex items-center gap-1 text-[9.5px] text-dim">${ic('shield-check', 'h-2.5 w-2.5')}只影响镜头 ${esc(shot.no)}，其余 ${shots.length - 1} 个镜头不受影响</p>
              <button data-action="shot-delete" data-id="${shot.id}" class="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-danger/60 bg-danger/15 py-2 text-[12px] font-medium text-danger transition hover:border-danger hover:bg-danger/25">
                ${ic('trash-2', 'h-3.5 w-3.5')}删除片段
              </button>
            </div>
          </div>
        </div>
      </div>

      <aside class="flex w-[224px] shrink-0 flex-col border-l border-line bg-[#0E0F12] py-3">
        <div class="flex items-center justify-between px-3">
          <span class="text-[10.5px] tracking-[0.1em] text-sub">镜头清单</span>
          <span class="text-[9.5px] text-dim">${shots.length} / ${total.toFixed(1)}s</span>
        </div>
        <div class="hide-scroll mt-2 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2">${list}</div>
        <div class="px-3 pt-2">
          <button data-action="generate-all-keyframes" class="mb-1.5 flex w-full items-center justify-center gap-1.5 rounded-md border border-amber/40 bg-amber/12 py-1.5 text-[10.5px] text-amber2 transition hover:bg-amber/20">
            ${ic('image', 'h-3 w-3')}一键生成所有首帧
          </button>
          <button data-action="generate-all-shots" class="mb-1.5 flex w-full items-center justify-center gap-1.5 rounded-md border border-amber/40 bg-amber/12 py-1.5 text-[10.5px] text-amber2 transition hover:bg-amber/20">
            ${ic('play', 'h-3 w-3')}一键生成所有镜头
          </button>
          <button data-action="shot-new" class="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-line2 py-1.5 text-[10.5px] text-sub transition hover:border-amber/40 hover:text-amber2">${ic('plus', 'h-3 w-3')}新增镜头</button>
        </div>
      </aside>
    </div>

    <div class="mt-1 border-t border-line">
      <div class="flex h-9 items-center gap-2 px-6">
        <div class="flex items-center gap-0.5 rounded-md border border-line bg-card p-0.5">
          ${['select:选择:mouse-pointer-2', 'blade:刀片:scissors', 'drag:拖动:hand'].map(t => {
            const [id, label, icon] = t.split(':');
            const on = S.video.tool === id;
            return `<button data-action="tool" data-id="${id}" class="flex items-center gap-1 rounded-[5px] px-2 py-1 text-[10.5px] ${on ? 'bg-raise text-txt' : 'text-sub'}">${ic(icon, `h-3 w-3 ${on ? 'text-amber' : ''}`)}${label}</button>`;
          }).join('')}
        </div>
        <span class="h-5 w-px bg-line"></span>
        <span class="flex items-center gap-1 rounded-md border border-line bg-card px-2 py-1 text-[10.5px] text-sub">${ic('magnet', 'h-3 w-3 text-amber')}吸附</span>
        <span class="flex items-center gap-1 rounded-md border border-line bg-card px-2 py-1 text-[10.5px] text-sub">${ic('audio-lines', 'h-3 w-3')}显示波形</span>
        <div class="ml-auto flex items-center gap-2 text-[10.5px] text-dim">
          ${ic('zoom-out', 'h-3 w-3')}
          <div class="relative h-[3px] w-[92px] rounded-full bg-line">
            <div class="absolute inset-y-0 left-0 w-[62%] rounded-full bg-sub"></div>
            <span class="absolute -top-[3px] left-[62%] h-[9px] w-[9px] -translate-x-1/2 rounded-full bg-txt"></span>
          </div>
          ${ic('zoom-in', 'h-3 w-3')}
          <span class="ml-2">${total.toFixed(1)}s / 共 ${shots.length} 段</span>
        </div>
      </div>

      <div class="flex">
        <div class="w-[136px] shrink-0 border-r border-line bg-[#0E0F12]">
          <div class="h-[22px] border-b border-line/60"></div>
          <div class="flex h-[66px] items-center gap-1.5 border-b border-line/50 px-2.5">
            ${ic('clapperboard', 'h-3 w-3 shrink-0 text-amber')}
            <span class="flex-1 truncate text-[10.5px] text-txt">镜头轨道</span>
            ${ic('lock', 'h-2.5 w-2.5 text-dim')}${ic('eye', 'h-2.5 w-2.5 text-dim')}
          </div>
          <div class="flex h-[44px] items-center gap-1.5 border-b border-line/50 px-2.5">
            ${ic('music', 'h-3 w-3 shrink-0 text-sub')}
            <span class="flex-1 truncate text-[10.5px] text-sub">BGM</span>
            ${ic('volume-2', 'h-2.5 w-2.5 text-dim')}${ic('lock', 'h-2.5 w-2.5 text-dim')}
          </div>
          <div class="flex h-[44px] items-center gap-1.5 px-2.5">
            ${ic('mic', 'h-3 w-3 shrink-0 text-sub')}
            <span class="flex-1 truncate text-[10.5px] text-sub">旁白</span>
            ${ic('volume-2', 'h-2.5 w-2.5 text-dim')}${ic('eye-off', 'h-2.5 w-2.5 text-dim')}
          </div>
        </div>

        <div class="relative min-w-0 flex-1 pr-6" id="timeline">
          <div id="ruler" class="relative flex h-[22px] cursor-pointer border-b border-line/60">
            ${ticks.map(t => `<span class="flex flex-1 border-r border-line/40 text-[9px] text-dim"><span class="ml-1">${t}s</span></span>`).join('')}
          </div>

          <div id="playhead" class="pointer-events-none absolute bottom-0 top-0 z-30 w-px bg-amber" style="left:${S.video.playhead}%">
            <span class="absolute -left-[4px] -top-[1px] h-0 w-0 border-l-[4.5px] border-r-[4.5px] border-t-[7px] border-l-transparent border-r-transparent border-t-amber"></span>
            <span id="playheadLabel" class="absolute -left-[15px] top-[6px] rounded-[3px] bg-amber px-1 py-[1px] font-mono text-[8px] font-medium text-[#1B0E05]">${cur.toFixed(1)}</span>
          </div>

          <div id="shotTrack" class="flex h-[66px] items-stretch gap-1 border-b border-line/50 pt-1.5">${track}</div>

          <div class="relative flex h-[44px] items-center border-b border-line/50">
            ${audioMats.length ? audioMats.map((m, i) => `
              <div class="absolute inset-y-1 overflow-hidden rounded-[5px] border border-line2/80 bg-[#15171B]" style="left:${2 + i * 12}%;width:${Math.max(18, 100 / Math.max(2, audioMats.length) - 4)}%">
                <span class="absolute left-2 top-1/2 -translate-y-1/2 truncate pr-2 text-[8.5px] text-sub">${esc(m.label)}</span>
              </div>`).join('') : `<div class="absolute inset-y-1 left-0 right-0 flex items-center justify-center rounded-[5px] border border-dashed border-line2/70 text-[8.5px] text-dim">还没有 BGM，音频素材后续接入</div>`}
          </div>

          <div class="relative flex h-[44px] items-center">
            ${audioMats.length ? '' : `<button data-action="narration-add" class="absolute inset-y-1 left-[6%] w-[46%] overflow-hidden rounded-[5px] border border-dashed border-line2 bg-[#141619]">
              <span class="absolute inset-0 flex items-center justify-center gap-1 text-[8.5px] text-dim">${ic('plus', 'h-2.5 w-2.5')}拖入旁白或对白</span>
            </button>`}
          </div>
        </div>
      </div>
    </div>

    <div class="mt-auto flex h-[196px] shrink-0 border-t border-line2 bg-[#0E0F12]">
      <div class="flex min-w-0 flex-1 flex-col px-6 py-3">
        ${verifyPanel()}
      </div>

      <div class="flex w-[560px] shrink-0 flex-col border-l border-line2 px-5 py-3">
        <div class="flex items-center gap-2">
          <span class="flex items-center gap-1.5 text-[11px] text-txt">${ic('text-cursor-input', 'h-3 w-3 text-amber')}用一句话改片</span>
          <span class="text-[10px] text-dim">支持撤销</span>
        </div>
        <div class="mt-2 flex items-center gap-2 rounded-md border border-line/70 bg-card/60 px-2 py-1.5 text-[10px]">
          ${ic('history', 'h-3 w-3 shrink-0 text-sub')}
          <span id="lastEdit" class="truncate text-sub">${esc(S.lastEdit || '还没有执行过文字剪辑')}</span>
        </div>
        <div class="mt-2 flex items-start gap-2 rounded-lg border border-line2 bg-card p-2 transition focus-within:border-amber/45">
          ${ic('wand-sparkles', 'mt-[3px] h-3.5 w-3.5 shrink-0 text-amber')}
          <textarea id="textEditInput" rows="2" placeholder="写出你想怎么改，回车执行" class="min-w-0 flex-1 resize-none bg-transparent text-[11.5px] leading-[1.6] text-txt placeholder:text-dim"></textarea>
          <button data-action="text-edit" class="grad-amber flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-[#1B0E05]">
            执行${ic('corner-down-left', 'h-3 w-3')}
          </button>
        </div>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <button data-action="text-edit-suggest" data-id="压缩到 10 秒" class="rounded-full border border-line px-2 py-[3px] text-[10px] text-sub transition hover:border-amber/40 hover:text-txt">压缩到 10 秒</button>
          <button data-action="text-edit-suggest" data-id="删除第 3 个镜头" class="rounded-full border border-line px-2 py-[3px] text-[10px] text-sub transition hover:border-amber/40 hover:text-txt">删除第 3 个镜头</button>
          <button data-action="text-edit-suggest" data-id="给全片加冷调" class="rounded-full border border-line px-2 py-[3px] text-[10px] text-sub transition hover:border-amber/40 hover:text-txt">给全片加冷调</button>
        </div>
        <div class="mt-auto flex items-center justify-between border-t border-line/60 pt-2 text-[9.5px] text-dim">
          <span class="flex items-center gap-1">${ic('shield-check', 'h-2.5 w-2.5')}锁定设定不会被文字指令改动</span>
          <span>可撤销 ${S.undo.length} 步</span>
        </div>
      </div>
    </div>
  </div>`;
}

/* 抽帧校验面板：S.video.verify 有四种状态——没校验过 / 校验中 / 通过 / 不通过 */
function verifyPanel() {
  const v = S.video.verify || null;
  const shot = S.shots.find(s => s.id === S.video.shotId) || S.shots[0] || null;
  const hasClip = !!(shot && shot.clipPath);
  const state = !v ? '未校验' : v.loading ? '校验中…' : v.error ? '校验失败' : v.pass ? '通过' : '不通过';
  const stateCls = !v || v.loading || v.error ? 'text-dim' : v.pass ? 'text-ok' : 'text-amber2';

  let body;
  if (v && v.loading) {
    body = `<div class="flex flex-1 items-center gap-2 text-[10.5px] text-sub">
      ${ic('refresh-cw', 'h-3.5 w-3.5 animate-spin text-amber')}正在从成片里抽 3 帧，和设定图逐张比对…
    </div>`;
  } else if (v && v.error) {
    body = `<div class="flex flex-1 items-center gap-2 text-[10.5px] text-amber2">
      ${ic('alert-triangle', 'h-3.5 w-3.5 shrink-0')}<span class="truncate">${esc(v.error)}</span>
    </div>`;
  } else if (v && v.frames && v.frames.length) {
    const thumbs = v.frames
      .map(f => `<img src="${esc(f.url)}" alt="" class="h-12 w-[76px] shrink-0 rounded-[4px] border border-line object-cover" />`)
      .join('');
    const issues = (v.issues || [])
      .slice(0, 2)
      .map(t => `<li class="truncate">· ${esc(t)}</li>`)
      .join('');
    body = `<div class="flex min-w-0 flex-1 items-center gap-2.5">
      <div class="flex shrink-0 gap-1.5">${thumbs}</div>
      <div class="min-w-0 flex-1">
        <p class="text-[11.5px] ${v.pass ? 'text-ok' : 'text-amber2'}">${v.pass ? '通过：和设定图是同一个主体' : '不通过：主体和设定图对不上'}</p>
        ${issues ? `<ul class="mt-0.5 space-y-[1px] text-[10px] text-dim">${issues}</ul>` : `<p class="mt-0.5 text-[10px] text-dim">没有发现明显差异</p>`}
      </div>
    </div>`;
  } else {
    body = `<div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-amber/30 bg-amber/10">
        ${ic('scan-face', 'h-4 w-4 text-amber')}
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-[11.5px] text-txt">视频角色一致度校验</p>
        <p class="mt-0.5 truncate text-[10px] text-dim">从这一镜的成片里抽 3 帧，和角色三视图比对长相、服装、场景关键物件</p>
      </div>`;
  }

  return `<div class="flex items-center gap-2">
      <span class="flex items-center gap-1.5 text-[11px] text-sub">${ic('shield-check', 'h-3 w-3')}校验</span>
      <span class="rounded-[4px] border border-amber/30 bg-amber/10 px-1.5 py-[2px] text-[9.5px] text-amber2">角色一致度</span>
      <span class="ml-auto text-[10px] ${stateCls}">${state}</span>
    </div>
    <div class="mt-2.5 flex flex-1 items-center gap-3 rounded-md border border-dashed border-line2/70 bg-card/30 px-4 py-2">
      ${body}
      <button data-action="video-verify" ${hasClip ? '' : 'disabled'} class="flex shrink-0 items-center gap-1 rounded-md border border-amber/45 bg-amber/10 px-2.5 py-1 text-[10.5px] text-amber2 transition hover:bg-amber/20 disabled:cursor-not-allowed disabled:opacity-40">
        ${ic('scan', 'h-3 w-3')}${v && !v.loading && !v.error && v.frames ? '重新校验' : '开始校验'}
      </button>
    </div>
    <div class="mt-auto flex items-center gap-2 rounded-md border border-line/70 bg-card/50 px-2.5 py-1.5 text-[10px] text-dim">
      ${ic('info', 'h-3 w-3 shrink-0')}
      <span>${hasClip ? '校验通过后再进成片确认；不通过就重抽这一镜。' : '这一镜还没有成片，先在右侧镜头清单里生成视频。'}</span>
    </div>`;
}
