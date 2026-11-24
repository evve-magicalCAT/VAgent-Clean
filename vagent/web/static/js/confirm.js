/* Vagent · 成片确认视图
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, S, currentProject, emptyBlock, esc, fmtDur, ic, totalDur } from './core.js';
import { statusPill } from './video.js';
/* ---------- 4.5 成片确认 ---------- */
export function confirmStats() {
  return {
    ok: S.shots.filter(hasVerdict).length,
    pending: S.shots.filter(x => x.clipPath && !hasVerdict(x) && x.review?.verdict !== 'error').length,
    redraw: S.shots.filter(x => x.status === 'redraw').length
  };
}

function hasVerdict(s) {
  return ['pass', 'fail', 'uncertain'].includes(s.review?.verdict)
    && (s.review.target == null || s.review.target === s.prompt);
}

export function canReview(s) {
  return Boolean(s.clipPath) && (s.review?.mode !== 'auto' ||
    (s.review.state === 'done' && (!s.review.reason || !hasVerdict(s))));
}

function assessment(s) {
  const r = s.review || {};
  const labels = { pass: '一致', fail: '不一致', uncertain: '证据不足' };
  if (r.verdict === 'error') return `<strong class="text-danger">审核失败</strong><p>${esc(r.summary)}</p>`;
  if (hasVerdict(s)) {
    const color = { pass: 'text-ok', fail: 'text-danger', uncertain: 'text-amber2' }[r.verdict];
    return `<strong class="${color}">${labels[r.verdict]}</strong><p class="whitespace-pre-wrap">${esc(r.reason || '')}</p>`;
  }
  if (r.target != null && r.state === 'done' && r.target !== s.prompt) return '提示词已修改，待重新判定';
  if (r.mode === 'auto') return '等待自动审核';
  return s.clipPath ? '待判定' : '待生成视频';
}

