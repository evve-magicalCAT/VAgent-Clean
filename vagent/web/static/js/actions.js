/* Vagent · 所有按钮行为（data-action 分发目标）

   这个文件同时服务三个人，规则：
   1. 只在自己的区间里追加 action，不要重排、不要格式化别人的区间；
   2. 新增 action 的命名必须是 <域>-<动词>，且与按钮上的 data-action 完全一致；
   3. 跨域复用请提函数到 core.js（A 负责），不要在 actions.js 里互相调用对方的新函数；
   4. 修改后必须跑 node tests/ui_smoke.mjs。
*/

import { $, $$, API, S, clamp, esc, ic, paint, timeLabel, toast, totalDur } from './core.js';
import { renderDrawer } from './drawer.js';
import { canReview } from './confirm.js';
import { assetModal, closeMigrate, closeModal, confirmModal, inputCls, labelCls, modalFoot, modalHead, openMigrate, openModal, projectModal, renderMigrate, subModal } from './ui.js';
import { previewEl, refreshAssetSelection, renderAssetDrawer } from './assets.js';
import { shotAtPlayhead, statusPill, videoConfigured } from './video.js';
import { analyzePrompt, fitChatInput, planMeta, scrollChatToBottom, autoRunProgress } from './chat.js';
import { closeSwitcher, mountView, openSwitcher, refresh, renderAllViews, switchView } from './shell.js';
/* ---------- 5 行为 ---------- */

/* ================= A · 项目与对话 helper ================= */
export function projectOfSub(sid) {
  return S.projects.find(p => (p.subs || []).some(s => s.id === sid)) || null;
}

/* ================= C · 撤销 / 重绘 / 文字剪辑 ================= */
export function pushUndo() {
  S.undo.push(JSON.parse(JSON.stringify(S.shots)));
  if (S.undo.length > 12) S.undo.shift();
}

export async function undoLast() {
  if (!S.undo.length) return toast('没有可撤销的操作', 'warn');
  const shots = S.undo.pop();
  try {
    await API.put('/api/shots/bulk', { shots });
    await refresh({ toast: '已撤销上一步' });
  } catch (err) {
    toast('撤销失败：' + err.message, 'warn');
  }
}

/* 本地模拟镜头重绘：进度条走完后置为已确认 */
export async function simulateRedraw(id, opts = {}) {
  const shot = S.shots.find(s => s.id === id);
  if (!shot) return;
  pushUndo();
  try {
    await API.patch('/api/shots/' + encodeURIComponent(id), { status: 'redraw', progress: 3 });
  } catch (err) {
    return toast('提交失败：' + err.message, 'warn');
  }
  await refresh();
  toast(opts.keysOnly ? '正在重做关键帧（本地模拟）' : '正在重做这个镜头（本地模拟）', 'info');
  let p = 3;
  const timer = setInterval(async () => {
    const cur = (S.shots.find(s => s.id === id) || {});
    if (cur.status !== 'redraw') { clearInterval(timer); return; }
    p = Math.min(100, p + 8 + Math.random() * 10);
    cur.progress = Math.round(p);
    const bar = $(`[data-status-pill="${id}"]`);
    if (bar) bar.innerHTML = statusPill('redraw', { progress: Math.round(p) });
    const block = $(`[data-action="shot-select"][data-id="${id}"]`);
    if (block) {
      const label = block.querySelector('.absolute span');
      if (label) label.textContent = `生成中 ${Math.round(p)}%`;
      const fill = block.querySelector('.absolute.bottom-0 .grad-amber, .absolute.inset-x-0.bottom-0 > div');
      if (fill) fill.style.width = Math.round(p) + '%';
    }
    if (p >= 100) {
      clearInterval(timer);
      try {
        await API.patch('/api/shots/' + encodeURIComponent(id), { status: 'confirmed', progress: 0 });
        await refresh({ toast: `镜头 ${shot.no} 重绘完成`, type: 'ok' });
      } catch (err) {
        toast('更新失败：' + err.message, 'warn');
      }
    }
  }, 320);
}

/* 视频生成：提交后按固定间隔查询，结果写回镜头 */
const shotPolls = new Map();

async function generateShotVideo(id) {
  const shot = S.shots.find(s => s.id === id);
  if (!shot) return;
  try {
    await API.post(`/api/shots/${encodeURIComponent(id)}/video`, {});
    await refresh({ view: S.view });
    toast('已提交视频生成任务，通常需要 1–5 分钟', 'info');
  } catch (err) {
    return toast('提交失败：' + err.message, 'warn');
  }
  pollShotVideo(id, shot.no);
}

/* 首帧确认：首帧模式下，视频必须先用这张图确认，再和提示词一起提交 */
function shotFrameModal(shot) {
  return `
    ${modalHead('image', '确认首帧', `镜头 ${shot.no} · ${shot.name}`)}
    <div class="px-4 py-3">
      <div class="relative aspect-video overflow-hidden rounded-md border border-line2 bg-[#0C0E11]">
        <div id="frameLoading" class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[10px] text-dim">
          ${ic('loader-circle', 'h-5 w-5 animate-spin text-amber')}正在生成首帧，约 10–30 秒
        </div>
        <img id="frameImg" class="hidden h-full w-full object-contain" alt="首帧预览" />
      </div>
      <p id="frameHint" class="mt-2 text-[11px] leading-relaxed text-sub">首帧会作为这个镜头的第一帧，和提示词一起提交给视频模型。</p>
      <button data-action="shot-frame-regen" data-id="${shot.id}" id="frameRegenBtn" disabled class="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-line2 py-1.5 text-[11px] text-sub transition hover:bg-raise hover:text-txt disabled:cursor-not-allowed disabled:opacity-50">
        ${ic('refresh-cw', 'h-3 w-3')}重新生成首帧
      </button>
    </div>
    <div class="flex items-center justify-end gap-2 border-t border-line bg-panel/60 px-4 py-3">
      <button data-action="modal-close" class="rounded-lg border border-line2 px-3 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">取消</button>
      <button data-action="shot-frame-confirm" data-id="${shot.id}" id="frameConfirmBtn" disabled class="grad-amber flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-medium text-[#1B0E05] disabled:cursor-not-allowed disabled:opacity-50">
        ${ic('check', 'h-3.5 w-3.5')}确认，用此首帧生成视频
      </button>
    </div>`;
}

async function loadShotFrame(id, force = false) {
  const img = $('#frameImg'), loading = $('#frameLoading'), hint = $('#frameHint');
  const regen = $('#frameRegenBtn'), confirm = $('#frameConfirmBtn');
  if (!img || !loading) return;
  loading.classList.remove('hidden');
  img.classList.add('hidden');
  if (regen) regen.disabled = true;
  if (confirm) confirm.disabled = true;
  hint.textContent = force ? '正在重新生成首帧，请稍候…' : '正在读取首帧…';
  try {
    let d = await API.get(`/api/shots/${encodeURIComponent(id)}/keyframe`);
    if (force || !d.exists) {
      d = await API.post(`/api/shots/${encodeURIComponent(id)}/keyframe`, force ? { force: true } : {});
    }
    if (!d.exists || !d.url) throw new Error('首帧没有生成成功');
    img.src = d.url + (d.url.includes('?') ? '&' : '?') + 'v=' + Date.now();
    img.classList.remove('hidden');
    loading.classList.add('hidden');
    hint.textContent = d.confirmed
      ? '这张首帧已确认；如果要改，可以重新生成后再确认。'
      : '确认前请先看画面：不满意就重新生成，确认后才会提交视频。';
    if (regen) regen.disabled = false;
    if (confirm) confirm.disabled = false;
  } catch (err) {
    loading.classList.add('hidden');
    hint.textContent = '首帧生成失败：' + err.message;
    if (regen) regen.disabled = false;
  }
}

function openShotFrameConfirm(id) {
  const shot = S.shots.find(s => s.id === id);
  if (!shot) return;
  openModal(shotFrameModal(shot), '560px');
  loadShotFrame(id, false);
}

/* 重抽这个镜头的首帧：坏首帧（手指贴脸、换脸）必须先换掉，否则视频会原样放大 */
async function regenShotKeyframe(id) {
  const shot = S.shots.find(s => s.id === id);
  if (!shot) return;
  const img = (S.settings.api || {}).img || {};
  if (!img.api_key) return toast('还没有配置图片模型 API Key，重抽只会得到占位图', 'warn');
  try {
    toast('正在重新生成首帧，约 10–30 秒', 'info');
    await API.post(`/api/shots/${encodeURIComponent(id)}/keyframe`, { force: true });
    await refresh({ view: S.view, toast: '首帧已重抽，确认没问题再生成视频' });
  } catch (err) {
    toast('首帧重抽失败：' + err.message, 'warn');
  }
}

function pollShotVideo(id, no) {
  clearInterval(shotPolls.get(id));
  let fails = 0;
  const timer = setInterval(async () => {
    try {
      const d = await API.get(`/api/shots/${encodeURIComponent(id)}/video`);
      fails = 0;
      if (d.state === 'succeeded') {
        clearInterval(timer); shotPolls.delete(id);
        const review = d.shot?.review;
        const labels = { pass: '合格', fail: '不合格', uncertain: '证据不足，未通过', error: '审核失败' };
        const message = review?.mode === 'auto' ? `镜头 ${no || ''} 自动审核：${labels[review.verdict]}` : (no ? `镜头 ${no} 的视频已生成` : '视频已生成');
        await refresh({ view: S.view, toast: message });
      } else if (d.state === 'failed' || d.state === 'cancelled') {
        clearInterval(timer); shotPolls.delete(id);
        await refresh({ view: S.view, toast: `视频生成${d.state === 'cancelled' ? '被取消' : '失败'}${d.error ? '：' + d.error : ''}`, type: 'warn' });
      } else if (d.shot) {
        const cur = S.shots.find(s => s.id === id);
        if (cur) cur.progress = d.shot.progress;
      }
    } catch (err) {
      /* 网络抖动或一时 5xx 不该让轮询永久停摆：连续失败 3 次才放弃 */
      fails += 1;
      if (fails >= 3) {
        clearInterval(timer); shotPolls.delete(id);
        toast('查询生成进度连续失败 3 次，已停止轮询：' + err.message, 'warn');
      }
    }
  }, 5000);
  shotPolls.set(id, timer);
}

function stopShotPoll(id) {
  clearInterval(shotPolls.get(id));
  shotPolls.delete(id);
}

/* 预览 = 播放头所在那一个镜头的完整视频（不换片源，才不会黑屏卡顿）。
   播放时播放头跟着视频真实时间走；拖标尺时视频跳到那一帧。 */
function previewVideo() {
  return document.getElementById('previewVideo');
}

function paintPlayhead(pct) {
  const total = totalDur();
  const ph = $('#playhead');
  if (ph) ph.style.left = pct + '%';
  const cur = total * pct / 100;
  const lbl = $('#playheadLabel');
  if (lbl) lbl.textContent = cur.toFixed(1);
  const pt = $('#previewTime');
  if (pt) pt.textContent = timeLabel(cur);
}

