/* Vagent · 事件绑定、初始化
   只在本模块内改动，跨模块依赖走上面的 import。 */

import { $, API, S, clamp, paint, timeLabel, toast, totalDur } from './core.js';
import { closeDrawer, openDrawer, renderDrawer } from './drawer.js';
import { closeLightbox, closeMigrate, closeModal, ensureModalHost, lightboxOpen, openLightbox } from './ui.js';
import { renderAssetGrid } from './assets.js';
import { statusPill } from './video.js';
import { updateConfirmStats } from './confirm.js';
import { boot, closeSwitcher, mountView, openSwitcher, refresh, renderRecent, switchView } from './shell.js';
import { ACTIONS } from './actions.js';
import { fitChatInput } from './chat.js';
export function bindEvents() {
  document.addEventListener('click', async e => {
    const target = e.target;
    if (target.closest('[data-lightbox-close]')) { closeLightbox(); return; }
    const viewBtn = target.closest('button[data-view]');
    if (viewBtn) {
      const id = viewBtn.dataset.view;
      if (!S.projects.length && id !== 'manage') { toast('先新建一个项目', 'warn'); return; }
      switchView(id);
      return;
    }

    const el = target.closest('[data-action]');
    if (!el) {
      if (target.closest('#switcherBtn')) {
        const panel = $('#switcherPanel');
        panel.classList.contains('hidden') ? openSwitcher() : closeSwitcher();
        return;
      }
      if (target.closest('#avatarBtn')) { S.drawer.open ? closeDrawer() : openDrawer(); return; }
      if (target.closest('[data-drawer-close]')) { closeDrawer(); return; }
      const tab = target.closest('[data-tab]');
      if (tab) { S.drawer.tab = tab.dataset.tab; renderDrawer(); return; }
      if (target.closest('[data-migrate-close]')) { closeMigrate(); return; }
      if (target.closest('#modalMask') && !target.closest('#modalHost')) { closeModal(); return; }
      if (target.closest('[data-migrate-close]')) { closeMigrate(); return; }
      return;
    }

    const action = el.dataset.action;
    const id = el.dataset.id || '';
    if (action === 'shot-select') { S.video.shotId = id; }
    const fn = ACTIONS[action];
    if (!fn) return;
    e.preventDefault();
    e.stopPropagation();
    try { await fn(id, el); } catch (err) { toast(err.message || '操作失败', 'warn'); }
  });

  document.addEventListener('input', e => {
    const t = e.target;
    if (t.id === 'chatInput') { fitChatInput(); return; }
    if (t.id === 'projSearch') { renderRecent(); return; }
    if (t.id === 'assetSearch') {
      S.assetQuery = t.value;
      const grid = renderAssetGrid();
      const g = $('#assetGrid');
      if (g) g.innerHTML = grid.html;
      const sum = $('#assetSummary');
      if (sum) sum.textContent = grid.summary;
      paint($('#assetGrid'));
      return;
    }
    if (t.dataset && t.dataset.clarifyInput && S.clarify) {
      const slot = S.clarify.slots && S.clarify.slots[t.dataset.clarifyInput];
      if (slot) slot.text = t.value;
      return;
    }
    if (t.dataset && t.dataset.assetPrompt) {
      const id = t.dataset.assetPrompt;
      const a = S.assets.find(x => x.id === id);
      if (a) a.desc = t.value;
      if (a && a.locked) return;
      queuePatch('asset-' + id, '/api/assets/' + encodeURIComponent(id), { prompt: t.value },
        `资产「${a ? a.name : id}」提示词已保存`);
      return;
    }
    if (t.dataset && t.dataset.shotPrompt) {
      const id = t.dataset.shotPrompt;
      const s = S.shots.find(x => x.id === id);
      if (s) s.prompt = t.value;
      if (t.value.trim()) queuePatch('shot-' + id, '/api/shots/' + encodeURIComponent(id), { prompt: t.value }, `镜头提示词已保存`);
      return;
    }
    if (t.dataset && t.dataset.confirmPrompt) {
      const s = S.shots.find(x => x.id === t.dataset.confirmPrompt);
      if (!s) return;
      s.prompt = t.value;
      if (t.value.trim()) queuePatch('shot-' + s.id, '/api/shots/' + encodeURIComponent(s.id), { prompt: t.value }, `镜头 ${s.no} 提示词已保存`);
      if (s.status !== 'modified') {
        s.status = 'modified';
        API.patch('/api/shots/' + encodeURIComponent(s.id), { status: 'modified' }).catch(() => {});
        const pill = document.querySelector(`[data-status-pill="${s.id}"]`);
        if (pill) { pill.innerHTML = statusPill('modified'); paint(pill); }
      }
      updateConfirmStats(s);
    }
  });

  document.addEventListener('change', e => {
    const t = e.target;
    if (['model', 'base_url', 'provider'].includes(t.dataset?.cfg)) {
      const capacity = t.closest('[data-api-group="llm"]')?.querySelector('[data-cfg="context_limit"]');
      if (capacity) capacity.value = '';
    }
    if (!t.dataset || !t.dataset.shotDur) return;
    const id = t.dataset.shotDur;
    const shot = S.shots.find(x => x.id === id);
    if (!shot) return;
    const dur = Math.round(clamp(Number(t.value) || Number(shot.dur) || 4, 1, 15) * 2) / 2;
    t.value = dur.toFixed(1);
    if (Math.abs(dur - Number(shot.dur)) < 0.01) return;
    API.patch('/api/shots/' + encodeURIComponent(id), { dur })
      .then(() => {
        shot.dur = dur;
        mountView('video');
        toast(`镜头 ${shot.no} 时长已改为 ${dur.toFixed(1)}s`, 'ok');
      })
      .catch(err => toast('时长保存失败：' + err.message, 'warn'));
  });

  /* 双击图片：全屏弹窗 / 聊天里的图 → 单图灯箱；卡片 → 打开三视图 */
  document.addEventListener('dblclick', e => {
    if (lightboxOpen()) return;
    const img = e.target.closest('#modalHost img, #chatThread img');
    if (img) {
      openLightbox(img.getAttribute('src'), img.getAttribute('alt') || '');
      return;
    }
    const card = e.target.closest('#assetGrid [data-action="asset-card"]');
    if (!card) return;
    const hit = e.target.closest('[data-action]');
    if (hit && hit !== card) return;
    const fn = ACTIONS['asset-fullscreen'];
    if (fn) fn(card.dataset.id, card);
  });

  document.addEventListener('keydown', e => {
    const ta = e.target;
    const clarifyInput = ta && ta.closest ? ta.closest('[data-clarify-input]') : null;
    if (e.key === 'Enter' && !e.shiftKey && clarifyInput) {
      if (e.isComposing || e.keyCode === 229) return;
      e.preventDefault();
      ACTIONS['clarify-text-ok'](clarifyInput.dataset.clarifyInput);
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && ta && ta.id === 'chatInput') {
      /* 中文输入法选词时的回车不发送 */
      if (e.isComposing || e.keyCode === 229) return;
      e.preventDefault();
      ACTIONS['chat-send']();
      return;
    }
    if (e.key === 'Escape') {
      if (lightboxOpen()) { closeLightbox(); return; }
      if ($('#modalMask') && !$('#modalMask').classList.contains('hidden')) { closeModal(); return; }
      if (!$('#migrateModal').classList.contains('hidden')) { closeMigrate(); return; }
      closeSwitcher();
      if (S.drawer.open) closeDrawer();
    }
  });

  const ruler = () => $('#ruler');
  document.addEventListener('click', e => {
    const r = ruler();
    if (!r || !e.target.closest('#ruler')) return;
    const rect = r.getBoundingClientRect();
    const pct = clamp(((e.clientX - rect.left) / rect.width) * 100, 0, 100);
    S.video.playhead = pct;
    const ph = $('#playhead');
    if (ph) ph.style.left = pct + '%';
    const total = totalDur();
    const cur = total * pct / 100;
    const lbl = $('#playheadLabel');
    if (lbl) lbl.textContent = cur.toFixed(1);
    const pt = $('#previewTime');
    if (pt) pt.textContent = timeLabel(cur);
  });
}

