/* Vagent · 对话视图与本地分析
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, S, currentProject, emptyLine, esc, fmtDur, ic, totalDur } from './core.js';
import { finalPlayer } from './confirm.js';
/* ---------- 4.2 对话 ---------- */

/* 本地分析一句话：不调用模型，只做关键词抽取 */
export function analyzePrompt(text) {
  const slots = [];
  const durMatch = text.match(/(\d+(?:\.\d+)?)\s*(?:秒|s\b|sec)/i);
  const roleMap = [['女人', '女性角色'], ['男人', '男性角色'], ['女孩', '女孩'], ['男孩', '男孩'], ['老人', '老人'], ['店员', '店员']];
  const sceneMap = [['便利店', '便利店'], ['街道', '街道'], ['街', '街道'], ['房间', '室内'], ['公路', '公路'], ['加油站', '加油站'], ['仓库', '仓库'], ['海边', '海边'], ['森林', '森林'], ['办公室', '办公室']];
  const styleMap = [['电影感', '电影感'], ['冷调', '冷调'], ['暖调', '暖调'], ['黑白', '黑白'], ['黄昏', '黄昏'], ['夜景', '夜景'], ['雨', '雨夜']];

  const role = roleMap.find(([k]) => text.includes(k));
  const scene = sceneMap.find(([k]) => text.includes(k));
  const style = styleMap.find(([k]) => text.includes(k));

  slots.push({ kind: 'role', icon: 'user-round', label: '角色', value: role ? role[1] : '待补充', locked: !!role, missing: !role });
  slots.push({ kind: 'scene', icon: 'store', label: '场景', value: scene ? scene[1] : '待补充', locked: !!scene, missing: !scene });
  slots.push({ kind: 'dur', icon: 'timer', label: '镜头时长', value: durMatch ? `${durMatch[1]}s` : '4s', locked: false, missing: false });
  slots.push({ kind: 'style', icon: 'clapperboard', label: '风格', value: style ? style[1] : '待补充', locked: !!style, missing: !style });

  const questions = [];
  if (!role) questions.push({ q: '这一镜里有明确的人物吗？要不要把 TA 存成资产？', options: ['有，存成资产', '没有人物', '让 AI 决定'] });
  if (!scene) questions.push({ q: '场景是室内还是室外？具体是什么地方？', options: ['室内', '室外', '让 AI 决定'] });
  if (!durMatch) questions.push({ q: '这一镜多长？', options: ['3 秒', '4 秒', '6 秒'] });

  const stored = slots.filter(s => s.locked).length;
  const adjustable = slots.filter(s => !s.locked).length;
  return {
    type: 'analysis',
    slots,
    stored,
    adjustable,
    questions: questions.slice(0, 2)
  };
}

/* 后端分镜 → 消息 meta：沿用 slots 结构，原始 plan 另外存一份 */
export function planMeta(plan) {
  const assets = plan.assets || [];
  const shots = plan.shots || [];
  const slots = assets.map(a => ({
    kind: 'asset',
    icon: a.type === '场景' ? 'store' : a.type === '风格' ? 'palette' : 'user-round',
    label: a.type,
    value: a.name,
    locked: !!a.locked,
    missing: false
  }));
  const total = shots.reduce((sum, s) => sum + Number(s.dur || 0), 0);
  if (shots.length) {
    slots.push({
      kind: 'dur', icon: 'timer', label: '镜头时长',
      value: `${shots.length} 镜 · ${total.toFixed(1)}s`, locked: false, missing: false
    });
  }
  return {
    type: 'plan',
    draft: true,
    plan,
    slots,
    stored: assets.filter(a => a.locked).length,
    adjustable: shots.length,
    questions: (plan.questions || []).map(q => ({ q: q.text, options: q.options || [] }))
  };
}

export function scrollChatToBottom() {
  const el = document.getElementById('chatThread');
  if (el) el.scrollTop = el.scrollHeight;
}

/* 分镜大纲：只在模型返回了镜头时渲染 */
export function planBlock(plan) {
  const shots = (plan && plan.shots) || [];
  if (!shots.length) return '';
  const total = shots.reduce((sum, s) => sum + Number(s.dur || 0), 0);
  return `
    <div class="mt-2.5 rounded-lg border border-line bg-panel/60 p-2.5">
      <div class="flex items-center gap-1.5 text-[10px] text-dim">
        ${ic('clapperboard', 'h-3 w-3 text-amber/80')}分镜大纲 · ${shots.length} 镜 · ${total.toFixed(1)}s
      </div>
      <div class="mt-1.5 flex flex-col gap-1">
        ${shots.map((s, i) => `
          <div class="flex items-start gap-2">
            <span class="mt-[1px] shrink-0 text-[9px] tabular-nums text-dim">${String(i + 1).padStart(2, '0')}</span>
            <span class="min-w-0 flex-1">
              <span class="flex items-baseline gap-1.5">
                <span class="truncate text-[11px] text-txt">${esc(s.name)}</span>
                <span class="shrink-0 text-[9px] tabular-nums text-dim">${fmtDur(s.dur)}</span>
              </span>
              <span class="mt-[1px] line-clamp-2 block text-[10px] leading-[1.55] text-sub">${esc(s.prompt)}</span>
            </span>
          </div>`).join('')}
      </div>
    </div>`;
}

function askModifyKind(text) {
  const t = String(text || '');
  const shot =
    /(修改|更新|调整).{0,10}(镜头|分镜).{0,6}(描述|提示词)/.test(t) ||
    /(镜头|分镜).{0,6}(描述|提示词).{0,10}(修改|更新|调整)/.test(t);
  if (shot) return 'shot';
  const asset =
    /(重新出|重新生成|更新|修改|调整).{0,12}(设定图|资产|三视图|外观|形象|描述)/.test(t) ||
    /(设定图|资产|三视图).{0,12}(修改|更新|调整|重新生成)/.test(t);
  return asset ? 'asset' : '';
}