/* 视频素材可能比镜头时长短/长：按时间轴 dur 截断播放，播到 dur 就切下一镜 */
function advanceToNext(v) {
  S.video.playing = false;
  const i = S.shots.findIndex(s => s.id === v.dataset.shot);
  const next = S.shots[i + 1];
  const total = totalDur();
  if (!next) {
    S.video.playhead = 100;
    paintPlayhead(100);
    mountView('video');
    return;
  }
  const startNext = S.shots.slice(0, i + 1).reduce((a, s) => a + s.dur, 0);
  S.video.shotId = next.id;
  S.video.playhead = total ? (startNext / total) * 100 : 0;
  mountView('video');
  setTimeout(() => {
    const nv = previewVideo();
    if (nv) { nv.currentTime = 0; nv.play().catch(() => {}); }
  }, 60);
}

let lastHeadPct = -1;
setInterval(() => {
  const v = previewVideo();
  const at = shotAtPlayhead(S.video.playhead);
  if (!v || !at) return;
  if (v.dataset.bound !== '1') {
    v.dataset.bound = '1';
    v.addEventListener('ended', () => advanceToNext(v));
  }
  if (!v.paused) {
    const vShot = S.shots.find(s => s.id === v.dataset.shot);
    if (vShot && v.currentTime >= vShot.dur) {
      v.pause();
      advanceToNext(v);
      return;
    }
    const total = totalDur();
    if (!total) return;
    const idx = S.shots.findIndex(s => s.id === at.shot.id);
    const start = S.shots.slice(0, idx).reduce((a, s) => a + s.dur, 0);
    const pct = Math.min(100, ((start + Math.min(v.currentTime, at.shot.dur)) / total) * 100);
    S.video.playhead = pct;
    lastHeadPct = pct;
    paintPlayhead(pct);
    return;
  }
  if (Math.abs(S.video.playhead - lastHeadPct) > 0.2) {
    lastHeadPct = S.video.playhead;
    v.currentTime = at.offset;
    paintPlayhead(S.video.playhead);
  }
}, 120);