/* 防抖保存 */
export const patchTimers = {};
export function queuePatch(key, url, body, okMsg) {
  clearTimeout(patchTimers[key]);
  patchTimers[key] = setTimeout(async () => {
    try {
      await API.patch(url, body);
      if (okMsg) toast(okMsg, 'ok');
    } catch (err) {
      toast('保存失败：' + err.message, 'warn');
    }
  }, 700);
}

/* ---------- 6 初始化 ---------- */
export function fitFrame() {
  const frame = $('#frame');
  const wrap = $('#frameWrap');
  const s = Math.min(1, window.innerWidth / 1440, window.innerHeight / 900);
  frame.style.transform = `scale(${s})`;
  wrap.style.width = 1440 * s + 'px';
  wrap.style.height = 900 * s + 'px';
}

ACTIONS['modal-close'] = () => closeModal();

window.addEventListener('resize', fitFrame);
document.addEventListener('click', e => {
  if (e.target.closest('#bootRetry')) location.reload();
  if (!e.target.closest('#switcherPanel') && !e.target.closest('#switcherBtn')) closeSwitcher();
});

/* 窗口最小化时浏览器会暂停定时器；恢复后重新读取后端状态，避免时间轴显示旧页面状态。 */
let visibilityRefreshTimer = 0;
function refreshOnReturn() {
  if (!S.ready || document.visibilityState === 'hidden') return;
  clearTimeout(visibilityRefreshTimer);
  visibilityRefreshTimer = setTimeout(() => {
    visibilityRefreshTimer = 0;
    refresh({ view: S.view }).catch(() => {});
  }, 120);
}

document.addEventListener('visibilitychange', refreshOnReturn);
window.addEventListener('focus', refreshOnReturn);

fitFrame();
ensureModalHost();
bindEvents();
boot();