function assetProposalCard(p, m) {
  const clicked = (S.proposalClicked && S.proposalClicked[m.id]) || (m.meta && m.meta.proposalClicked) || '';
  const locked = clicked ? 'disabled opacity-60' : '';
  const adjustLabel = clicked === 'adjust'
    ? `${ic('check', 'h-3 w-3')}已进入调整`
    : '不满意，继续调整';
  const generateLabel = clicked === 'generate'
    ? `${ic('check', 'h-3 w-3')}已提交`
    : `${ic('sparkles', 'h-3 w-3')}就这样生成`;
  return `<div class="mt-3 overflow-hidden rounded-lg border border-amber/35 bg-amber/8">
    <div class="flex items-center gap-1.5 px-3 py-2 text-[10px] text-amber2">
      ${ic('file-pen-line', 'h-3 w-3')}变更方案 · 待确认
    </div>
    <div class="px-3 pb-2">
      <p class="text-[11.5px] text-txt">${esc(p.assetName)}${p.type ? ` · ${esc(p.type)}` : ''}</p>
      <p class="mt-1 whitespace-pre-wrap text-[10.5px] leading-relaxed text-sub">${esc(p.changes || p.desc || '')}</p>
    </div>
    <div class="flex items-center justify-end gap-2 border-t border-line/60 px-3 py-2">
      <button data-action="asset-proposal-adjust" data-msg="${m.id}" class="flex items-center gap-1 rounded-md border border-line2 px-2.5 py-1 text-[10.5px] text-sub transition hover:bg-raise hover:text-txt ${locked}">${adjustLabel}</button>
      <button data-action="asset-proposal-generate" data-msg="${m.id}" data-id="${p.assetId}" class="flex items-center gap-1 rounded-md border border-amber/55 bg-amber/12 px-2.5 py-1 text-[10.5px] font-medium text-amber2 transition hover:bg-amber/20 ${locked}">${generateLabel}</button>
    </div>
  </div>`;
}

function assetDraftCard(draft, m) {
  const previews = (draft.previews || []).slice(0, 3);
  const grid = previews.length === 1 ? 'grid-cols-1' : previews.length >= 3 ? 'grid-cols-3' : 'grid-cols-2';
  const clicked = (S.draftClicked && S.draftClicked[m.id]) || (m.meta && m.meta.draftClicked) || '';
  const locked = clicked ? 'disabled opacity-60' : '';
  const keepLabel = clicked === 'keep'
    ? `${ic('check', 'h-3 w-3')}已保留`
    : '不保存到资产（后台保留）';
  const saveLabel = clicked === 'save'
    ? `${ic('check', 'h-3 w-3')}已保存`
    : `${ic('save', 'h-3 w-3')}保存到资产（覆盖）`;
  return `<div class="mt-3 overflow-hidden rounded-lg border border-line2 bg-card">
    <div class="flex items-center gap-1.5 px-3 py-2 text-[10px] text-sub">
      ${ic('images', 'h-3 w-3')}新设定图预览 · 未覆盖资产
    </div>
    ${previews.length ? `<div class="grid ${grid} gap-1 px-2">
      ${previews.map(item => `<img src="${esc(item.url)}" alt="${esc(draft.assetName)}" loading="lazy" class="max-h-[220px] w-full cursor-zoom-in rounded-md border border-line object-contain" />`).join('')}
    </div>` : ''}
    <div class="flex flex-wrap items-center justify-end gap-2 px-3 py-2">
      <button data-action="asset-draft-keep" data-msg="${m.id}" class="flex items-center gap-1 rounded-md border border-line2 px-2.5 py-1 text-[10.5px] text-sub transition hover:bg-raise hover:text-txt ${locked}">${keepLabel}</button>
      <button data-action="asset-draft-save" data-msg="${m.id}" class="flex items-center gap-1 rounded-md border border-amber/55 bg-amber/12 px-2.5 py-1 text-[10.5px] font-medium text-amber2 transition hover:bg-amber/20 ${locked}">${saveLabel}</button>
    </div>
  </div>`;
}

function assetUpdateCard(asset, m) {
  const previews = (asset.previews || []).slice(0, 3);
  const grid = previews.length === 1 ? 'grid-cols-1' : previews.length >= 3 ? 'grid-cols-3' : 'grid-cols-2';
  return `<div class="mt-3 overflow-hidden rounded-lg border border-amber/35 bg-amber/8">
    <div class="flex items-center gap-1.5 px-3 py-2 text-[10px] text-amber2">
      ${ic('layers', 'h-3 w-3')}设定图已更新${asset.type ? ` · ${esc(asset.type)}` : ''}
    </div>
    ${previews.length ? `<div class="grid ${grid} gap-1 px-2">
      ${previews.map(url => {
        const stamp = String(asset.updatedAt || '').replace(/\D/g, '');
        const src = stamp ? url + (url.includes('?') ? '&' : '?') + 'v=' + stamp : url;
        return `<img src="${esc(src)}" alt="${esc(asset.name)}" loading="lazy" class="max-h-[220px] w-full cursor-zoom-in rounded-md border border-line object-contain" />`;
      }).join('')}
    </div>` : ''}
    <div class="flex items-center gap-2 px-3 py-2">
      <div class="min-w-0 flex-1">
        <p class="truncate text-[11.5px] text-txt">${esc(asset.name)}</p>
        <p class="mt-0.5 truncate text-[9.5px] text-dim">${esc(asset.desc || '')}</p>
      </div>
      <button data-action="asset-jump" data-id="${asset.id}" class="flex shrink-0 items-center gap-1 rounded-md border border-amber/45 bg-amber/12 px-2.5 py-1 text-[10.5px] text-amber2 transition hover:bg-amber/20">
        ${ic('arrow-up-right', 'h-3 w-3')}去资产库查看
      </button>
    </div>
  </div>`;
}