export async function downloadFile(url) {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* 文字剪辑：本地解析，不调用模型 */
export async function runTextEdit(text) {
  if (!S.shots.length) return toast('还没有镜头可以改', 'warn');
  const cmd = (text || '').trim();
  if (!cmd) return toast('先写一句指令', 'warn');
  pushUndo();

  let next = JSON.parse(JSON.stringify(S.shots));
  let msg = '';

  const target = cmd.match(/压缩到\s*(\d+(?:\.\d+)?)\s*秒/);
  const del = cmd.match(/删除(?:第)?\s*(\d+)\s*个?镜头/);
  const grade = cmd.match(/(冷调|暖调|黑白)/);

  if (target) {
    const want = Number(target[1]);
    const cur = next.reduce((a, s) => a + s.dur, 0);
    if (cur > 0) {
      const k = want / cur;
      next = next.map(s => ({ ...s, dur: Math.max(0.4, Math.round(s.dur * k * 10) / 10) }));
      msg = `已把总时长压缩到 ${want} 秒`;
    }
  } else if (del) {
    const idx = Number(del[1]) - 1;
    if (idx < 0 || idx >= next.length) return toast(`没有第 ${del[1]} 个镜头`, 'warn');
    next.splice(idx, 1);
    msg = `已删除第 ${del[1]} 个镜头`;
  } else if (grade) {
    const map = {
      '冷调': ['#2C343C', '#2A323A', '#252C34'],
      '暖调': ['#3A322C', '#332B26', '#2A241F'],
      '黑白': ['#333333', '#2A2A2A', '#202020']
    };
    next = next.map(s => ({ ...s, tones: map[grade[1]] }));
    msg = `已给全片换成${grade[1]}`;
  } else if (/字幕/.test(cmd)) {
    S.undo.pop();
    await downloadFile('/api/export/subtitles.srt');
    return toast('已按当前镜头生成字幕文件', 'ok');
  } else {
    S.undo.pop();
    return toast('暂不支持这条指令，试试「压缩到 10 秒」「删除第 3 个镜头」「给全片加冷调」', 'warn');
  }

  try {
    await API.put('/api/shots/bulk', { shots: next });
    S.lastEdit = `${cmd} · ${msg}`;
    await refresh({ toast: msg });
  } catch (err) {
    toast('执行失败：' + err.message, 'warn');
  }
}

/* ================= A · 对话发送与继续生成 ================= */
export let chatAttachment = null;

export function analyzeSlotsToPrompt(meta) {
  const get = k => (meta.slots.find(s => s.kind === k) || {}).value || '';
  const role = get('role'), scene = get('scene'), style = get('style');
  const dur = (meta.slots.find(s => s.kind === 'dur') || {}).value || '4s';
  const parts = [];
  if (scene && scene !== '待补充') parts.push(scene);
  if (role && role !== '待补充' && role !== '让 AI 决定') parts.push(role);
  if (style && style !== '待补充') parts.push(style + '风格');
  return { prompt: parts.join('，') || '待补充镜头描述', dur: parseFloat(dur) || 4 };
}

function localReply(meta) {
  const locked = meta.slots.filter(s => s.locked).map(s => `${s.label}「${s.value}」`);
  return `我理解这是一镜的画面。${locked.length ? '这些按不可修改的设定处理：' + locked.join('、') + '。' : ''}${meta.questions.length ? '还有 ' + meta.questions.length + ' 处需要你确认，确认后我就能开始生成。' : '信息够了，可以直接继续生成。'}`;
}

export async function sendChat() {
  if (S.autoRun?.subId === S.current.subId && S.autoRun?.status === 'running') return;
  const ta = $('#chatInput');
  const text = (ta && ta.value || '').trim();
  if (!S.current.projectId) return toast('请先新建一个项目', 'warn');
  if (!text && !chatAttachment) return toast('先写点什么，或者附加一张参考图', 'warn');
  if (S.chatPending) return toast('上一条还在处理，稍等一下', 'info');
  if (S.autoMode) return submitAutoVideo();

  const fallbackText = text;
  const confirmKind = S.confirmKind || '';
  S.confirmKind = '';
  let assetUpdates = [];
  const payload = {
    role: 'user',
    text: text || `（发送了一个${chatAttachment.kind}：${chatAttachment.name}）`,
    meta: chatAttachment ? { attachment: chatAttachment } : {}
  };
  /* 先本地插入并立刻渲染，等后端返回消息列表后再对齐；避免模型思考期间看不到自己发的话 */
  S.messages = [...S.messages, {
    id: 'local-' + Date.now(), role: 'user', text: payload.text, meta: payload.meta, createdAt: ''
  }];
  S.chatPending = true;
  if (ta) ta.value = '';
  mountView('chat');
  scrollChatToBottom();

  try {
    const posted = await API.post('/api/messages', payload);
    if (posted && Array.isArray(posted.messages)) S.messages = posted.messages;
    mountView('chat');
    scrollChatToBottom();

    const cfg = (S.settings.api || {}).llm || {};
    let meta = null;
    let reply = '';
    if (cfg.api_key) {
      try {
        const d = await API.post('/api/llm/plan', {
          text: text || '根据这张参考图生成一个镜头',
          attachment: chatAttachment || null,
          confirm_kind: confirmKind,
          auto: !!S.autoMode
        });
        meta = planMeta(d.plan);
        if (d.contextUsage) meta.contextUsage = d.contextUsage;
        if (Array.isArray(d.images) && d.images.length) meta.images = d.images;
        if (Array.isArray(d.assetUpdates)) assetUpdates = d.assetUpdates;
        if (assetUpdates.length) meta.assetUpdates = assetUpdates;
        if (Array.isArray(d.assetProposals) && d.assetProposals.length) meta.assetProposals = d.assetProposals;
        if (Array.isArray(d.videos) && d.videos.length) {
          toast(`已提交 ${d.videos.length} 个视频任务，去「视频」页查看进度`, 'ok');
        }
        reply = d.reply || d.plan.summary || (d.plan.shots.length
          ? `我拆成了 ${d.plan.shots.length} 个镜头，确认后就能生成。`
          : '信息还不够，先回答下面几个问题。');
      } catch (err) {
        toast('语言模型不可用：' + err.message + '，已退回本地理解', 'warn');
      }
    }
    if (!meta) {
      meta = analyzePrompt(text);
      reply = localReply(meta);
    }
    await API.post('/api/messages', { role: 'agent', text: reply, meta: { ...meta, dismissed: false } });
    chatAttachment = null;
    S.chatPending = false;
    await refresh({ view: 'chat' });
    if (assetUpdates.length) {
      mountView('assets');
      toast('设定图已更新，预览已显示在对话里', 'ok');
    }
    scrollChatToBottom();
  } catch (err) {
    S.chatPending = false;
    if (ta && !ta.value) ta.value = fallbackText;
    await refresh({ view: 'chat' }).catch(() => {});
    toast('发送失败：' + err.message, 'warn');
  }
}

let generatingImages = false;

async function generatePlanImages(msgId) {
  const msg = S.messages.find(m => String(m.id) === String(msgId));
  const plan = msg && msg.meta && msg.meta.plan;
  const assets = (plan && plan.assets) || [];
  if (!assets.length) return toast('这条消息里没有可生成的资产', 'warn');
  if (!S.current.projectId) return toast('请先新建一个项目', 'warn');
  if (!((S.settings.api || {}).img || {}).api_key) return toast('还没有配置图片模型 API Key', 'warn');
  if (generatingImages) return toast('正在生成，等这一批完成再试', 'info');
  generatingImages = true;
  const done = [];
  const targets = [];
  try {
    /* 先把所有资产建出来并标成生成中，资产库立即可见 */
    for (const a of assets) {
      try {
        let asset = S.assets.find(x => x.name === a.name);
        if (!asset) {
          const d = await API.post('/api/assets', { name: a.name, type: a.type, desc: a.desc, locked: !!a.locked });
          asset = d.asset;
          if (asset) S.assets = [asset, ...S.assets];
        }
        if (!asset) continue;
        asset.ai = 'generating';
        asset.progress = 5;
        targets.push({ meta: a, asset });
      } catch (err) {
        toast(`「${a.name}」创建失败：${err.message}`, 'warn');
      }
    }
    if (!targets.length) return;
    /* 隐藏的资产库视图也先刷新，点过去就能看到生成中 */
    mountView('assets');
    if (S.view !== 'assets') mountView(S.view);
    toast(`已创建 ${targets.length} 项资产，正在生成中`, 'info');

    for (const target of targets) {
      const a = target.meta;
      try {
        const g = await API.post(`/api/assets/${encodeURIComponent(target.asset.id)}/preview`, {});
        target.asset.ai = 'none';
        done.push({ name: a.name, url: (g.image || {}).url || '' });
        toast(`已生成 ${done.length}/${targets.length}：${a.name}`, 'info');
        if (S.view === 'assets') mountView('assets');
      } catch (err) {
        target.asset.ai = 'none';
        toast(`「${a.name}」生成失败：${err.message}`, 'warn');
        if (S.view === 'assets') mountView('assets');
      }
    }
    if (done.length) {
      await API.post('/api/messages', {
        role: 'agent',
        text: `已生成 ${done.length} 张资产设定图，可以在「资产库」里继续微调。`,
        meta: { images: done }
      });
      await refresh({ view: S.view, toast: `已生成 ${done.length} 张设定图` });
      if (S.view === 'chat') scrollChatToBottom();
    } else {
      await refresh({ view: S.view });
    }
    if (S.view !== 'assets') mountView('assets');
  } finally {
    generatingImages = false;
  }
}

let continuing = false;

const CLARIFY_LABELS = { role: '角色', scene: '场景', style: '风格' };

function clarifyDraft() {
  return S.clarify && S.clarify.slots ? S.clarify : null;
}

function clarifyReady(draft) {
  return ['role', 'scene', 'style'].every(key => {
    const slot = draft.slots[key];
    if (!slot || !slot.mode) return false;
    if (slot.mode === 'text' && !(slot.text || '').trim()) return false;
    if (slot.mode === 'image' && !slot.attachment) return false;
    return true;
  });
}

/* 资产库变动时回一条带预览的 Agent 消息 */
async function notifyAsset(asset) {
  if (!asset || !asset.id) return;
  const preview = (asset.preview || []).map(item => item && item.url).filter(Boolean).slice(0, 3);
  await API.post('/api/messages', {
    role: 'agent',
    text: `资产库已更新：${asset.name}（${asset.type}）`,
    meta: {
      assetCard: {
        id: asset.id,
        name: asset.name,
        type: asset.type,
        desc: asset.desc || '',
        preview
      }
    }
  });
}

/* 轮询最终资产生成状态；完成后把带预览的资产回成消息 */
async function pollFinalAssets(ids) {
  if (!ids || !ids.length) return;
  const started = Date.now();
  const timer = setInterval(async () => {
    try {
      const data = await API.get('/api/assets?scope=' + encodeURIComponent(S.assetScope));
      if (data && Array.isArray(data.assets)) S.assets = data.assets;
      const pending = S.assets.filter(asset => ids.includes(asset.id) && asset.ai === 'generating');
      if (S.view === 'assets') mountView('assets');
      if (!pending.length) {
        clearInterval(timer);
        const ready = S.assets.filter(asset => ids.includes(asset.id) && (asset.preview || []).length);
        for (const asset of ready) {
          try {
            await notifyAsset(asset);
          } catch (err) {
            /* 单条消息失败不阻塞 */
          }
        }
        if (ready.length) {
          await refresh({
            view: S.view,
            toast:
              ready.length === ids.length
                ? `相关资产已生成（${ready.length} 项）`
                : `部分资产已生成（${ready.length}/${ids.length}）`
          });
        } else {
          await refresh({ view: S.view });
          toast('资产生成失败，请稍后重试', 'warn');
        }
        return;
      }
    } catch (err) {
      /* 继续轮询 */
    }
    if (Date.now() - started > 240000) clearInterval(timer);
  }, 2500);
}

/* 用户补充的文字/图片先落成资产，再让 Agent 补全自动项 */
async function saveClarifyAssets(draft) {
  const types = { role: '角色', scene: '场景', style: '风格' };
  const saved = [];
  const initialUser = [...S.messages].reverse().find(m => m.role === 'user' && m.meta && m.meta.attachment);
  const initialAttachment = initialUser && initialUser.meta.attachment;
  for (const key of ['role', 'scene', 'style']) {
    const slot = draft.slots[key];
    if (!slot) continue;
    try {
      const image =
        slot.mode === 'image' && slot.attachment && slot.attachment.url && slot.attachment.kind === '图片'
          ? slot.attachment
          : key === 'role' && initialAttachment && initialAttachment.url && initialAttachment.kind === '图片'
            ? initialAttachment
            : null;
      if (image) {
        const existing = S.assets.find(asset => asset.refImage === image.url);
        if (existing) {
          saved.push(existing.name);
          continue;
        }
        const d = await API.post('/api/assets/from-image', {
          url: image.url,
          name: `${types[key]}·参考图`,
          type: types[key],
          desc: (slot.text || '').trim() || '用户上传的参考图'
        });
        if (d && d.asset) {
          saved.push(d.asset.name);
          if (d.created !== false) {
            try { await notifyAsset(d.asset); } catch (err) { /* 通知失败不阻塞 */ }
          }
        }
      } else if (slot.mode === 'text' && (slot.text || '').trim()) {
        const text = slot.text.trim();
        const d = await API.post('/api/assets', {
          name: `${types[key]}·${text.slice(0, 8)}`,
          type: types[key],
          desc: text,
          locked: false
        });
        if (d && d.asset) {
          saved.push(d.asset.name);
          try { await notifyAsset(d.asset); } catch (err) { /* 通知失败不阻塞 */ }
        }
      }
    } catch (err) {
      /* 单个转存失败不阻塞继续 */
    }
  }
  return saved;
}

/* 三个模块都选完：视频先合并最终提示词并让用户确认；其他情况沿用原来的继续逻辑 */
async function finishClarifyIfReady() {
  const draft = clarifyDraft();
  if (!draft || !clarifyReady(draft) || S.chatPending) return false;
  /* 先立刻收起追问卡并显示“生成中”，再去合并最终提示词 */
  const restore = { msgId: draft.msgId, slots: JSON.parse(JSON.stringify(draft.slots)) };
  S.finalPending = true;
  S.clarify = null;
  mountView('chat');
  try {
  const saved = await saveClarifyAssets(draft);
  const lastUser = [...S.messages].reverse().find(m => m.role === 'user' && (m.text || '').trim());
  const original = lastUser ? lastUser.text.trim().slice(0, 200) : '';
  const attachment =
    draft.slots.role.attachment ||
    draft.slots.scene.attachment ||
    draft.slots.style.attachment ||
    (lastUser && lastUser.meta && lastUser.meta.attachment) ||
    null;

  let isVideo = /视频|短片|影片|成片|动起来/.test(original);
  try {
    const intent = await API.post('/api/intent', { text: original });
    if (intent && typeof intent.video === 'boolean') isVideo = intent.video;
  } catch (err) {
    /* 判断失败时用关键词兜底 */
  }

  if (isVideo) {
    const modules = {};
    for (const key of ['role', 'scene', 'style']) {
      const slot = draft.slots[key];
      modules[key] = { mode: slot.mode, text: slot.text || '' };
    }
    try {
      const forceExpand = ['role', 'scene', 'style'].some(key => (modules[key] || {}).mode === 'auto');
      const d = await API.post('/api/video/final-prompt', {
        text: original,
        modules,
        assets: saved,
        attachment,
        force_expand: forceExpand
      });
      await API.post('/api/messages', {
        role: 'agent',
        text: '最终提示词已合并，请确认后去视频界面生成。',
        meta: {
          finalPrompt: {
            shotId: d.shot.id,
            prompt: d.prompt,
            dur: d.dur,
            assets: saved,
              assetDetails: d.assetDetails || [],
            modules,
            ref: attachment ? attachment.url : '',
            shots: (d.shots || [d.shot]).map(shot => ({
              id: shot.id,
              no: shot.no,
              prompt: shot.prompt,
              dur: shot.dur
            }))
          }
        }
      });
      S.finalPending = false;
      await refresh({ view: 'chat' });
    } catch (err) {
      S.finalPending = false;
      toast('合并最终提示词失败：' + err.message, 'warn');
    }
    return true;
  }

  S.finalPending = false;
  const last = [...S.messages].reverse().find(m => m.role === 'agent' && m.meta && (m.meta.plan || m.meta.slots));
  const hasPlan = !!(
    last &&
    last.meta.plan &&
    ((last.meta.plan.shots || []).length || (last.meta.plan.assets || []).length)
  );
  const cfg = (S.settings.api || {}).llm || {};
  if (!cfg.api_key) {
    /* 本地理解模式：把三项选择并回槽位，再走原来的建镜头逻辑 */
    const rows = (last && last.meta && last.meta.slots) || [];
    ['role', 'scene', 'style'].forEach(key => {
      const pick = draft.slots[key];
      const row = rows.find(item => item.kind === key);
      if (!row || !pick) return;
      if (pick.mode === 'text') row.value = pick.text.trim();
      else if (pick.mode === 'image') row.value = '参考图已上传';
    });
    await chatContinue();
    return true;
  }
  if (hasPlan) {
    await chatContinue();
    return true;
  }
  const parts = ['role', 'scene', 'style'].map(key => {
    const slot = draft.slots[key];
    const value =
      slot.mode === 'image' ? '已上传参考图' : slot.mode === 'auto' ? '由你自动补全' : slot.text.trim();
    return `${CLARIFY_LABELS[key]}：${value}`;
  });
  const autoLabels = ['role', 'scene', 'style']
    .filter(key => draft.slots[key].mode === 'auto')
    .map(key => CLARIFY_LABELS[key]);
  const savedNote = saved.length ? `已转存资产：${saved.join('、')}。` : '';
  const autoNote = autoLabels.length
    ? `${autoLabels.join('、')}由你结合资产与上文自动补全并返回生成结果。`
    : '';
  const text = `${original ? `原需求：${original}。` : ''}${savedNote}${parts.join('；')}。${autoNote}三项已确认，请直接继续，不要再追问。`;
  chatAttachment = attachment;
  const ta = $('#chatInput');
  if (ta) ta.value = text;
  fitChatInput();
  await sendChat();
  return true;
  } catch (err) {
    S.finalPending = false;
    S.clarify = restore;
    mountView('chat');
    toast('处理失败：' + err.message, 'warn');
    return true;
  }
}

export async function chatContinue() {
  if (continuing) return;
  continuing = true;
  try {
    await continueChat();
  } catch (err) {
    toast('生成失败：' + err.message, 'warn');
  } finally {
    continuing = false;
  }
}

async function continueChat() {
  const last = [...S.messages].reverse().find(m => m.role === 'agent' && m.meta && (m.meta.plan || m.meta.slots));
  if (!last) return toast('还没有可生成的理解结果', 'warn');
  const plan = last.meta.plan;
  if (plan && ((plan.shots || []).length || (plan.assets || []).length)) {
    let shots = 0;
    for (const s of plan.shots || []) {
      await API.post('/api/shots', { name: s.name, dur: s.dur, prompt: s.prompt });
      shots += 1;
    }
    const drafts = [];
    for (const a of plan.assets || []) {
      if (S.assets.some(x => x.name === a.name)) continue;
      /* 草稿必须可编辑：锁定资产的描述改动不会保存，用户就没法确认/修改了 */
      const created = await API.post('/api/assets', { name: a.name, type: a.type, desc: a.desc, locked: false });
      if (created && created.asset) drafts.push(created.asset.id);
    }
    if (drafts.length) {
      S.pendingAssets = drafts;
      S.editingAsset = drafts[0];
      await API.post('/api/messages', {
        role: 'agent',
        text: `已创建 ${drafts.length} 项资产草稿${shots ? `和 ${shots} 个镜头` : ''}，请在资产库确认描述后再生成设定图。`,
        meta: {}
      });
      await refresh({ view: 'assets', toast: '请先检查资产描述，确认后生成设定图' });
      return;
    }
    await API.post('/api/messages', { role: 'agent', text: `已创建 ${shots} 个镜头。`, meta: {} });
    await refresh({ view: 'video', toast: `已创建 ${shots} 个镜头` });
    return;
  }
  const { prompt, dur } = analyzeSlotsToPrompt(last.meta);
  await API.post('/api/shots', { name: prompt.slice(0, 10), dur, prompt });
  await API.post('/api/messages', { role: 'agent', text: `已按上面的理解创建了一个 ${dur}s 的镜头，可以在「视频」里继续调整。`, meta: {} });
  await refresh({ view: 'video', toast: '已创建镜头，去「视频」里继续' });
}

export async function saveApiSettings() {
  const out = {};
  $$('[data-api-group]').forEach(sec => {
    const g = {};
    sec.querySelectorAll('[data-cfg]').forEach(el => {
      const key = el.dataset.cfg;
      const val = (el.value || '').trim();
      if (!key) return;
      if (key === 'context_limit') { g[key] = val; return; }
      if (key === 'api_key') {
        if (val && val.indexOf('•') === -1) g.api_key = val;
        return;
      }
      if (key === 'concurrency') { g.concurrency = Number(val) || 3; return; }
      if (val) g[key] = val;
    });
    out[sec.dataset.apiGroup] = g;
  });
  try {
    const d = await API.put('/api/settings/api', { api: out });
    if (d && d.api) S.settings.api = d.api;
    S.savedAt = new Date().toISOString().slice(0, 19).replace('T', ' ');
    renderDrawer();
    const saved = $('#drawerSavedAt');
    if (saved) saved.textContent = `上次保存 ${S.savedAt.slice(5, 16)}`;
    toast('设置已保存到本地数据库', 'ok');
  } catch (err) {
    toast('保存失败：' + err.message, 'warn');
  }
}

/* 上传：图片 / 附件 / 素材 */
/* ================= 共享 · 上传（图片 / 附件 / 素材） ================= */
export function pickFile(accept, cb) {
  const input = document.createElement('input');
  input.type = 'file';
  if (accept) input.accept = accept;
  input.onchange = () => { if (input.files && input.files[0]) cb(input.files[0]); };
  input.click();
}

export async function uploadToServer(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/upload', { method: 'POST', body: fd });
  const json = await res.json().catch(() => null);
  if (!json || !json.ok) throw new Error((json && json.error && json.error.message) || '上传失败');
  return json.data;
}

/* ---------- 5.1 动作表 ---------- */
async function submitAutoVideo() {
  const ta = $('#chatInput');
  const text = ((ta && ta.value) || '').trim();
  if (!text && !chatAttachment) return toast('请输入想法或上传素材', 'warn');
  try {
    S.chatPending = true;
    const subId = S.current.subId;
    const d = await API.post('/api/auto/runs', { text, attachment: chatAttachment });
    if (S.current.subId !== subId) return;
    S.autoRun = d.run;
    if (ta) ta.value = '';
    chatAttachment = null;
    renderChatAttachment();
    await refresh({ view: 'chat' });
  } catch (err) {
    toast('提交失败：' + err.message, 'warn');
  } finally {
    S.chatPending = false;
  }
}

let checkingRun = false;
setInterval(async () => {
  if (checkingRun || !S.ready || !['chat', 'confirm'].includes(S.view) || !S.current.subId) return;
  const sub = S.current.subId;
  checkingRun = true;
  try {
    const { run } = await API.get('/api/auto/runs/current');
    if (S.current.subId !== sub || !['chat', 'confirm'].includes(S.view)) return;
    const previous = S.autoRun;
    S.autoRun = run;
    if (previous?.id === run?.id && previous?.status === run?.status && run?.status !== 'running') return;
    if (S.view === 'chat' && run?.status === 'running' && (previous?.id !== run.id || previous.status !== 'running')) mountView('chat');
    const el = $('#autoRunProgress');
    if (el) el.innerHTML = autoRunProgress();
    if ((run && previous?.id === run.id && previous.status === 'running' && run.status !== 'running') ||
        (S.view === 'confirm' && previous?.id !== run?.id)) {
      await refresh({ view: S.view });
    }
  } catch { /* 下轮重新读取后台状态 */ }
  finally { checkingRun = false; }
}, 2500);

export const ACTIONS = {
  /* 项目管理 */
  /* ================= A · 项目管理 / 子项目 ================= */
  'project-new': () => projectModal(null),
  'project-rename': (id) => projectModal(S.projects.find(p => p.id === id)),
  'project-save': async (id) => {
    const name = ($('#mName').value || '').trim();
    const current = id ? S.projects.find(p => p.id === id) : null;
    const kind = current ? current.kind : '概念片';
    const desc = ($('#mDesc').value || '').trim();
    if (!name) return toast('项目名不能为空', 'warn');
    try {
      if (id) {
        await API.patch('/api/projects/' + encodeURIComponent(id), { name, kind, desc });
        closeModal();
        await refresh({ toast: '项目已更新' });
      } else {
        const d = await API.post('/api/projects', { name, kind, desc });
        closeModal();
        await refresh({ view: 'manage', toast: `项目「${name}」已创建` });
      }
    } catch (err) { toast('保存失败：' + err.message, 'warn'); }
  },
  'project-archive': async (id) => {
    const p = S.projects.find(x => x.id === id);
    if (!p) return;
    try {
      await API.patch('/api/projects/' + encodeURIComponent(id), { archived: !p.archived });
      await refresh({ toast: p.archived ? '项目已恢复' : '项目已归档' });
    } catch (err) { toast('操作失败：' + err.message, 'warn'); }
  },
  'project-delete': (id) => {
    const p = S.projects.find(x => x.id === id);
    if (!p) return;
    confirmModal({ title: '删除项目', desc: `确定删除「${p.name}」？项目下的子项目、镜头、资产都会一起删除。`, label: '删除项目', action: 'project-delete-confirm', id });
  },
  'project-delete-confirm': async (id) => {
    try {
      await API.del('/api/projects/' + encodeURIComponent(id));
      closeModal();
      await refresh({ view: 'manage', toast: '项目已删除' });
    } catch (err) { toast('删除失败：' + err.message, 'warn'); }
  },
  'open-project': async (id) => {
    try {
      await API.post('/api/switch', { projectId: id });
      await refresh({ view: 'manage', toast: '已打开项目' });
    } catch (err) { toast('打开失败：' + err.message, 'warn'); }
  },
  'select-project': async (id) => {
    try {
      await API.post('/api/switch', { projectId: id });
      await refresh({ view: 'manage' });
    } catch (err) { toast('切换失败：' + err.message, 'warn'); }
  },
  'switch-project': async (id) => {
    closeSwitcher();
    try {
      await API.post('/api/switch', { projectId: id });
      await refresh({ view: 'manage', toast: '已切换项目' });
    } catch (err) { toast('切换失败：' + err.message, 'warn'); }
  },
  'switcher-open': () => openSwitcher(),
  'select-sub': async (id) => {
    const p = projectOfSub(id);
    try {
      await API.post('/api/switch', { projectId: p ? p.id : S.current.projectId, subId: id });
      await refresh({ view: 'manage' });
    } catch (err) { toast('切换失败：' + err.message, 'warn'); }
  },
  'sub-new': () => {
    if (!S.current.projectId) return toast('先新建一个项目', 'warn');
    subModal();
  },
  'sub-save': async () => {
    const name = ($('#mSubName').value || '').trim();
    if (!name) return toast('子项目名不能为空', 'warn');
    try {
      await API.post(`/api/projects/${encodeURIComponent(S.current.projectId)}/subs`, { name });
      closeModal();
      await refresh({ view: 'manage', toast: '子项目已创建' });
    } catch (err) { toast('创建失败：' + err.message, 'warn'); }
  },
  'projects-all': () => { switchView('manage'); toast(`共 ${S.projects.length} 个项目（含已归档）`, 'info'); },

  /* 对话 */
  /* ================= A · 对话 ================= */
  'chat-send': () => sendChat(),
  'chat-focus': () => { const ta = $('#chatInput'); if (ta) ta.focus(); },
  'confirm-modify': (id, el) => {
    if (S.chatPending) return toast('上一条还在处理，稍等一下', 'info');
    const kind = (el && el.dataset.kind) || 'asset';
    S.confirmKind = kind;
    const ta = $('#chatInput');
    if (ta) {
      ta.value = kind === 'asset' ? '确认修改资产描述' : '确认修改镜头描述';
      fitChatInput();
    }
    sendChat();
  },
  'video-verify': async () => {
    const shot = S.shots.find(s => s.id === S.video.shotId) || S.shots[0] || null;
    if (!shot) return toast('还没有镜头，先建一个镜头再校验', 'warn');
    if (!shot.clipPath) return toast('这个镜头还没有生成视频，先出片再校验', 'warn');
    S.video.verify = { loading: true, shotId: shot.id };
    await refresh({ view: 'video' });
    try {
      const d = await API.post(`/api/shots/${encodeURIComponent(shot.id)}/verify`, {});
      S.video.verify = {
        loading: false,
        shotId: shot.id,
        pass: !!d.pass,
        issues: d.issues || [],
        frames: d.frames || [],
      };
      await refresh({ view: 'video', toast: d.pass ? '校验通过：和设定图是同一个人' : '校验不通过，见下方问题清单', type: d.pass ? 'ok' : 'warn' });
    } catch (err) {
      S.video.verify = { loading: false, shotId: shot.id, error: err.message };
      await refresh({ view: 'video', toast: err.message, type: 'warn' });
    }
  },
  'final-confirm': async (id) => {
    S.video.shotId = id;
    await refresh({ view: 'video' });
    switchView('video');
    toast('已到视频界面，点「生成视频」开始生成', 'info');
  },
  'final-assets': (id) => {
    const msg = S.messages.find(m => String(m.id) === String(id));
    const fp = msg && msg.meta && msg.meta.finalPrompt;
    if (!fp) return toast('找不到最终提示词', 'warn');
    confirmModal({
      title: '生成相关资产',
      desc: '将调用图片模型生成角色三视图 + 场景概念图，共 2 张，按张计费，约 1–2 分钟。',
      label: '开始生成',
      action: 'final-assets-confirm',
      id,
      danger: false
    });
  },
  'final-assets-confirm': async (id) => {
    closeModal();
    const msg = S.messages.find(m => String(m.id) === String(id));
    const fp = msg && msg.meta && msg.meta.finalPrompt;
    if (!fp) return;
    try {
      const d = await API.post('/api/video/final-assets', {
        prompt: fp.prompt,
        modules: fp.modules || {},
        assets: fp.assets || [],
        ref: fp.ref || ''
      });
      const assets = d.assets || [];
      if (!assets.length) throw new Error('没有创建资产');
      await API.post('/api/messages', {
        role: 'agent',
        text: `已创建 ${assets.length} 项资产，正在生成图片…`,
        meta: {}
      });
      await refresh({ view: 'chat', toast: '资产已创建，正在生成中，可去资产库查看' });
      pollFinalAssets(assets.map(asset => asset.id));
    } catch (err) {
      toast('创建资产失败：' + err.message, 'warn');
    }
  },
  'auto-video': () => {
    S.autoMode = !S.autoMode;
    sessionStorage.setItem('vagent.autoMode', S.autoMode ? 'on' : 'off');
    document.body.classList.toggle('agent-auto', S.autoMode);
    mountView('chat');
    toast(
      S.autoMode ? 'Agent 全自动已开启：先出设定图，再生成视频' : '已关闭 Agent 全自动',
      S.autoMode ? 'ok' : 'info'
    );
  },
  'chat-continue': chatContinue,
  'clarify-pick': async (id, el) => {
    const draft = clarifyDraft();
    if (!draft || !el) return;
    const slot = el.dataset.slot;
    const mode = el.dataset.mode;
    const cur = draft.slots[slot] || {};
    if (mode === 'image') {
      pickFile('image/*', async file => {
        try {
          const attachment = await uploadToServer(file);
          draft.slots[slot] = { mode: 'image', attachment };
          if (await finishClarifyIfReady()) return;
          mountView('chat');
        } catch (err) {
          toast(err.message, 'warn');
        }
      });
      return;
    }
    draft.slots[slot] = mode === 'auto' ? { mode: 'auto' } : { mode: 'text', text: cur.text || '' };
    if (await finishClarifyIfReady()) return;
    mountView('chat');
    if (mode === 'text') {
      const input = document.querySelector(`[data-clarify-input="${slot}"]`);
      if (input) input.focus();
    }
  },
  'clarify-text-ok': async (arg, el) => {
    const slot = (el && el.dataset.slot) || arg;
    const draft = clarifyDraft();
    if (!draft || !slot) return;
    const input = document.querySelector(`[data-clarify-input="${slot}"]`);
    const typed = ((input && input.value) || '').trim();
    const existing = ((draft.slots[slot] || {}).text || '').trim();
    const text = typed || existing;
    if (!text) return toast('先写一句描述', 'warn');
    draft.slots[slot] = { mode: 'text', text };
    if (await finishClarifyIfReady()) return;
    mountView('chat');
  },
  'export-chat': () => {
    toast('正在导出对话记录', 'info');
    downloadFile('/api/export/chat.md');
  },
  'chat-save-image': async (id, el) => {
    const msg = S.messages.find(m => String(m.id) === String(id));
    const images = (msg && msg.meta && msg.meta.images) || [];
    const im = images[Number((el && el.dataset.index) || 0)];
    if (!im || !im.url) return toast('找不到这张图', 'warn');
    try {
      const d = await API.post('/api/assets/from-image', {
        url: im.url,
        name: im.name || '对话图片',
        type: im.type || '其他',
        desc: im.desc || im.name || ''
      });
      toast(d.created ? `已转存到资产库：${d.asset.name}` : '这张图已经在资产库', d.created ? 'ok' : 'info');
    } catch (err) {
      toast('转存失败：' + err.message, 'warn');
    }
  },
  'chat-generate-images': (id) => {
    const msg = S.messages.find(m => String(m.id) === String(id));
    const assets = (msg && msg.meta && msg.meta.plan && msg.meta.plan.assets) || [];
    if (!assets.length) return toast('这条消息里没有可生成的资产', 'warn');
    confirmModal({
      title: '生成资产图',
      desc: `将调用图片模型为「${assets.map(a => a.name).join('、')}」生成 ${assets.length} 张设定图，按张计费，每张约 20–40 秒。`,
      label: '开始生成',
      action: 'chat-generate-images-confirm',
      id,
      danger: false
    });
  },
  'chat-generate-images-confirm': async (id) => {
    closeModal();
    await generatePlanImages(id);
  },
  'chip-pick': (id, el) => {
    const group = el.parentElement;
    Array.from(group.children).forEach(c => {
      c.className = 'rounded-full border px-2.5 py-1 text-[11.5px] transition border-line2 bg-panel text-sub hover:border-amber/45 hover:text-txt';
    });
    el.className = 'rounded-full border px-2.5 py-1 text-[11.5px] transition border-amber/55 bg-amber/12 text-amber2';
  },
  'chat-detach': () => { chatAttachment = null; renderChatAttachment(); },
  'upload-image': () => pickFile('image/*', async file => {
    try { chatAttachment = await uploadToServer(file); renderChatAttachment(); toast('已附加参考图', 'ok'); }
    catch (err) { toast(err.message, 'warn'); }
  }),
  'upload-file': () => pickFile('', async file => {
    try { chatAttachment = await uploadToServer(file); renderChatAttachment(); toast('已附加文件', 'ok'); }
    catch (err) { toast(err.message, 'warn'); }
  }),

  /* 资产 */
  /* ================= B · 资产 / 批量 / 迁移 ================= */
  'asset-new': () => {
    if (!S.current.projectId) return toast('先新建一个项目', 'warn');
    assetModal();
  },
  'asset-confirm-drafts': async () => {
    const ids = (S.pendingAssets || []).slice();
    if (!ids.length) return;
    if (S.busy.drafts) return toast('正在生成，等这一批完成', 'info');
    S.busy.drafts = true;
    let done = 0;
    try {
      for (const id of ids) {
        const asset = S.assets.find(x => x.id === id);
        toast(`正在生成三视图 ${done + 1}/${ids.length}${asset ? '：' + asset.name : ''}（每项约 1 分钟）`, 'info');
        await API.post(`/api/assets/${encodeURIComponent(id)}/preview`, {});
        done += 1;
        S.pendingAssets = ids.slice(done);
        renderAllViews();
      }
      S.pendingAssets = [];
      await refresh({ view: 'assets', toast: `已生成 ${done} 项资产的三视图` });
    } catch (err) {
      S.pendingAssets = ids.slice(done);
      await refresh({ view: 'assets' }).catch(() => {});
      toast(`生成失败：${err.message}${done ? `，已完成 ${done} 项` : ''}`, 'warn');
    } finally {
      S.busy.drafts = false;
    }
  },
  'asset-dismiss-drafts': () => {
    S.pendingAssets = [];
    renderAllViews();
  },
  'asset-save-new': async () => {
    const name = ($('#mAssetName').value || '').trim();
    if (!name) return toast('资产名不能为空', 'warn');
    try {
      const d = await API.post('/api/assets', {
        name, type: $('#mAssetType').value, desc: ($('#mAssetDesc').value || '').trim(),
        locked: $('#mAssetLocked').checked, scopeLevel: $('#mAssetScope').value
      });
      S.editingAsset = (d.asset || {}).id || '';
      closeModal();
      await refresh({ view: 'assets', toast: '资产已创建' });
    } catch (err) { toast('创建失败：' + err.message, 'warn'); }
  },
  'asset-edit': (id) => { S.editingAsset = id; renderAssetDrawer(); switchView('assets'); },
  'asset-card': (id) => { S.editingAsset = id; renderAssetDrawer(); },
  'asset-proposal-adjust': (msgId, el) => {
    const id = (el && el.dataset.msg) || msgId;
    if (id) {
      S.proposalClicked[id] = 'adjust';
      mountView('chat');
    }
    const ta = $('#chatInput');
    if (ta) {
      ta.value = '继续调整：';
      ta.focus();
      fitChatInput();
    }
    toast('说说还有哪里不满意，我再给一版方案', 'info');
  },
  'asset-proposal-generate': async (msgId, el) => {
    msgId = (el && el.dataset.msg) || msgId;
    if (S.chatPending) return toast('上一条还在处理，稍等一下', 'info');
    const msg = S.messages.find(m => String(m.id) === String(msgId));
    const proposal = msg && msg.meta && (msg.meta.assetProposals || [])[0];
    if (!proposal) return toast('找不到变更方案，刷新后再试', 'warn');
    S.proposalClicked[msg.id] = 'generate';
    const pendingId = 'local-generating-' + Date.now();
    S.messages = [
      ...S.messages,
      { id: pendingId, role: 'agent', text: '正在按方案生成草稿，稍等…', meta: {}, createdAt: '' }
    ];
    S.chatPending = true;
    mountView('chat');
    scrollChatToBottom();
    toast('正在按方案生成草稿，约 1–2 分钟…', 'info');
    try {
      const d = await API.post(`/api/assets/${encodeURIComponent(proposal.assetId)}/draft`, {
        desc: proposal.desc,
        changes: proposal.changes || ''
      });
      S.messages = S.messages.filter(m => m.id !== pendingId);
      await API.post('/api/messages', {
        role: 'agent',
        text: '已按方案生成新设定图（未覆盖资产）。',
        meta: {
          assetDraft: {
            assetId: proposal.assetId,
            assetName: proposal.assetName,
            desc: d.desc || proposal.desc,
            previews: d.previews || [],
            draftId: d.draftId || ''
          }
        }
      });
      S.chatPending = false;
      await refresh({ view: 'chat' });
      scrollChatToBottom();
      toast('草稿生成完成，选择是否覆盖资产', 'ok');
    } catch (err) {
      S.messages = S.messages.filter(m => m.id !== pendingId);
      S.chatPending = false;
      delete S.proposalClicked[msg.id];
      await refresh({ view: 'chat' });
      toast('草稿生成失败：' + err.message, 'warn');
    }
  },
  'asset-draft-save': async (msgId, el) => {
    msgId = (el && el.dataset.msg) || msgId;
    const msg = S.messages.find(m => String(m.id) === String(msgId));
    const draft = msg && msg.meta && msg.meta.assetDraft;
    if (!draft) return toast('找不到草稿，刷新后再试', 'warn');
    S.draftClicked[msg.id] = 'save';
    mountView('chat');
    try {
      await API.post(`/api/assets/${encodeURIComponent(draft.assetId)}/draft/save`, {
        desc: draft.desc,
        previews: draft.previews
      });
      await refresh({ view: 'chat', toast: '已覆盖保存到资产' });
      mountView('assets');
    } catch (err) {
      delete S.draftClicked[msg.id];
      await refresh({ view: 'chat' });
      toast('保存失败：' + err.message, 'warn');
    }
  },
  'asset-draft-keep': (msgId, el) => {
    const id = (el && el.dataset.msg) || msgId;
    if (id) {
      S.draftClicked[id] = 'keep';
      mountView('chat');
    }
    toast('草稿已自动保存在后台，资产未覆盖', 'info');
  },
  'asset-jump': async (id) => {
    switchView('assets');
    await refresh({ view: 'assets' });
    const card = document.querySelector(`[data-action="asset-card"][data-id="${id}"]`);
    if (card) card.scrollIntoView({ block: 'center' });
    const asset = S.assets.find(a => a.id === id);
    toast(asset ? `已定位到「${asset.name}」` : '已打开资产库', 'info');
  },
  'asset-close': () => { S.editingAsset = ''; renderAssetDrawer(); },
  'asset-check': (id) => {
    if (S.selected.has(id)) S.selected.delete(id); else S.selected.add(id);
    refreshAssetSelection();
  },
  'batch-clear': () => { S.selected.clear(); refreshAssetSelection(); },
  'batch-migrate': () => openMigrate(Array.from(S.selected), 'move'),
  'batch-copy': () => openMigrate(Array.from(S.selected), 'copy'),
  'asset-migrate': (id) => openMigrate([id], 'copy'),
  'asset-scope': async (id) => {
    S.assetScope = id;
    try {
      const d = await API.get('/api/assets?scope=' + encodeURIComponent(id));
      S.assets = d.assets || [];
      S.assetStats = d.stats || S.assetStats;
      renderAllViews();
    } catch (err) { toast('切换范围失败：' + err.message, 'warn'); }
  },
  'asset-type': (id) => { S.assetType = id; renderAllViews(); },
  'asset-status': (id) => { S.assetStatus = id; renderAllViews(); },
  'asset-enrich': async (id) => {
    const a = S.assets.find(x => x.id === id);
    if (!a) return;
    if (a.locked) return toast('资产已锁定，先解锁再修改', 'warn');
    if (S.busy.enrich) return toast('主 Agent 正在扩写，稍等一下', 'info');
    S.busy.enrich = true;
    toast('主 Agent 正在结合项目与镜头上下文扩写描述…', 'info');
    try {
      const d = await API.post(`/api/assets/${encodeURIComponent(id)}/enrich`, {});
      const prompt = d.prompt || '';
      S.aiPending = {
        assetId: id,
        base: d.base || a.desc || '',
        prompt,
        previewText: prompt.slice(0, 60) + (prompt.length > 60 ? '…' : '')
      };
      S.editingAsset = id;
      renderAssetDrawer();
      toast('扩写完成，确认后可采纳', 'ok');
    } catch (err) {
      toast('扩写失败：' + err.message, 'warn');
    } finally {
      S.busy.enrich = false;
    }
  },
  'asset-ai-accept': async () => {
    if (!S.aiPending) return toast('没有待采纳的补充', 'warn');
    const a = S.assets.find(x => x.id === S.aiPending.assetId);
    if (!a) return;
    try {
      await API.patch('/api/assets/' + encodeURIComponent(a.id), { prompt: S.aiPending.prompt, ai: 'done' });
      S.aiPending = null;
      await refresh({ view: 'assets', toast: '已采纳扩写' });
    } catch (err) { toast('保存失败：' + err.message, 'warn'); }
  },
  'asset-ai-revert': () => { S.aiPending = null; renderAssetDrawer(); toast('已撤销补充', 'info'); },
  'asset-ai-remove': async () => {
    if (!S.aiPending) return toast('没有待移除的补充', 'warn');
    const a = S.assets.find(x => x.id === S.aiPending.assetId);
    if (!a) return;
    try {
      await API.patch('/api/assets/' + encodeURIComponent(a.id), { prompt: S.aiPending.base });
      S.aiPending = null;
      await refresh({ view: 'assets', toast: '已移除补充' });
    } catch (err) { toast('移除失败：' + err.message, 'warn'); }
  },
  'asset-original': () => {
    if (!S.aiPending) return toast('没有可对比的原描述', 'warn');
    openModal(`
      ${modalHead('file-text', '原描述')}
      <div class="px-4 py-3"><p class="whitespace-pre-wrap text-[11.5px] leading-relaxed text-sub">${esc(S.aiPending.base || '（空）')}</p></div>
      ${modalFoot('关闭', '关闭', 'modal-close')}
    `, '480px');
  },
  'asset-fullscreen': (id) => {
    const a = S.assets.find(x => x.id === id);
    if (!a) return;
    const pv = (a.preview && a.preview.length) ? a.preview : [{ label: '正面' }, { label: '侧面' }, { label: '背面' }];
    const single = a.type === '场景' || pv.length === 1;
    const tiles = (single ? pv.slice(0, 1) : pv.slice(0, 3)).map(p => `
      <div class="relative flex ${single ? 'h-[520px]' : 'h-[240px]'} cursor-zoom-in items-end justify-center overflow-hidden rounded-lg border border-line2 bg-[#0C0D10] pb-6" title="双击放大">
        ${(p.kind === 'img' || p.sym) ? previewEl(p, 'contain', a.updatedAt) : ''}
        <span class="absolute bottom-2 rounded bg-black/55 px-1.5 py-[1px] text-[10px] text-txt">${esc(p.label || '')}</span>
      </div>`).join('');
    openModal(`
      ${modalHead('maximize-2', a.name, single ? '概念图' : '三视图')}
      <div class="grid ${single ? 'grid-cols-1' : 'grid-cols-3'} gap-3 bg-[#0C0D10] p-4">${tiles}</div>
      <div class="flex items-center justify-between border-t border-line bg-panel/60 px-4 py-3">
        <span class="text-[10px] text-dim">双击任意一张图可放大</span>
        <button data-action="modal-close" class="rounded-lg border border-line2 px-3 py-1.5 text-[11.5px] text-sub transition hover:bg-raise hover:text-txt">关闭</button>
      </div>
    `, single ? '760px' : '720px');
  },
  'asset-save': async (id) => { await saveAssetPrompt(id, false); },
  'asset-save-sync': async (id) => { await saveAssetPrompt(id, true); },
  'asset-lock': async (id) => {
    try { await API.patch('/api/assets/' + encodeURIComponent(id), { locked: true }); await refresh({ view: 'assets', toast: '已锁定' }); }
    catch (err) { toast('操作失败：' + err.message, 'warn'); }
  },
  'asset-unlock': async (id) => {
    try { await API.patch('/api/assets/' + encodeURIComponent(id), { locked: false }); await refresh({ view: 'assets', toast: '已解锁' }); }
    catch (err) { toast('操作失败：' + err.message, 'warn'); }
  },
  'asset-copy': async (id) => {
    try { await API.post(`/api/assets/${encodeURIComponent(id)}/copy`, {}); await refresh({ view: 'assets', toast: '已复制为副本' }); }
    catch (err) { toast('复制失败：' + err.message, 'warn'); }
  },
  'asset-delete': (id) => {
    const a = S.assets.find(x => x.id === id);
    if (!a) return;
    confirmModal({ title: '删除资产', desc: `确定删除「${a.name}」？引用它的镜头会失去这条设定。`, label: '删除资产', action: 'asset-delete-confirm', id });
  },
  'asset-delete-confirm': async (id) => {
    try {
      await API.del('/api/assets/' + encodeURIComponent(id));
      closeModal();
      if (S.editingAsset === id) S.editingAsset = '';
      await refresh({ view: 'assets', toast: '资产已删除' });
    } catch (err) { toast('删除失败：' + err.message, 'warn'); }
  },
  'asset-regen-preview': (id) => generateAssetPreview(id),
  'asset-generate': (id) => generateAssetPreview(id),
  'asset-reference-views': (id) => generateReferenceViews(id),
  'asset-reference-accept': async (id, el) => {
    const msg = [...S.messages].reverse().find(item => item.meta && item.meta.assetReferenceViews && item.meta.assetReferenceViews.assetId === id);
    const draft = msg && msg.meta.assetReferenceViews;
    if (!draft || !draft.previews || !draft.previews.length) return toast('找不到三视图草稿', 'warn');
    try {
      await API.post(`/api/assets/${encodeURIComponent(id)}/draft/save`, { previews: draft.previews, desc: draft.desc || '' });
      await API.post('/api/messages', { role: 'agent', text: `已用三视图替换「${draft.assetName}」的用户参考图，后续镜头将使用三视图设定。`, meta: {} });
      await refresh({ view: S.view, toast: '资产已替换为三视图' });
    } catch (err) {
      toast('替换失败：' + err.message, 'warn');
    }
  },
  'asset-reference-keep': (id) => toast('已保留用户参考图，三视图草稿仍可在上方确认替换', 'info'),
  'asset-from-chat': async () => {
    const lastUser = [...S.messages].reverse().find(m => m.role === 'user');
    if (!lastUser) return toast('对话里还没有你的描述', 'warn');
    const desc = lastUser.text;
    const name = desc.slice(0, 12) || '对话提取';
    try {
      await API.post('/api/assets', { name, type: '其他', desc, locked: false });
      await refresh({ view: 'assets', toast: '已从对话中提取一项资产' });
    } catch (err) { toast('提取失败：' + err.message, 'warn'); }
  },
  'asset-tag-add': (id) => {
    const a = S.assets.find(x => x.id === id);
    if (!a) return;
    openModal(`
      ${modalHead('tag', '添加风格标签', a.name)}
      <div class="px-4 py-3"><label class="block ${labelCls}">标签<input id="mTag" placeholder="输入标签" class="${inputCls}" /></label></div>
      ${modalFoot('取消', '添加', 'asset-tag-save', id)}
    `, '420px');
  },
  'asset-tag-save': async (id) => {
    const tag = ($('#mTag').value || '').trim();
    if (!tag) return toast('标签不能为空', 'warn');
    const a = S.assets.find(x => x.id === id);
    if (!a) return;
    const tags = (a.tags || []).concat(tag);
    try {
      await API.patch('/api/assets/' + encodeURIComponent(id), { tags });
      closeModal();
      await refresh({ view: 'assets', toast: '标签已添加' });
    } catch (err) { toast('添加失败：' + err.message, 'warn'); }
  },
  'asset-tag-del': async (id, el) => {
    const index = Number(el.dataset.index);
    const a = S.assets.find(x => x.id === id);
    if (!a) return;
    const tags = (a.tags || []).filter((_, i) => i !== index);
    try {
      await API.patch('/api/assets/' + encodeURIComponent(id), { tags });
      await refresh({ view: 'assets' });
    } catch (err) { toast('删除失败：' + err.message, 'warn'); }
  },

  /* 迁移 */
  'migrate-close': () => closeMigrate(),
  'migrate-mode': (id) => { S.migrate.mode = id; renderMigrate(); },
  'migrate-target': (id) => {
    S.migrate.target = id;
    S.migrate.ids.forEach(aid => {
      const me = (S.migrate.allAssets || []).find(a => a.id === aid);
      const dup = (S.migrate.allAssets || []).find(a => a.projectId === id && me && a.name === me.name);
      if (!dup) S.migrate.conflicts[aid] = 'keep';
    });
    renderMigrate();
  },
  'migrate-conflict': (id, el) => { S.migrate.conflicts[id] = el.dataset.value; renderMigrate(); },
  'migrate-lock': (id, el) => { S.migrate.conflicts[id + ':lock'] = el.dataset.value; renderMigrate(); },
  'migrate-confirm': async () => {
    if (!S.migrate.target) return toast('先选择目标项目', 'warn');
    const target = S.projects.find(p => p.id === S.migrate.target);
    try {
      const d = await API.post('/api/assets/migrate', {
        ids: S.migrate.ids, targetProjectId: S.migrate.target, mode: S.migrate.mode,
        conflicts: S.migrate.conflicts
      });
      closeMigrate();
      S.selected.clear();
      await refresh({ view: 'assets', toast: `迁移完成：新增 ${d.copied + d.moved} 项，跳过 ${d.skipped} 项` });
    } catch (err) { toast('迁移失败：' + err.message, 'warn'); }
  },

  /* 镜头 / 视频 */
  /* ================= C · 镜头 / 视频 / 时间轴 ================= */
  'shot-new': async () => {
    if (!S.current.subId) return toast('先新建项目或子项目', 'warn');
    try {
      const d = await API.post('/api/shots', { name: '新镜头', dur: 3.0, prompt: '' });
      S.video.shotId = (d.shot || {}).id || '';
      await refresh({ view: 'video', toast: '已新增镜头' });
    } catch (err) { toast('新增失败：' + err.message, 'warn'); }
  },
  'shot-select': (id) => {
    S.video.shotId = id;
    const idx = S.shots.findIndex(s => s.id === id);
    const start = S.shots.slice(0, idx).reduce((a, s) => a + s.dur, 0);
    S.video.playhead = totalDur() ? (start / totalDur()) * 100 : 0;
    if (S.view !== 'video') { mountView('video'); switchView('video'); } else { mountView('video'); }
    /* 对话里提交的镜头不会自动轮询：选中它时把进度接回来 */
    const picked = S.shots.find(x => x.id === id);
    if (picked && picked.providerJob && !picked.clipPath && picked.status === 'redraw') pollShotVideo(id, picked.no);
  },
  'shot-redo': (id) => {
    const s = S.shots.find(x => x.id === id);
    if (!s) return;
    if (videoConfigured()) {
      if (s.providerJob && !s.clipPath && s.status === 'redraw') return pollShotVideo(id, s.no);
      if (!s.refMode) {
        openShotFrameConfirm(id);
        return;
      }
      confirmModal({
        title: s.clipPath ? '重新生成这个镜头的视频' : '生成这个镜头的视频',
        desc: `会用 MiniMax H3 全能参考提交：提示词 + 所选资产图 + 资产设定描述，生成约 ${Math.max(4, Math.round(s.dur))} 秒素材（时间轴按 ${s.dur.toFixed(1)} 秒截取），按次计费，通常需要 1–5 分钟。`,
        label: '开始生成',
        action: 'shot-video-confirm',
        id,
        danger: false
      });
      return;
    }
    simulateRedraw(id);
  },
  'shot-redo-keys': (id) => openShotFrameConfirm(id),
  'shot-frame-regen': (id) => loadShotFrame(id, true),
  'shot-frame-confirm': async (id) => {
    const btn = $('#frameConfirmBtn');
    if (btn) { btn.disabled = true; btn.textContent = '确认中…'; }
    try {
      await API.post(`/api/shots/${encodeURIComponent(id)}/keyframe`, { confirm: true });
      closeModal();
      await generateShotVideo(id);
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = '确认，用此首帧生成视频'; }
      toast('确认首帧失败：' + err.message, 'warn');
    }
  },
  'shot-regen-keys': (id) => regenShotKeyframe(id),
  'shot-ref-mode': async (id, el) => {
    const shot = S.shots.find(s => s.id === id);
    if (!shot) return;
    const assetMode = el && el.dataset.mode === 'asset';
    try {
      await API.patch('/api/shots/' + encodeURIComponent(id), { refMode: assetMode });
      await refresh({ view: 'video', toast: assetMode ? '已启用资产全能参考模式' : '已启用首帧模式' });
    } catch (err) {
      toast('切换失败：' + err.message, 'warn');
    }
  },
  'shot-ref-toggle': async (id) => {
    const shot = S.shots.find(s => s.id === id);
    if (!shot) return;
    try {
      await API.patch('/api/shots/' + encodeURIComponent(id), { refMode: !shot.refMode });
      await refresh({ view: 'video', toast: shot.refMode ? '已切换回首帧模式' : '已启用资产全能参考模式' });
    } catch (err) {
      toast('切换失败：' + err.message, 'warn');
    }
  },
  'shot-ref-pick': (id) => {
    const shot = S.shots.find(s => s.id === id);
    if (!shot) return;
    S.refShotId = id;
    const selected = new Set(shot.refAssets || []);
    const rows = S.assets.length
      ? S.assets.map(a => `<label class="flex items-center gap-2 rounded-md border border-line bg-panel/50 px-2 py-1.5 text-[11px] text-txt">
          <input type="checkbox" data-ref-asset="${a.id}" ${selected.has(a.id) ? 'checked' : ''} class="accent-amber" />
          <span class="min-w-0 flex-1 truncate">${esc(a.name)}</span>
          <span class="shrink-0 text-[9px] text-dim">${esc(a.type)}</span>
        </label>`).join('')
      : `<p class="py-6 text-center text-[11px] text-dim">资产库还没有资产，先生成角色/场景设定图</p>`;
    openModal(`
      ${modalHead('layers', '选择参考资产', shot.name)}
      <div class="hide-scroll max-h-[360px] space-y-1.5 overflow-y-auto px-4 py-3">${rows}</div>
      <div class="border-t border-line px-4 py-2">
        <button data-action="shot-ref-auto" class="flex w-full items-center justify-center gap-1.5 rounded-md border border-amber/40 bg-amber/10 py-1.5 text-[10.5px] text-amber2 transition hover:bg-amber/20">
          ${ic('sparkles', 'h-3 w-3')}Agent 自动选择
        </button>
      </div>
      ${modalFoot('取消', '保存', 'shot-ref-save')}
    `, '520px');
  },
  'shot-ref-save': async () => {
    const id = S.refShotId;
    if (!id) return;
    const ids = $$('[data-ref-asset]').filter(el => el.checked).map(el => el.dataset.refAsset);
    try {
      await API.patch('/api/shots/' + encodeURIComponent(id), { refMode: true, refAssets: ids });
      closeModal();
      await refresh({ view: 'video', toast: ids.length ? `已选择 ${ids.length} 项参考资产` : '已启用涉及资产，生成时自动选择' });
    } catch (err) {
      toast('保存失败：' + err.message, 'warn');
    }
  },
  'shot-ref-auto': async () => {
    const id = S.refShotId;
    if (!id) return;
    try {
      const d = await API.post(`/api/shots/${encodeURIComponent(id)}/ref-assets/auto`, {});
      closeModal();
      await refresh({ view: 'video', toast: `Agent 已选择 ${(d.assetIds || []).length} 项参考资产` });
    } catch (err) {
      toast('自动选择失败：' + err.message, 'warn');
    }
  },
  'shot-video-confirm': async (id) => {
    closeModal();
    await generateShotVideo(id);
  },
  'generate-all-shots': () => {
    const targets = S.shots.filter(s => !s.clipPath && !s.providerJob);
    if (!targets.length) return toast('没有待生成的镜头', 'warn');
    if (targets.some(s => !s.refMode)) {
      return toast('首帧模式需要逐镜确认首帧，请在每个镜头里点「生成视频」逐个确认', 'warn');
    }
    confirmModal({
      title: '一键生成所有镜头',
      desc: `将依次提交 ${targets.length} 个镜头，每个约 ${Math.round(targets[0].dur || 4)} 秒，按次计费。`,
      label: '开始生成',
      action: 'generate-all-confirm',
      id: '',
      danger: false
    });
  },
  'generate-all-keyframes': async () => {
    const missing = S.shots.filter(s => !s.hasFirstFrame);
    const targets = missing.filter(s => (s.prompt || '').trim());
    if (!targets.length) {
      if (!S.shots.length) return toast('没有可生成首帧的镜头', 'info');
      if (missing.length) return toast('缺少提示词，无法生成首帧', 'info');
      return toast('所有镜头都已有首帧', 'info');
    }
    if (S.busy.keyframes) return toast('首帧正在生成，等这一批完成', 'info');
    S.busy.keyframes = true;
    let done = 0;
    try {
      for (const shot of targets) {
        toast(`正在生成首帧 ${done + 1}/${targets.length}：镜头 ${shot.no}`, 'info');
        await API.post(`/api/shots/${encodeURIComponent(shot.id)}/keyframe`, {});
        done += 1;
      }
      await refresh({ view: 'video', toast: `已生成 ${done} 个镜头的首帧` });
    } catch (err) {
      await refresh({ view: 'video' }).catch(() => {});
      toast(`首帧生成失败：${err.message}${done ? `，已完成 ${done} 个` : ''}`, 'warn');
    } finally {
      S.busy.keyframes = false;
    }
  },
  'generate-all-confirm': async () => {
    closeModal();
    const targets = S.shots.filter(s => !s.clipPath && !s.providerJob);
    if (targets.some(s => !s.refMode)) {
      return toast('首帧模式需要逐镜确认首帧，已停止批量提交', 'warn');
    }
    let submitted = 0;
    for (const shot of targets) {
      try {
        await API.post(`/api/shots/${encodeURIComponent(shot.id)}/video`, {});
        pollShotVideo(shot.id, shot.no);
        submitted += 1;
      } catch (err) {
        toast(`镜头 ${shot.no} 提交失败：${err.message}`, 'warn');
      }
    }
    if (submitted) toast(`已提交 ${submitted} 个镜头`, 'ok');
    await refresh({ view: 'video' });
  },
  'shot-stop': async (id) => {
    stopShotPoll(id);
    try {
      await API.patch('/api/shots/' + encodeURIComponent(id), { status: 'pending', progress: 0 });
      await refresh({ view: S.view, toast: '已停止等待；云端任务可能仍在运行，再点重做会继续查询' });
    } catch (err) { toast('停止失败：' + err.message, 'warn'); }
  },
  'shot-split': async (id) => {
    pushUndo();
    try {
      await API.post(`/api/shots/${encodeURIComponent(id)}/split`, { ratio: 0.5 });
      await refresh({ view: 'video', toast: '镜头已拆成两段' });
    } catch (err) { toast('拆分失败：' + err.message, 'warn'); }
  },
  'shot-delete': (id) => {
    const s = S.shots.find(x => x.id === id);
    if (!s) return;
    confirmModal({ title: '删除镜头', desc: `确定删除镜头 ${s.no}「${s.name}」？`, label: '删除镜头', action: 'shot-delete-confirm', id });
  },
  'shot-delete-confirm': async (id) => {
    pushUndo();
    stopShotPoll(id);
    try {
      await API.del('/api/shots/' + encodeURIComponent(id));
      closeModal();
      if (S.video.shotId === id) S.video.shotId = '';
      await refresh({ view: 'video', toast: '镜头已删除' });
    } catch (err) { toast('删除失败：' + err.message, 'warn'); }
  },
  'shot-endframe': async (id) => {
    const s = S.shots.find(x => x.id === id);
    if (!s) return;
    const frames = ['street', 'push', 'door', 'shelf', 'counter', 'bell'];
    const next = frames[(frames.indexOf(s.frame) + 1) % frames.length];
    try {
      await API.patch('/api/shots/' + encodeURIComponent(id), { frame: next });
      await refresh({ view: 'video', toast: '末帧已更换' });
    } catch (err) { toast('更换失败：' + err.message, 'warn'); }
  },
  'undo': undoLast,
  'play': () => {
    if (!totalDur()) return toast('还没有镜头', 'warn');
    const btn = document.querySelector('[data-action="play"]');
    const v = previewVideo();
    if (!v) return toast('这个位置还没有视频，先生成一个镜头', 'warn');
    if (v.paused) {
      v.play().catch(() => {});
      S.video.playing = true;
    } else {
      v.pause();
      S.video.playing = false;
    }
    if (btn) btn.innerHTML = ic(S.video.playing ? 'pause' : 'play', 'h-3 w-3 text-[#1B0E05]');
  },
  'tool': (id) => { S.video.tool = id; mountView('video'); },
  'export': async () => {
    try {
      toast('正在按时间轴拼接成片，请稍候', 'info');
      const d = await API.post('/api/shots/stitch', { mode: 'trim' });
      downloadFile(d.url);
      toast(`成片已生成：${d.count} 段 · ${d.duration}s`, 'ok');
    } catch (err) { toast('导出失败：' + err.message, 'warn'); }
  },
  'subtitles': () => { toast('正在按镜头生成字幕', 'info'); downloadFile('/api/export/subtitles.srt'); },
  'text-edit': () => runTextEdit($('#textEditInput') ? $('#textEditInput').value : ''),
  'text-edit-suggest': (id) => {
    const ta = $('#textEditInput');
    if (ta) { ta.value = id; ta.focus(); }
  },
  'material-upload': () => pickFile('', async file => {
    try {
      const up = await uploadToServer(file);
      await API.post('/api/materials', { label: up.name, kind: up.kind === '图片' ? '图片' : '视频', dur: '' });
      await refresh({ view: 'video', toast: '素材已上传' });
    } catch (err) { toast(err.message, 'warn'); }
  }),
  'material-insert': (id) => {
    const m = S.materials.find(x => x.id === id);
    if (!m) return;
    toast(`已把「${m.label}」插入到播放头位置（本地预览，未渲染）`, 'ok');
  },
  'narration-add': () => {
    openModal(`
      ${modalHead('mic', '添加旁白', '音频轨')}
      <div class="px-4 py-3"><label class="block ${labelCls}">旁白文本<textarea id="mNarr" rows="3" placeholder="这一句要说什么……" class="${inputCls}"></textarea></label></div>
      ${modalFoot('取消', '添加到轨道', 'narration-save')}
    `, '460px');
  },
  'narration-save': async () => {
    const text = ($('#mNarr').value || '').trim();
    if (!text) return toast('旁白不能为空', 'warn');
    try {
      await API.post('/api/materials', { label: text.slice(0, 18), kind: '音频', wave: '#8A8F98' });
      closeModal();
      await refresh({ view: 'video', toast: '旁白已添加到轨道' });
    } catch (err) { toast('添加失败：' + err.message, 'warn'); }
  },

  /* 成片确认 */
  'shot-review': async () => {
    if (S.busy.shotReview) return;
    const targets = S.shots.filter(canReview);
    if (!targets.length) return toast('暂无可复述的视频', 'info');
    S.busy.shotReview = true;
    const sub = S.current.subId;
    mountView('confirm');
    try {
      for (const shot of targets) {
        try {
          const result = await API.post(`/api/shots/${encodeURIComponent(shot.id)}/review`, { mode: 'manual', prompt: shot.prompt });
          const current = S.shots.find(s => s.id === shot.id && s.clipPath === result.clip);
          if (current) current.review = result;
        } catch (err) { toast(`镜头 ${shot.no}：${err.message}`, 'warn'); }
      }
    } finally {
      S.busy.shotReview = false;
      if (sub === S.current.subId) mountView('confirm');
    }
  },
  'back-to-video': () => switchView('video'),
  'asset-enrich-shot': async (id) => {
    const s = S.shots.find(x => x.id === id);
    if (!s) return;
    try {
      await API.patch('/api/shots/' + encodeURIComponent(id), {
        prompt: `${s.prompt}${s.prompt ? ' ' : ''}补充：前景有轻微雨雾，光线从右上方来。`, status: 'modified', ai: '1 处'
      });
      await refresh({ view: 'confirm', toast: '已丰富提示词（本地模拟）' });
    } catch (err) { toast('失败：' + err.message, 'warn'); }
  },

  /* 个人中心 */
  /* ================= A · 个人中心 / API 设置 / 账单 ================= */
  'drawer-collapse': (id) => { S.drawer.collapsed[id] = !S.drawer.collapsed[id]; renderDrawer(); },
  'save-settings': async () => saveApiSettings(),
  'api-reset': async () => {
    try {
      const d = await API.post('/api/settings/api/reset', {});
      S.settings.api = d.api;
      renderDrawer();
      toast('已恢复平台默认设置', 'ok');
    } catch (err) { toast('恢复失败：' + err.message, 'warn'); }
  },
  'api-test': async (id) => {
    try {
      const d = await API.post('/api/settings/api/test', { group: id });
      toast(d.message, d.ok ? 'ok' : 'warn');
    } catch (err) { toast('测试失败：' + err.message, 'warn'); }
  },
  'key-reveal': () => toast('密钥只以掩码形式提供，明文保存在本地数据库，不会回显', 'info'),
  'key-copy': async (id) => {
    const cfg = (S.settings.api || {})[id] || {};
    const text = cfg.api_key || '';
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制掩码', 'ok');
    } catch (e) {
      toast('浏览器不允许写剪贴板', 'warn');
    }
  },
  'bill-full': () => openModal(`
    ${modalHead('receipt', '完整账单', '本月')}
    <div class="px-4 py-4">
      ${(S.spend.records || []).length ? S.spend.records.map(r => `
        <div class="flex items-center gap-2.5 border-b border-line/60 py-2 text-[11px]">
          <span class="w-[64px] shrink-0 text-[10px] text-dim">${esc(r.time)}</span>
          <span class="min-w-0 flex-1 truncate text-sub">${esc(r.desc)}</span>
          <span class="shrink-0 tabular-nums">${esc(r.amount)}</span>
        </div>`).join('') : `<p class="py-6 text-center text-[11px] text-dim">还没有消费记录</p>`}
    </div>
    ${modalFoot('关闭', '关闭', 'modal-close')}
  `, '480px'),
  'bill-project': () => toast('还没有按项目拆分的账单数据', 'info'),

  /* 弹窗关闭 */
  /* ================= 共享 · 弹窗 ================= */
  'modal-close': () => closeModal()
};