export function confirmRow(s) {
  const review = s.review || {};
  const redraw = s.status === 'redraw';
  const border = redraw ? 'border-amber/35' : s.status === 'modified' ? 'border-line2 shadow-[0_0_0_1px_rgba(245,129,60,.12)]' : 'border-line';
  return `
    <article data-confirm-row="${s.id}" class="grid grid-cols-1 gap-3 rounded-lg border ${border} bg-card p-3 md:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)_minmax(0,.8fr)]">
      <header class="col-span-full flex flex-wrap items-center gap-2 border-b border-line pb-2">
        <strong class="text-[12px]">镜头 ${esc(s.no)}</strong><span class="text-[11px] text-sub">${fmtDur(s.dur)} · ${esc(s.name)}</span>
        <span class="ml-auto text-[11px] text-sub" data-status-pill="${s.id}">${s.clipPath ? '已出片' : statusPill(s.status, { progress: s.progress })}</span>
        ${redraw ? `<button data-action="shot-stop" data-id="${s.id}" class="rounded border border-line2 px-3 py-1 text-sub">停止重绘</button>`
          : `<button data-action="shot-redo" data-id="${s.id}" class="flex items-center gap-1.5 rounded-md border border-amber bg-amber/15 px-3 py-1.5 text-[12px] font-semibold text-amber2 hover:bg-amber/25">${ic('rotate-ccw', 'h-3.5 w-3.5')}单镜重做</button>`}
      </header>
      <div class="flex items-start gap-1.5 md:flex-col">
        <div class="relative h-[70px] w-[112px] overflow-hidden rounded-[6px] border border-line bg-[#0C0E11]">
          <div class="absolute inset-0" style="background:linear-gradient(160deg,${(s.tones || ['#2A323A'])[0]} 0%,#11151A 72%)"></div>
          <svg viewBox="0 0 200 125" preserveAspectRatio="xMidYMid slice" class="absolute inset-0 h-full w-full" style="color:#6E7884" role="img" aria-label="镜头 ${esc(s.no)} 首帧"><use href="#shot-${s.frame}"/></svg>
          ${s.clipPath ? `<video src="${esc(s.clipPath)}#t=0.1" muted playsinline preload="metadata" class="pointer-events-none absolute inset-0 h-full w-full object-cover"></video>` : ''}
          ${redraw ? `<div class="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-base/78">${ic('loader-circle', 'h-3.5 w-3.5 animate-spin text-amber')}<div class="h-[2.5px] w-[58px] overflow-hidden rounded-full bg-line"><div class="grad-amber h-full" style="width:${s.progress}%"></div></div><span class="text-[8px] text-amber2">${s.progress}%</span></div>` : ''}
          <span class="absolute left-1 top-1 rounded-[3px] bg-black/55 px-1 py-[1px] text-[8.5px] text-amber2">首帧</span>
        </div>
        <div class="relative h-[70px] w-[112px] overflow-hidden rounded-[6px] border border-line bg-[#0C0E11]">
          <div class="absolute inset-0" style="background:linear-gradient(160deg,${(s.tones || ['#2A323A'])[1] || (s.tones || ['#2A323A'])[0]} 0%,#131820 72%)"></div>
          <svg viewBox="0 0 200 125" preserveAspectRatio="xMidYMid slice" class="absolute inset-0 h-full w-full scale-x-[-1]" style="color:#707A86" role="img" aria-label="镜头 ${esc(s.no)} 末帧"><use href="#shot-${s.frame}"/></svg>
          ${redraw ? `<div class="skeleton absolute inset-0"></div>` : ''}
          <span class="absolute left-1 top-1 rounded-[3px] bg-black/55 px-1 py-[1px] text-[8.5px] text-sub">末帧</span>
        </div>
      </div>

      <div class="min-w-0 text-[11px] leading-relaxed">
        <label class="mb-1 block font-semibold" for="confirm-prompt-${s.id}">镜头提示词</label>
        <div>
          <textarea id="confirm-prompt-${s.id}" data-confirm-prompt="${s.id}" rows="3" spellcheck="false" placeholder="写这一镜的提示词……" class="block w-full resize-y bg-transparent text-sub focus:text-txt focus:outline-amber/50" style="field-sizing:content">${esc(s.prompt)}</textarea>
          <div class="mt-1 flex items-center justify-end gap-2">
            ${s.ai ? `<span class="mr-auto flex items-center gap-1 rounded-[3px] bg-amber/12 px-1 py-[1px] text-[9px] text-amber2/90">${ic('sparkles', 'h-2 w-2')}AI 补充 ${esc(s.ai)}</span>` : ''}
            <button data-action="asset-enrich-shot" data-id="${s.id}" class="flex items-center gap-1 rounded-[3px] border border-line px-1 py-[1px] text-[9px] text-sub transition hover:border-amber/40 hover:text-amber2">${ic('sparkles', 'h-2 w-2')}AI 丰富</button>
            <button data-action="shot-regen-keys" data-id="${s.id}" class="flex items-center gap-1 text-[9px] text-dim transition hover:text-sub">${ic('refresh-cw', 'h-2 w-2')}重新生成关键帧</button>
          </div>
        </div>
      </div>

      <div class="min-w-0 text-[11px] leading-relaxed md:border-l md:border-line md:pl-3">
        <strong>Agent 画面复述</strong>
        <p class="mt-1 whitespace-pre-wrap break-words text-sub">${esc(review.verdict !== 'error' && review.summary || (s.clipPath ? '待复述' : '待生成视频'))}</p>
      </div>
      <div class="min-w-0 text-[11px] leading-relaxed md:border-l md:border-line md:pl-3">
        <strong>生成一致性</strong>
        <div data-assessment class="mt-1 break-words text-sub">${assessment(s)}</div>
      </div>
    </article>`;
}

export function finalPlayer(run, compact = false) {
  if (run?.status !== 'done' || run.subId !== S.current.subId || !run.exportUrl?.startsWith('/uploads/')) return '';
  const url = esc(run.exportUrl);
  return `<div class="my-2">
    <video aria-label="全自动成片" controls playsinline preload="metadata" src="${url}" class="block w-full ${compact ? 'max-h-[168px]' : 'max-h-[300px]'} rounded-md bg-base object-contain"></video>
    <a download class="text-[11px] text-amber2 underline" href="${url}">下载成片 MP4</a>
  </div>`;
}