export function chatMessageHtml(m) {
  const meta = m.meta || {};
  const draft = !!meta.draft;
  if (m.role === 'user') {
    const att = meta.attachment;
    return `
      <div class="mt-3 flex justify-end gap-2.5">
        <div class="max-w-[540px] rounded-[10px] rounded-tr-[3px] border border-line2/80 bg-raise px-3.5 py-2.5">
          <p class="whitespace-pre-wrap text-[13.5px] leading-[1.65] text-txt">${esc(m.text)}</p>
          ${att ? (att.kind === '图片' && att.url
            ? `<div class="mt-2">
                <img src="${esc(att.url)}" alt="${esc(att.name)}" loading="lazy" class="max-h-[220px] w-auto max-w-full cursor-zoom-in rounded-lg border border-line bg-black/20 object-contain" />
                <div class="mt-1 flex items-center gap-1 text-[10px] text-dim">${ic('image', 'h-3 w-3')}${esc(att.name)}</div>
              </div>`
            : `<div class="mt-2 flex items-center gap-2 rounded-md border border-line bg-panel/80 px-1.5 py-1">
                <div class="relative h-6 w-8 shrink-0 overflow-hidden rounded-[3px] bg-raise"></div>
                <span class="truncate text-[10.5px] text-sub">${esc(att.name)}</span>
                <span class="shrink-0 text-[10px] text-dim">${esc(att.kind || '附件')}</span>
              </div>`) : ''}
        </div>
        <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line2 bg-raise">${ic('user-round', 'h-3.5 w-3.5 text-sub')}</div>
      </div>`;
  }

  const slots = Array.isArray(meta.slots) ? meta.slots : [];
  const images = Array.isArray(meta.images) ? meta.images : [];
  return `
    <div class="mt-3 flex gap-2.5">
      <div class="grad-amber mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px]">
        ${ic('sparkles', 'h-3.5 w-3.5 text-[#1B0E05]')}
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="text-[12px] font-medium text-txt">Vagent</span>
          <span class="text-[10.5px] text-dim">${esc((m.createdAt || '').slice(11, 16))}</span>
        </div>
        <div class="mt-1.5 rounded-[10px] border border-line bg-card p-3.5">
          <p class="text-[13.5px] leading-[1.7] text-txt">${esc(m.text)}</p>
          ${(() => {
            const isLast = S.messages.length && String(S.messages[S.messages.length - 1].id) === String(m.id);
            const kind = isLast && !meta.finalPrompt && !(meta.questions || []).length ? askModifyKind(m.text) : '';
            if (!kind) return '';
            return `<div class="mt-2 flex justify-end">
              <button data-action="confirm-modify" data-id="${m.id}" data-kind="${kind}" class="amber-ring flex items-center gap-1.5 rounded-lg border border-amber/55 bg-amber/12 px-3 py-1.5 text-[11.5px] font-medium text-amber2 transition hover:border-amber hover:bg-amber/20">
                ${ic('check', 'h-3 w-3 text-amber')}${kind === 'asset' ? '确认修改资产' : '确认修改镜头'}
              </button>
            </div>`;
          })()}
          ${images.length ? `<div class="mt-2 grid ${images.length === 1 ? 'grid-cols-1' : images.length >= 3 ? 'grid-cols-3' : 'grid-cols-2'} gap-2">
            ${images.map((im, i) => `<figure class="overflow-hidden rounded-lg border border-line bg-[#0C0D10] ${images.length === 1 ? 'mx-auto w-fit max-w-full' : ''}">
              <img src="${esc(im.url)}" alt="${esc(im.name)}" loading="lazy" class="${images.length === 1 ? 'block max-h-[420px] max-w-full cursor-zoom-in object-contain' : 'max-h-[260px] w-full cursor-zoom-in object-contain'}" />
              <figcaption class="flex items-center justify-between gap-2 px-2 py-1">
                <span class="min-w-0 truncate text-[9.5px] text-dim">${esc(im.name)}</span>
                <button data-action="chat-save-image" data-id="${m.id}" data-index="${i}" class="flex shrink-0 items-center gap-1 text-[9.5px] text-sub transition hover:text-amber2">
                  ${ic('folder-down', 'h-2.5 w-2.5')}转存到资产
                </button>
              </figcaption>
            </figure>`).join('')}
          </div>` : ''}
          ${(meta.assetUpdates || []).map(asset => assetUpdateCard(asset, m)).join('')}
          ${(meta.assetProposals || []).map(p => assetProposalCard(p, m)).join('')}
          ${meta.assetDraft ? assetDraftCard(meta.assetDraft, m) : ''}
          ${planBlock(meta.plan)}
          ${meta.plan && (meta.plan.assets || []).length ? `<div class="mt-2 flex flex-wrap items-center gap-2">
            <button data-action="chat-generate-images" data-id="${m.id}" class="flex items-center gap-1.5 rounded-lg border border-amber/40 bg-amber/12 px-2.5 py-1.5 text-[11.5px] text-amber2 transition hover:bg-amber/20">
              ${ic('image-plus', 'h-3 w-3')}生成资产图（${meta.plan.assets.length} 项）
            </button>
            <span class="text-[9.5px] text-dim">调用图片模型前会再确认</span>
          </div>` : ''}
          ${meta.plan && (meta.plan.shots || []).length && !(meta.questions || []).length ? `<div class="mt-2">
            <button data-action="chat-continue" class="flex items-center gap-1.5 rounded-lg border border-amber/40 bg-amber/12 px-2.5 py-1.5 text-[11.5px] text-amber2 transition hover:bg-amber/20">
              ${ic('arrow-right', 'h-3 w-3')}继续生成（${meta.plan.shots.length} 个镜头）
            </button>
          </div>` : ''}
          ${meta.finalPrompt ? `<div class="mt-3 rounded-lg border border-amber/40 bg-amber/10 p-3">
            <div class="flex items-center gap-1.5 text-[10px] text-amber2">${ic('file-text', 'h-3 w-3')}最终提示词 · 待确认</div>
            <p class="mt-1.5 whitespace-pre-wrap text-[12px] leading-relaxed text-txt">${esc(meta.finalPrompt.prompt)}</p>
            ${(meta.finalPrompt.shots || []).length > 1 ? `<div class="mt-2 space-y-1 border-t border-line/60 pt-2">
              ${(meta.finalPrompt.shots || []).map((shot, i) => `<div class="flex gap-2 text-[10px] text-sub">
                <span class="shrink-0 text-dim">0${i + 1}</span>
                <span class="line-clamp-1">${esc(shot.prompt)}</span>
                <span class="ml-auto shrink-0 text-dim">${shot.dur}s</span>
              </div>`).join('')}
            </div>` : ''}
            ${(meta.finalPrompt.assets || []).length ? `<p class="mt-1.5 text-[9.5px] text-dim">已转存资产：${esc(meta.finalPrompt.assets.join('、'))}</p>` : ''}
            ${(meta.finalPrompt.assetDetails || []).length ? `<div class="mt-2 border-t border-line/60 pt-2">
              <div class="mb-1.5 text-[10px] text-sub">本次提示词涉及的资产</div>
              <div class="flex flex-wrap gap-2">
                ${(meta.finalPrompt.assetDetails || []).map(asset => `<div class="flex min-w-[180px] items-center gap-2 rounded-md border border-line bg-panel/70 p-1.5">
                  ${(asset.preview || []).length ? `<img src="${esc(asset.preview[0])}" alt="${esc(asset.name)}" class="h-10 w-10 shrink-0 rounded object-cover" />` : `<span class="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-raise">${ic('image', 'h-3.5 w-3.5 text-dim')}</span>`}
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-[10.5px] text-txt">${esc(asset.name)}</div>
                    <div class="truncate text-[9px] text-dim">${esc(asset.type || '')}</div>
                  </div>
                  ${asset.needsReferenceViews ? `<button data-action="asset-reference-views" data-id="${esc(asset.id)}" class="shrink-0 rounded border border-amber/40 px-1.5 py-1 text-[9px] text-amber2">生成三视图</button>` : ''}
                </div>`).join('')}
              </div>
              ${(meta.finalPrompt.assetDetails || []).some(asset => asset.needsReferenceViews) ? `<p class="mt-1.5 text-[9.5px] text-dim">三视图生成后可替换资产里原来的用户参考图。</p>` : ''}
            </div>` : ''}
            <div class="mt-2 flex items-center justify-between gap-2">
              <span class="flex items-center gap-1 text-[9.5px] text-dim">${ic('clock', 'h-3 w-3')}${(meta.finalPrompt.shots || []).length || 1} 个镜头 · 到视频界面逐个生成</span>
              <div class="flex items-center gap-2">
                <button data-action="final-assets" data-id="${m.id}" class="amber-ring flex items-center gap-1.5 rounded-lg border border-amber/55 bg-amber/12 px-3 py-1.5 text-[11.5px] font-medium text-amber2 transition hover:border-amber hover:bg-amber/20">
                  ${ic('layers', 'h-3 w-3 text-amber')}生成相关资产
                </button>
                <button data-action="final-confirm" data-id="${meta.finalPrompt.shotId}" class="grad-amber flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-medium text-[#1B0E05]">
                  ${ic('arrow-right', 'h-3 w-3')}确认，去视频界面
                </button>
              </div>
            </div>
          </div>` : ''}
          ${meta.assetCard ? `<div class="mt-2 flex items-center gap-3 rounded-lg border border-line bg-panel/60 p-2">
            ${(meta.assetCard.preview || []).length
              ? `<img src="${esc(meta.assetCard.preview[0])}" alt="${esc(meta.assetCard.name)}" class="h-14 w-14 shrink-0 rounded-md border border-line object-cover" />`
              : `<span class="flex h-14 w-14 shrink-0 items-center justify-center rounded-md border border-line bg-raise">${ic('layers', 'h-5 w-5 text-amber')}</span>`}
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-[12px] font-medium text-txt">${esc(meta.assetCard.name)}</span>
                <span class="shrink-0 rounded-[3px] border border-line px-1 py-[1px] text-[8.5px] text-dim">${esc(meta.assetCard.type)}</span>
              </div>
              <p class="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-sub">${esc(meta.assetCard.desc || '')}</p>
            </div>
          </div>` : ''}
          ${meta.assetReferenceViews ? `<div class="mt-2 rounded-lg border border-amber/35 bg-amber/8 p-2.5">
            <div class="flex items-center gap-1.5 text-[11px] text-amber2">${ic('layers', 'h-3 w-3')}三视图已生成</div>
            <p class="mt-1 text-[10px] leading-relaxed text-sub">请确认是否用三视图替换资产里原来的用户参考图。替换后，后续镜头会统一使用三视图设定。</p>
            ${(meta.assetReferenceViews.previews || []).length ? `<div class="mt-2 grid grid-cols-3 gap-1.5">
              ${(meta.assetReferenceViews.previews || []).map(preview => `<img src="${esc(preview.url || '')}" alt="${esc(preview.label || '三视图')}" class="h-20 w-full rounded border border-line object-cover" />`).join('')}
            </div>` : ''}
            <div class="mt-2 flex gap-2">
              <button data-action="asset-reference-accept" data-id="${esc(meta.assetReferenceViews.assetId)}" class="rounded-lg border border-amber/45 bg-amber/12 px-2.5 py-1.5 text-[10.5px] text-amber2">用三视图替换</button>
              <button data-action="asset-reference-keep" class="rounded-lg border border-line2 px-2.5 py-1.5 text-[10.5px] text-sub">保留原图</button>
            </div>
          </div>` : ''}
          ${slots.length ? `
            <div class="mt-3 grid grid-cols-2 gap-2">
              ${slots.map(s => `
                <div class="flex items-center gap-2 rounded-lg border ${s.locked ? 'border-line bg-panel' : 'border-dashed border-line2/70'} px-2.5 py-1.5">
                  ${ic(s.icon, 'h-3.5 w-3.5 shrink-0 text-sub')}
                  <div class="min-w-0 flex-1">
                    <p class="text-[10px] leading-none text-dim">${esc(s.label)}</p>
                    <p class="mt-1 truncate text-[12px] leading-none ${s.missing ? 'text-dim' : 'text-txt'}">${esc(s.value)}</p>
                  </div>
                  ${s.locked
                    ? `<span class="flex shrink-0 items-center gap-1 rounded-[4px] bg-amber/10 px-1.5 py-[3px] text-[9.5px] text-amber2">${ic('lock', 'h-[9px] w-[9px]')}${draft ? '待存入' : '已存入资产'}</span>`
                    : `<span class="shrink-0 rounded-[4px] border border-line px-1.5 py-[2px] text-[9.5px] text-dim">可调</span>`}
                </div>`).join('')}
            </div>
            <div class="mt-2.5 flex items-center gap-3 text-[10.5px] text-sub">
              <span class="flex items-center gap-1">${ic('lock', 'h-3 w-3 text-amber/80')}${draft ? '将存入资产' : '已存入资产'} ${meta.stored || 0} 项</span>
              <span class="h-2.5 w-px bg-line2"></span>
              <span class="flex items-center gap-1">${ic('sliders-horizontal', 'h-3 w-3')}可改参数 ${meta.adjustable || 0} 项</span>
              <span class="ml-auto flex items-center gap-1 text-dim">${ic('database', 'h-3 w-3')}资产库共 ${S.assets.length} 项</span>
            </div>` : ''}
        </div>
      </div>
    </div>`;
}