/* ================= B · 资产出图 ================= */
async function generateAssetPreview(id) {
  const a = S.assets.find(x => x.id === id);
  if (!a) return;
  toast('正在生成三视图（Seedream，约 1 分钟）', 'info');
  a.ai = 'generating'; a.progress = 8;
  renderAllViews();
  try {
    const got = await API.post(`/api/assets/${encodeURIComponent(id)}/preview`, {});
    const fresh = (await API.get('/api/assets?scope=' + encodeURIComponent(S.assetScope))).assets;
    if (fresh) S.assets = fresh;
    // 体检只报告不阻断：缺口挂在卡片上，让用户决定要不要整张重来
    const gaps = (got && got.audit && got.audit.gaps) || [];
    S.assetAudit = S.assetAudit || {};
    if (gaps.length) S.assetAudit[id] = gaps; else delete S.assetAudit[id];
    await refresh({ view: 'assets', toast: gaps.length ? `三视图已生成，体检发现 ${gaps.length} 处要改` : '三视图已生成' });
  } catch (err) {
    const cur = S.assets.find(x => x.id === id);
    if (cur) { cur.ai = 'none'; cur.progress = 0; renderAllViews(); }
    toast('生成失败：' + err.message, 'warn');
  }
}

/* ================= B · 资产保存 ================= */
export async function saveAssetPrompt(id, sync) {
  const a = S.assets.find(x => x.id === id);
  if (!a) return;
  const ta = $(`[data-asset-prompt="${id}"]`);
  const nameInput = $(`[data-asset-name="${id}"]`);
  const text = ta ? ta.value.trim() : (a.desc || '');
  const name = nameInput ? nameInput.value.trim() : (a.name || '');
  if (!name) return toast('资产名称不能为空', 'warn');
  try {
    const body = { name };
    if (text) body.prompt = text;
    await API.patch('/api/assets/' + encodeURIComponent(id), body);
    if (S.aiPending && S.aiPending.assetId === id) S.aiPending = null;
    await refresh({ view: 'assets', toast: sync ? '已保存并同步到所有镜头' : '已保存到资产库' });
  } catch (err) { toast('保存失败：' + err.message, 'warn'); }
}