export function renderConfirm() {
  const st = confirmStats();
  const total = totalDur();
  const proj = currentProject();
  const rows = S.shots.map(confirmRow).join('');

  return `
  <div class="flex h-full min-h-0 flex-col">
    <div class="flex h-11 shrink-0 items-center gap-3 border-b border-line/70 bg-[#0E0F12] px-6">
      <button data-action="back-to-video" class="flex items-center gap-1 text-[10.5px] text-dim transition hover:text-sub">${ic('film', 'h-3 w-3')}视频${ic('chevron-right', 'h-2.5 w-2.5')}</button>
      <h2 class="max-w-[300px] truncate text-[13.5px] font-medium">${esc(proj ? proj.name : '还没有项目')}${proj ? ' · ' + esc(proj.kind) : ''}</h2>
      <span class="shrink-0 rounded-[4px] border border-line px-1.5 py-[1px] text-[9.5px] text-dim">${esc(S.current.sub || '未分集')}</span>
      <span class="flex shrink-0 items-center gap-1 rounded-[4px] bg-amber/10 px-1.5 py-[2px] text-[9.5px] text-amber2">
        ${S.shots.filter(s => s.clipPath).length} 个镜头已出片
      </span>
      <div class="ml-auto flex items-center gap-2 text-[10.5px] text-dim">${ic('history', 'h-3 w-3')}${esc(S.savedAt ? S.savedAt.slice(5, 16) + ' 保存' : '')}</div>
    </div>

    <div class="flex shrink-0 items-center gap-6 border-b border-line/60 px-6 py-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <h1 class="text-[15px] font-semibold tracking-tight">成片确认</h1>
        </div>
        <p class="mt-1 text-[11.5px] text-sub">共 ${S.shots.length} 个镜头 · 画面抽帧审核 · 不含音轨</p>
        <p class="mt-0.5 flex items-center gap-1 text-[10px] text-dim">${ic('link-2', 'h-2.5 w-2.5')}与时间轴共用同一组镜头数据，这里改的提示词会同步到「视频」的时间轴</p>
      </div>
      <div class="ml-auto flex items-center gap-3">
        <div class="flex items-center gap-3 rounded-lg border border-line bg-card px-3 py-2 text-[10.5px]">
          <span class="flex items-center gap-1 text-ok">${ic('check-circle-2', 'h-3 w-3')}已有结论 <span id="statOk">${st.ok}</span></span>
          <span class="h-3 w-px bg-line"></span>
          <span class="flex items-center gap-1 text-amber2"><span class="h-1.5 w-1.5 rounded-full bg-amber2"></span>待确认 <span id="statPending">${st.pending}</span></span>
          <span class="h-3 w-px bg-line"></span>
          <span class="flex items-center gap-1 text-sub">${ic('loader-circle', 'h-3 w-3')}重绘 <span id="statRedraw">${st.redraw}</span></span>
        </div>
        <button data-action="back-to-video" class="flex h-9 items-center gap-1.5 rounded-lg border border-line2 px-3 text-[12px] text-sub transition hover:bg-raise hover:text-txt">
          ${ic('arrow-left', 'h-3.5 w-3.5')}返回调整
        </button>
        <button data-action="shot-review" class="grad-amber flex h-9 items-center gap-1.5 rounded-lg px-3.5 text-[12.5px] font-medium text-[#1B0E05] transition hover:brightness-105 disabled:opacity-70" ${!S.busy.shotReview && S.shots.some(canReview) ? '' : 'disabled'}>
          <span class="flex items-center gap-1.5">${ic('clapperboard', 'h-3.5 w-3.5')}${S.busy.shotReview ? '复述中…' : '开始确认'}
            <span class="ml-0.5 rounded bg-black/15 px-1.5 py-[1px] text-[9.5px] font-normal">${Math.round(total)}s</span>
          </span>
        </button>
      </div>
    </div>

    <div class="hide-scroll min-h-0 flex-1 overflow-y-auto px-6 py-3">
      ${finalPlayer(S.autoRun)}
      ${S.shots.length ? `<div class="flex flex-col gap-2">${rows}</div>` : emptyBlock({
        icon: 'clapperboard', title: '还没有可确认的镜头',
        desc: '先在「视频」里新增镜头并写好提示词，再回到这里逐个确认。',
        action: 'shot-new', label: '新增镜头'
      })}
    </div>

    <div class="flex h-11 shrink-0 items-center gap-3 border-t border-line bg-[#0E0F12] px-6 text-[10px] text-dim">
      ${ic('info', 'h-3 w-3 shrink-0')}
      <span>首帧与末帧共同决定运镜；只改提示词不会重绘关键帧，点「重新生成关键帧」才会。</span>
      <span class="ml-auto flex items-center gap-1">${ic('shield-check', 'h-2.5 w-2.5')}锁定设定的资产在逐镜生成时不会被改动</span>
    </div>
  </div>`;
}

export function updateConfirmStats(shot) {
  if (shot) {
    const field = document.getElementById('confirm-prompt-' + shot.id);
    const result = field?.closest('article')?.querySelector('[data-assessment]');
    if (result) result.innerHTML = assessment(shot);
    const button = $('[data-action="shot-review"]');
    if (button) button.disabled = S.busy.shotReview || !S.shots.some(canReview);
  }
  const st = confirmStats();
  const a = $('#statOk'), b = $('#statPending'), d = $('#statRedraw');
  if (a) a.textContent = st.ok;
  if (b) b.textContent = st.pending;
  if (d) d.textContent = st.redraw;
}