const CLARIFY_MODULES = [
  { key: 'role', label: '角色', icon: 'user-round', hint: '外观 / 服装 / 配色' },
  { key: 'scene', label: '场景', icon: 'store', hint: '室内外 / 地点 / 光线' },
  { key: 'style', label: '风格', icon: 'palette', hint: '写实 / 动画 / 电影感' }
];

const CLARIFY_MODES = [
  { mode: 'image', label: '上传图片', icon: 'image-plus' },
  { mode: 'text', label: '文字描述', icon: 'pen-line' },
  { mode: 'auto', label: 'Agent 自动补全', icon: 'sparkles' }
];

function slotComplete(slot) {
  if (!slot || !slot.mode) return false;
  if (slot.mode === 'image') return !!slot.attachment;
  if (slot.mode === 'text') return !!(slot.text || '').trim();
  return true;
}

function clarifyValue(slot) {
  if (!slot || !slot.mode) return '待确认';
  if (slot.mode === 'image') return slot.attachment ? '已上传图片' : '待上传';
  if (slot.mode === 'auto') return 'Agent 自动补全';
  return slotComplete(slot) ? '已填文字' : '待填写';
}

export function chatQuestionCard(m) {
  const qs = (m.meta && m.meta.questions) || [];
  if (!qs.length) return '';
  const draft = S.clarify && S.clarify.msgId === m.id ? S.clarify : null;
  if (!draft) return '';
  const slots = draft.slots || {};
  const done = CLARIFY_MODULES.filter(mod => slotComplete(slots[mod.key])).length;
  const missing = CLARIFY_MODULES.filter(mod => !slotComplete(slots[mod.key]));
  const emptyText = missing
    .filter(mod => (slots[mod.key] || {}).mode === 'text')
    .map(mod => mod.label);
  const hint =
    done === 3
      ? '三项已选，正在继续…'
      : emptyText.length
        ? `请填写${emptyText.join('、')}描述后自动继续（已选 ${done}/3）`
        : `还差 ${3 - done} 项，选完自动继续（已选 ${done}/3）`;
  return `
    <div class="mt-3 flex gap-2.5">
      <div class="mt-0.5 h-7 w-7 shrink-0"></div>
      <div class="amber-ring min-w-0 flex-1 overflow-hidden rounded-[10px] border border-line2 bg-[#16171B]">
        <div class="flex items-center gap-2 border-b border-line/80 bg-raise/60 px-3.5 py-2">
          ${ic('message-circle-question', 'h-3.5 w-3.5 text-amber')}
          <span class="text-[12px] font-medium text-txt">还需要确认一下</span>
          <span class="flex items-center gap-1 rounded-full border border-amber/30 bg-amber/10 px-2 py-[2px] text-[9.5px] text-amber2">
            <span class="live-dot h-1 w-1 rounded-full bg-amber2"></span>等你回话
          </span>
          <span class="ml-auto text-[10px] text-dim">3 个模块 · 已选 ${done}/3</span>
        </div>
        ${CLARIFY_MODULES.map(mod => {
          const slot = slots[mod.key] || {};
          return `
          <div class="border-t border-line/60 px-3.5 py-3">
            <div class="flex items-center gap-2">
              ${ic(mod.icon, 'h-3.5 w-3.5 text-amber')}
              <span class="text-[12.5px] font-medium text-txt">${mod.label}</span>
              <span class="text-[9.5px] text-dim">${mod.hint}</span>
              <span class="ml-auto rounded-full border px-2 py-[1px] text-[9.5px] ${slotComplete(slot) ? 'border-ok/30 bg-ok/10 text-ok' : slot.mode ? 'border-amber/40 bg-amber/10 text-amber2' : 'border-line2 text-dim'}">${clarifyValue(slot)}</span>
            </div>
            <div class="mt-2 flex flex-wrap gap-1.5">
              ${CLARIFY_MODES.map(opt => `<button data-action="clarify-pick" data-slot="${mod.key}" data-mode="${opt.mode}" class="flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11.5px] transition ${slot.mode === opt.mode ? 'border-amber/55 bg-amber/12 text-amber2' : 'border-line2 bg-panel text-sub hover:border-amber/45 hover:text-txt'}">${ic(opt.icon, 'h-3 w-3')}${opt.label}</button>`).join('')}
            </div>
            ${slot.mode === 'text' ? `<div class="mt-2 flex items-center gap-1.5">
              <input data-clarify-input="${mod.key}" value="${esc(slot.text || '')}" placeholder="写一句${mod.label}描述，Enter 确认" class="min-w-0 flex-1 rounded-md border border-line2 bg-panel px-2 py-1.5 text-[11.5px] text-txt placeholder:text-dim focus:border-amber/45" />
              <button data-action="clarify-text-ok" data-slot="${mod.key}" class="rounded-md border border-line2 px-2.5 py-1.5 text-[11px] text-sub transition hover:text-txt">确定</button>
            </div>` : ''}
            ${slot.attachment ? `<div class="mt-2 flex items-center gap-1.5 text-[10px] text-dim">${ic('image', 'h-3 w-3')}${esc(slot.attachment.name)}</div>` : ''}
          </div>`;
        }).join('')}
        <div class="flex items-center justify-between border-t border-line/80 bg-panel/40 px-3.5 py-2.5">
          <span class="flex items-center gap-1.5 text-[10.5px] ${emptyText.length ? 'text-amber2' : 'text-dim'}">${ic('info', 'h-3 w-3')}${hint}</span>
          <button data-action="chat-focus" class="rounded-lg border border-line2 px-3 py-1.5 text-[12px] text-sub transition hover:bg-raise hover:text-txt">我再补充</button>
        </div>
      </div>
    </div>`;
}