async function generateReferenceViews(id) {
  const asset = S.assets.find(item => item.id === id);
  if (!asset) return toast('资产不存在', 'warn');
  if (!((S.settings.api || {}).img || {}).api_key) return toast('还没有配置图片模型 API Key', 'warn');
  try {
    const d = await API.post(`/api/assets/${encodeURIComponent(id)}/draft`, { desc: asset.desc || asset.name });
    await API.post('/api/messages', {
      role: 'agent',
      text: `已为「${asset.name}」生成三视图草稿。请确认是否用三视图替换资产里的用户参考图。`,
      meta: {
        assetReferenceViews: {
          assetId: id,
          assetName: asset.name,
          previews: d.previews || [],
          desc: d.desc || asset.desc || ''
        }
      }
    });
    await refresh({ view: S.view, toast: '三视图草稿已生成，请确认是否替换封面' });
  } catch (err) {
    toast('三视图生成失败：' + err.message, 'warn');
  }
}

export function renderChatAttachment() {
  const host = $('#chatAttach');
  if (!host) return;
  if (!chatAttachment) { host.classList.add('hidden'); host.innerHTML = ''; return; }
  host.classList.remove('hidden');
  host.classList.add('flex');
  const isImage = chatAttachment.kind === '图片' && chatAttachment.url;
  host.innerHTML = `
    ${isImage
      ? `<img src="${esc(chatAttachment.url)}" alt="${esc(chatAttachment.name)}" class="h-9 w-9 rounded-[5px] border border-line bg-base object-cover" />`
      : ic('paperclip', 'h-2.5 w-2.5')}
    <span class="max-w-[140px] truncate">${esc(chatAttachment.name)}</span>
    <button data-action="chat-detach" class="ml-0.5 shrink-0 text-dim transition hover:text-danger" title="移除">${ic('x', 'h-3 w-3')}</button>`;
  paint(host);
}