export function fitChatInput() {
  const ta = document.getElementById('chatInput');
  if (!ta || !ta.offsetParent) return;
  ta.style.height = 'auto';
  const height = Math.min(ta.scrollHeight, 220);
  if (!height) return;
  ta.style.height = height + 'px';
  ta.style.overflowY = ta.scrollHeight > 220 ? 'auto' : 'hidden';
}

export function autoRunProgress() {
  const run = S.autoRun;
  if (!run || run.subId !== S.current.subId) return '';
  const shots = run.shots.map((s,i) => `<li>${i+1}. ${esc(s.name)} · ${esc(s.stage)}</li>`).join('');
  return `<div class="my-2 border-l border-amber pl-3 text-[11px] text-sub">
    <strong class="text-amber2">${esc(run.stage)}</strong>
    <ol>${shots}</ol>
    ${finalPlayer(run, true)}
  </div>`;
}

export function renderChat() {
  document.body.classList.toggle('agent-auto', S.autoMode);
  setTimeout(fitChatInput, 0);
  const proj = currentProject();
  const running = S.autoRun?.subId === S.current.subId && S.autoRun?.status === 'running';
  const turns = S.messages.filter(m => m.role === 'user').length;
  const cfg = S.settings.api?.llm || {};
  const base = (cfg.base_url || '').replace(/\/+$/, '').replace(/\/chat\/completions$/, '');
  const usage = S.messages.map(m => m.meta?.contextUsage).reverse().find(u => u?.model === cfg.model && u.base === base);
  const used = Number.isSafeInteger(usage?.input) && usage.input >= 0 ? usage.input : null;
  const limit = Number.isSafeInteger(usage?.limit) && usage.limit > 0 ? usage.limit : Number(cfg.context_limit) || null;
  const lastAgent = [...S.messages].reverse().find(m => m.role === 'agent');
  const showQuestions = lastAgent && lastAgent.meta && lastAgent.meta.questions && !lastAgent.meta.dismissed;
  if (showQuestions && !S.finalPending && (!S.clarify || S.clarify.msgId !== lastAgent.id)) {
    S.clarify = { msgId: lastAgent.id, slots: { role: {}, scene: {}, style: {} } };
  }

  const pending = S.chatPending ? `
    <div class="mt-3 flex gap-2.5">
      <div class="grad-amber mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px]">
        ${ic('sparkles', 'h-3.5 w-3.5 text-[#1B0E05]')}
      </div>
      <div class="mt-0.5 flex items-center gap-2 rounded-[10px] border border-line bg-card px-3 py-2 text-[12px] text-sub">
        ${ic('loader-circle', 'h-3.5 w-3.5 animate-spin text-amber')}正在理解并规划…
      </div>
    </div>` : '';

  const finalPending = S.finalPending ? `
    <div class="mt-3 flex gap-2.5">
      <div class="grad-amber mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px]">
        ${ic('sparkles', 'h-3.5 w-3.5 text-[#1B0E05]')}
      </div>
      <div class="mt-0.5 flex items-center gap-2 rounded-[10px] border border-line bg-card px-3 py-2 text-[12px] text-sub">
        ${ic('loader-circle', 'h-3.5 w-3.5 animate-spin text-amber')}已确认，生成中…
      </div>
    </div>` : '';

  const thread = (S.messages.length
    ? S.messages.map(m => chatMessageHtml(m) + (m === lastAgent && showQuestions ? chatQuestionCard(m) : '')).join('') + pending
    : `<div class="flex h-full flex-col items-center justify-center gap-2.5 text-center">
        <div class="grad-amber-soft flex h-11 w-11 items-center justify-center rounded-[10px] border border-amber/25">
          ${ic('sparkles', 'h-5 w-5 text-amber')}
        </div>
        <p class="text-[13.5px] font-medium text-txt">和主 Agent 聊聊，或者直接描述你想要的镜头</p>
        <p class="max-w-[420px] text-[11.5px] leading-relaxed text-dim">可以闲聊、提问，也可以让它规划分镜、生成设定图。说清楚场景、人物、时长和风格，锁定的设定会存进资产库。</p>
      </div>`) + finalPending;

  return `
  <div class="flex h-full min-h-0">
    <main class="flex min-w-0 flex-1 flex-col px-8 py-4">
      <div class="mx-auto flex h-full w-full max-w-[820px] flex-col">
        <div id="chatThread" class="hide-scroll min-h-0 flex-1 overflow-y-auto pr-1">
          <div class="flex items-center gap-2.5 py-1">
            <span class="h-px flex-1 bg-line/70"></span>
            <span class="text-[10.5px] text-dim">${esc(proj ? proj.name + ' · ' + (S.current.sub || '') : '还没有项目')}</span>
            <span class="h-px flex-1 bg-line/70"></span>
          </div>
          <div ${running ? 'inert' : ''}>${thread}</div>
          <div id="autoRunProgress" aria-live="polite">${autoRunProgress()}</div>
        </div>

        <div class="mt-3 shrink-0">
          ${S.autoMode ? `<div class="mb-1.5 flex items-center gap-1.5 rounded-md border border-amber/30 bg-amber/10 px-2.5 py-1.5 text-[10.5px] text-amber2">${ic('sparkles', 'h-3 w-3')}Agent 全自动已开启：先出角色/场景设定图，再生成视频</div>` : ''}
          <div class="flex items-stretch gap-2">
          <fieldset ${running ? 'disabled' : ''} class="min-w-0 flex-1 rounded-[10px] border border-line2 bg-card transition focus-within:border-amber/45 disabled:opacity-60">
            <div class="px-3.5 pt-2.5">
              <textarea id="chatInput" rows="3" placeholder="${S.autoMode ? '写一句视频描述，发送即直接生成……' : proj ? '继续描述，或者直接回答上面的问题……' : '先新建一个项目，再开始描述镜头……'}" class="max-h-[220px] w-full resize-none overflow-y-hidden bg-transparent text-[13.5px] leading-[1.6] text-txt placeholder:text-dim"></textarea>
            </div>
            <div class="flex items-center justify-between px-2 pb-2">
              <div class="flex items-center gap-1">
                <button data-action="upload-image" class="flex items-center gap-1.5 rounded-lg border border-line bg-raise px-2 py-1.5 text-[12px] text-sub transition hover:border-line2 hover:text-txt">${ic('image-plus', 'h-3.5 w-3.5')}图片</button>
                <button data-action="upload-file" class="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[12px] text-dim transition hover:text-txt">${ic('paperclip', 'h-3.5 w-3.5')}附件</button>
                <span id="chatAttach" class="ml-1 hidden items-center gap-1.5 rounded-lg border border-line2 bg-raise px-2 py-1 text-[10.5px] text-sub"></span>
              </div>
              <div class="flex items-center gap-2">
                <span class="flex items-center gap-1 rounded-md bg-panel px-2 py-1 text-[10.5px] text-sub">${ic('bot', 'h-3 w-3')}主 Agent · ${esc(((S.settings.api || {}).llm || {}).model || '未配置')}</span>
                <button data-action="chat-send" class="grad-amber flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-medium text-[#1B0E05]">${S.autoMode ? `${ic('film', 'h-3.5 w-3.5')}生成视频` : `${ic('arrow-up', 'h-3.5 w-3.5')}发送`}</button>
              </div>
            </div>
          </fieldset>
            <div class="flex shrink-0 items-center gap-2 text-[10px] text-sub" title="最近一次规划请求的输入 token / 当前模型上下文容量">
              <div class="text-right"><p>输入轮次</p><strong class="text-[13px] text-txt">${turns} 轮</strong><p class="mt-1">上下文 · token</p><span>${used?.toLocaleString() ?? '—'} / ${limit?.toLocaleString() ?? '未知'}</span></div>
              <div ${limit && used !== null ? `role="meter" aria-label="上下文占用" aria-valuemin="0" aria-valuemax="${limit}" aria-valuenow="${Math.min(used,limit)}"` : 'aria-hidden="true"'} class="flex h-16 w-1.5 items-end overflow-hidden rounded-full bg-line">
                <span class="w-full bg-amber" style="height:${limit && used !== null ? Math.min(100, 100 * used / limit) : 0}%"></span>
              </div>
            </div>
            <button data-view="video" class="flex w-[74px] shrink-0 flex-col items-center justify-center gap-1.5 rounded-[10px] border border-line bg-card text-[11px] text-sub transition hover:border-amber/40 hover:bg-raise hover:text-txt" title="打开视频界面">
              ${ic('film', 'h-4 w-4 text-amber')}
              <span>视频界面</span>
            </button>
          </div>
          <p class="mt-1.5 flex items-center gap-2 text-[11px] text-dim">
            ${ic('lightbulb', 'h-3 w-3')}${proj ? '描述越具体，镜头越接近你想的画面' : '新建项目后即可开始对话'}
            <span class="ml-auto flex items-center gap-1">Enter 发送 · Shift + Enter 换行</span>
          </p>
        </div>

        <div class="mt-3 grid shrink-0">
          <button data-action="auto-video" ${running ? 'disabled' : ''} aria-pressed="${Boolean(running || S.autoMode)}" class="group flex w-full items-center gap-3 rounded-[10px] border ${running || S.autoMode ? 'border-amber/55 bg-amber/10' : 'border-line bg-card'} px-3 py-2.5 text-left transition hover:border-amber/40 hover:bg-raise">
            <span class="flex h-8 w-8 items-center justify-center rounded-lg border ${S.autoMode ? 'border-amber/50 bg-amber/15' : 'border-amber/30 bg-amber/10'}">${ic('sparkles', 'h-4 w-4 text-amber')}</span>
            <span class="min-w-0 flex-1">
              <span class="block text-[12.5px] font-medium text-txt">${running ? 'Agent 全自动运行中' : 'Agent 全自动'}</span>
              <span class="mt-0.5 block text-[10.5px] text-sub">提交后由 Agent 全程执行，运行期间对话只读。</span>
            </span>
            ${S.autoMode ? `<span class="shrink-0 rounded-full border border-amber/40 bg-amber/15 px-1.5 py-[1px] text-[9px] text-amber2">ON</span>` : ic('chevron-right', 'h-3.5 w-3.5 text-dim transition group-hover:text-sub')}
          </button>
        </div>
      </div>
    </main>

    <aside class="flex w-[296px] shrink-0 flex-col border-l border-line bg-[#0E0F12]">
      <div class="flex h-11 items-center justify-between border-b border-line px-4">
        <span class="text-[11px] tracking-[0.12em] text-sub">本次项目</span>
        <div class="flex items-center gap-3">
          <button data-action="export-chat" class="flex items-center gap-1 text-[10.5px] text-dim transition hover:text-sub">${ic('download', 'h-3 w-3')}导出</button>
          <button data-action="switcher-open" class="flex items-center gap-1 text-[10.5px] text-dim transition hover:text-sub">${ic('repeat', 'h-3 w-3')}切换</button>
        </div>
      </div>
      ${proj ? `
      <div class="px-4 pt-3.5">
        <div class="flex items-start justify-between gap-2">
          <h3 class="min-w-0 truncate text-[13.5px] font-medium leading-snug">${esc(proj.name)} · ${esc(proj.kind)}</h3>
          <span class="flex shrink-0 items-center gap-1 rounded-full border border-amber/25 bg-amber/10 px-1.5 py-[2px] text-[9.5px] text-amber2">
            <span class="live-dot h-1 w-1 rounded-full bg-amber2"></span>${S.shots.length ? '进行中' : '待开始'}
          </span>
        </div>
        <p class="mt-1 text-[10.5px] text-dim">${esc(S.current.sub || '未分集')} · 创建于 ${esc((proj.createdAt || '').slice(0, 10))}</p>
        <div class="mt-3 grid grid-cols-2 gap-2">
          <div class="rounded-lg border border-line bg-card px-2.5 py-2">
            <p class="text-[10px] text-dim">镜头</p>
            <p class="mt-0.5 text-[15px] font-medium leading-none">${S.shots.length}<span class="ml-0.5 text-[10px] text-sub">个</span></p>
          </div>
          <div class="rounded-lg border border-line bg-card px-2.5 py-2">
            <p class="text-[10px] text-dim">已用时长</p>
            <p class="mt-0.5 text-[15px] font-medium leading-none">${totalDur().toFixed(1)}<span class="ml-0.5 text-[10px] text-sub">s</span></p>
          </div>
        </div>
        <div class="mt-2 rounded-lg border border-line bg-card px-2.5 py-2">
          <div class="flex items-center justify-between text-[10px]">
            <span class="text-dim">整片确认进度</span><span class="text-amber2">${S.shots.length ? Math.round(S.shots.filter(s => s.status === 'confirmed').length / S.shots.length * 100) : 0}%</span>
          </div>
          <div class="mt-1.5 h-1 overflow-hidden rounded-full bg-line"><div class="grad-amber h-full rounded-full" style="width:${S.shots.length ? Math.round(S.shots.filter(s => s.status === 'confirmed').length / S.shots.length * 100) : 0}%"></div></div>
          <p class="mt-1.5 text-[10px] text-dim">${S.shots.length ? '已确认 ' + S.shots.filter(s => s.status === 'confirmed').length + ' / ' + S.shots.length + ' 个镜头' : '还没有镜头'}</p>
        </div>
      </div>
      <div class="mt-4 flex items-center justify-between px-4">
        <span class="text-[11px] text-sub">最近镜头</span><span class="text-[10px] text-dim">共 ${S.shots.length}</span>
      </div>
      <div class="mt-2 flex flex-col gap-1.5 px-3">
        ${S.shots.length ? S.shots.slice(-3).reverse().map(s => `
          <button data-action="shot-select" data-id="${s.id}" class="flex items-center gap-2.5 rounded-lg px-1 py-1.5 text-left transition hover:bg-raise">
            <div class="relative h-9 w-[54px] shrink-0 overflow-hidden rounded-[4px]" style="background:linear-gradient(155deg,${s.tones[0] || '#2A323A'},#101418)">
              <svg class="absolute bottom-0 left-1/2 h-8 w-4 -translate-x-1/2 text-[#080A0C]"><use href="#fig-front"/></svg>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-[11.5px] text-txt">镜头 ${s.no} · ${esc(s.name)}</p>
              <p class="mt-0.5 text-[10px] text-dim">${fmtDur(s.dur)} · ${s.status === 'confirmed' ? '已确认' : '待确认'}</p>
            </div>
            ${s.status === 'confirmed' ? ic('check-circle-2', 'h-3.5 w-3.5 text-sub') : ic('circle-dashed', 'h-3.5 w-3.5 text-dim')}
          </button>`).join('') : emptyLine('还没有镜头，先在对话里描述一个')}
      </div>
      <div class="mt-auto border-t border-line px-4 py-3">
        <div class="rounded-lg border border-line bg-card p-2.5">
          <p class="flex items-center gap-1.5 text-[10.5px] text-sub">${ic('lock', 'h-3 w-3 text-amber/80')}${S.assets.filter(a => a.locked).length} 项设定已锁定</p>
          <p class="mt-1 text-[10px] leading-relaxed text-dim">锁定项在所有镜头里保持一致，是画面不跳的关键。</p>
        </div>
      </div>` : `
      <div class="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <p class="text-[11.5px] text-dim">还没有项目</p>
        <button data-action="project-new" class="grad-amber mt-1 rounded-lg px-3 py-1.5 text-[12px] font-medium text-[#1B0E05]">新建项目</button>
      </div>`}
    </aside>
  </div>`;
}
