/* Vagent 前端交互冒烟测试
 *
 * 前置：
 *   1) python vagent_app.py --port 8000     （或任意 BASE_URL）
 *   2) chrome --headless=new --remote-debugging-port=9222 --no-sandbox \
 *        --user-data-dir=/tmp/vagent-cdp http://127.0.0.1:8000/
 * 运行：
 *   node tests/ui_smoke.mjs
 * 环境变量：
 *   BASE_URL（默认 http://127.0.0.1:8000）、CDP_URL（默认 http://127.0.0.1:9222）
 *
 * 脚本会通过接口自建一个「UI 基线」项目及其资产/镜头，不依赖已有数据。
 */

const BASE = (process.env.BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const CDP = (process.env.CDP_URL || 'http://127.0.0.1:9222').replace(/\/$/, '');

let ws;
let seq = 0;
const pending = new Map();
const errors = [];
const consoleErrors = [];
const results = [];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function ev(expr) {
  const r = await send('Runtime.evaluate', {
    expression: `(async () => { ${expr} })()`,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  });
  if (r.exceptionDetails) {
    const d = r.exceptionDetails;
    throw new Error('EVAL: ' + (d.exception?.description || d.text));
  }
  return r.result?.value;
}

function check(name, ok, extra = '') {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (extra ? ' · ' + extra : ''));
}

async function api(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!json.ok) throw new Error(`${method} ${path} -> ${json.error?.message}`);
  return json.data;
}

async function seed() {
  const boot = await api('GET', '/api/bootstrap');
  let projectId = boot.currentProject.projectId;
  if (!projectId) {
    ({ projectId } = await api('POST', '/api/projects', { name: 'UI 基线', kind: '概念片' }));
  }
  await api('POST', '/api/switch', { projectId });
  const assets = await api('GET', '/api/assets?scope=current');
  if (assets.total === 0) {
    await api('POST', '/api/assets', { name: '基线角色', type: '角色', desc: '短发风衣', locked: true });
    await api('POST', '/api/assets', { name: '基线场景', type: '场景', desc: '雨夜街道' });
  }
  const shots = await api('GET', '/api/shots');
  if (shots.total === 0) {
    await api('POST', '/api/shots', { name: '基线镜头 1', dur: 4.0, prompt: '街道远景' });
    await api('POST', '/api/shots', { name: '基线镜头 2', dur: 3.0, prompt: '推门特写' });
  }
  return api('GET', '/api/bootstrap');
}

async function main() {
  await seed();

  const list = await (await fetch(CDP + '/json/list')).json();
  const page = list.find((t) => t.type === 'page');
  if (!page) throw new Error('没有找到指向 ' + BASE + ' 的页面');
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errors.push(d.exception?.description || d.text);
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value || a.description || '').join(' '));
    }
  };
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: BASE + '/' });

  let ready = false;
  for (let i = 0; i < 80; i++) {
    if ((await ev(`return document.querySelectorAll('#rail button[data-view]').length`)) === 5) {
      ready = true;
      break;
    }
    await sleep(400);
  }
  if (!ready) throw new Error('首屏未渲染完成');
  await sleep(500);

  const state = () => api('GET', '/api/bootstrap');

  // ---------- 基础渲染 ----------
  check('页面标题', (await ev('return document.title')) === 'Vagent · 自然语言驱动的 AI 视频 Agent');
  check('启动遮罩已移除', await ev('return !document.querySelector("#bootGate")'));
  check('五个导航按钮', (await ev('return document.querySelectorAll("#rail button[data-view]").length')) === 5);
  check('默认停在项目管理', await ev(`return !!document.querySelector('.view[data-view="manage"].is-active')`));

  await ev(`document.querySelector('#rail button[data-view="assets"]').click(); return 1`);
  await sleep(600);
  check('资产视图挂载', await ev(`return !!document.querySelector('.view[data-view="assets"].is-active #assetGrid')`));
  check('资产卡片渲染', (await ev('return document.querySelectorAll("#assetGrid [data-action=\\"asset-card\\"]").length')) >= 1);

  await ev(`document.querySelector('#rail button[data-view="video"]').click(); return 1`);
  await sleep(700);
  check('视频时间轴渲染', await ev('return !!document.querySelector("#shotTrack") && !!document.querySelector("#ruler")'));
  check('镜头块存在', (await ev('return document.querySelectorAll("#shotTrack [data-action=\\"shot-select\\"]").length')) >= 1);

  await ev(`document.querySelector('#rail button[data-view="confirm"]').click(); return 1`);
  await sleep(600);
  check('成片确认镜头行', (await ev('return document.querySelectorAll("[data-confirm-row]").length')) >= 1);

  // ---------- 项目管理 ----------
  await ev(`document.querySelector('#rail button[data-view="manage"]').click(); return 1`);
  await sleep(500);
  const beforeProjects = (await state()).projects.length;
  await ev(`document.querySelector('[data-action="project-new"]').click(); return 1`);
  await sleep(400);
  check('新建项目弹窗', await ev('return !!document.querySelector("#mName")'));
  check('新建项目无类型字段', await ev('return !document.querySelector("#mKind")'));
  await ev(`document.querySelector('#mName').value = 'UI 新建项目'; document.querySelector('#mDesc').value = 'UI 项目概括'; return 1`);
  await ev(`document.querySelector('[data-action="project-save"]').click(); return 1`);
  await sleep(1400);
  check('新建项目落库', (await state()).projects.length === beforeProjects + 1);
  check('弹窗已关闭', await ev('return document.querySelector("#modalMask").classList.contains("hidden")'));
  check('顶栏跟随切项目', (await ev('return document.querySelector("#switcherName").textContent')) === 'UI 新建项目');

  // ---------- 资产 ----------
  await ev(`document.querySelector('#rail button[data-view="assets"]').click(); return 1`);
  await sleep(600);
  await ev(`document.querySelector('[data-action="asset-new"]').click(); return 1`);
  await sleep(400);
  await ev(`document.querySelector('#mAssetName').value = 'UI 资产'; document.querySelector('#mAssetDesc').value = '灰色毛衣'; return 1`);
  await ev(`document.querySelector('[data-action="asset-save-new"]').click(); return 1`);
  await sleep(1400);
  check('新建资产成功', (await state()).assets.length >= 1);
  check('新建后自动打开抽屉', await ev('return !!document.querySelector("#assetDrawer [data-asset-prompt]")'));

  await ev(`const t = document.querySelector('[data-asset-prompt]'); t.value = '自动保存的提示词'; t.dispatchEvent(new Event('input', { bubbles: true })); return 1`);
  await sleep(1200);
  check('提示词防抖保存', await ev(`const d = (await (await fetch('/api/bootstrap')).json()).data; return d.assets.some(a => a.desc.includes('自动保存的提示词'));`));

  // ---------- 视频 ----------
  await ev(`document.querySelector('#rail button[data-view="video"]').click(); return 1`);
  await sleep(700);
  const shotsBefore = (await state()).shots.length;
  await ev(`document.querySelector('[data-action="shot-new"]').click(); return 1`);
  await sleep(1400);
  check('新增镜头', (await state()).shots.length === shotsBefore + 1, `${shotsBefore} -> ${(await state()).shots.length}`);

  await ev(`const r = document.querySelector('#ruler'); const b = r.getBoundingClientRect(); r.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: b.left + b.width * 0.6, clientY: b.top + 5 })); return 1`);
  await sleep(300);
  check('点击刻度移动播放头', (await ev('return parseFloat(document.querySelector("#playhead").style.left)')) > 50);

  await ev(`document.querySelector('#textEditInput').value = '给全片加冷调'; return 1`);
  await ev(`document.querySelector('[data-action="text-edit"]').click(); return 1`);
  await sleep(1400);
  check('文字剪辑执行', ((await ev('return (document.querySelector("#lastEdit") || {}).textContent || ""')) || '').length > 0);

  await ev(`const b = document.querySelector('[data-action="shot-split"]'); if (b) b.click(); return 1`);
  await sleep(1400);
  check('拆分镜头', (await state()).shots.length >= shotsBefore + 2);

  // ---------- 成片确认 ----------
  await ev(`document.querySelector('#rail button[data-view="confirm"]').click(); return 1`);
  await sleep(600);
  check('未生成的视频显示待生成，开始确认不可提交', await ev(`const b = document.querySelector('[data-action="shot-review"]'); return b.disabled && b.textContent.includes('开始确认') && document.querySelector('[data-confirm-row]').textContent.includes('待生成视频')`));

  // ---------- 个人中心 ----------
  await ev(`document.querySelector('#avatarBtn').click(); return 1`);
  await sleep(600);
  check('抽屉打开', await ev('return !document.querySelector("#drawer").classList.contains("translate-x-full")'));
  check('三组 API 设置', (await ev('return document.querySelectorAll("[data-api-group]").length')) === 3);
  await ev(`document.querySelector('[data-tab="usage"]').click(); return 1`);
  await sleep(400);
  check('用量标签', await ev('return document.querySelector("#drawerBody").textContent.includes("本月总花费")'));
  await ev(`document.querySelector('[data-tab="api"]').click(); return 1`);
  await sleep(300);
  await ev(`document.querySelector('[data-action="save-settings"]').click(); return 1`);
  await sleep(900);
  check('保存设置', await ev('return document.querySelector("#drawerSavedAt").textContent.includes("上次保存")'));
  await ev(`document.querySelector('#drawerMask').click(); return 1`);
  await sleep(400);

  // ---------- 切换器 ----------
  await ev(`document.querySelector('#switcherBtn').click(); return 1`);
  await sleep(400);
  check('切换器展开', await ev('return !document.querySelector("#switcherPanel").classList.contains("hidden")'));
  check('切换器列出项目', (await ev('return document.querySelectorAll("#recentList [data-action=\\"switch-project\\"]").length')) >= 2);
  await ev(`document.querySelector('#recentList [data-action="switch-project"]').click(); return 1`);
  await sleep(1200);
  check('切换项目后收起', await ev('return document.querySelector("#switcherPanel").classList.contains("hidden")'));

  // ---------- 对话 ----------
  await ev(`document.querySelector('#rail button[data-view="chat"]').click(); return 1`);
  await sleep(600);
  const msgBefore = (await state()).messages.length;
  await ev(`document.querySelector('#chatInput').value = '雨夜便利店门口，一个女人停下，电影感冷调'; return 1`);
  await ev(`document.querySelector('[data-action="chat-send"]').click(); return 1`);
  await sleep(1600);
  check('发送消息', (await state()).messages.length === msgBefore + 2);
  check('出现追问卡', await ev('return !!document.querySelector(\'[data-action="clarify-pick"][data-slot="role"]\')'));
  const shotsBeforeChat = (await state()).shots.length;
  for (const slot of ['role', 'scene', 'style']) {
    await ev(`document.querySelector('[data-action="clarify-pick"][data-slot="${slot}"][data-mode="auto"]').click(); return 1`);
    await sleep(350);
  }
  await sleep(1600);
  check('继续生成建镜头', (await state()).shots.length === shotsBeforeChat + 1);
  check('跳转到视频视图', await ev(`return !!document.querySelector('.view[data-view="video"].is-active')`));

  // ---------- 迁移 ----------
  await ev(`document.querySelector('#rail button[data-view="assets"]').click(); return 1`);
  await sleep(600);
  const projects = (await state()).projects;
  if (projects.length >= 2) {
    await ev(`document.querySelector('#assetGrid [data-action="asset-migrate"]').click(); return 1`);
    await sleep(900);
    check('迁移浮层打开', await ev('return !document.querySelector("#migrateModal").classList.contains("hidden")'));
    await ev(`document.querySelector('[data-action="migrate-mode"][data-id="move"]').click(); return 1`);
    await sleep(300);
    check('移动提示为危险色文案', await ev('return document.querySelector("#migrateModal").textContent.includes("移动会切断原项目的引用")'));
    const targets = await ev('return Array.from(document.querySelectorAll(\'[data-action="migrate-target"]\')).map(b => b.dataset.id)');
    if (targets.length) {
      await ev(`document.querySelector('[data-action="migrate-target"][data-id="${targets[0]}"]').click(); return 1`);
      await sleep(300);
    }
    await ev(`document.querySelector('[data-action="migrate-confirm"]').click(); return 1`);
    await sleep(1500);
    check('迁移完成并关闭', await ev('return document.querySelector("#migrateModal").classList.contains("hidden")'));
  } else {
    check('迁移浮层（跳过：只有一个项目）', true);
    await ev(`document.querySelector('#migrateMask') && 0; return 1`);
  }

  // ---------- 归档 / 恢复 ----------
  await ev(`document.querySelector('#rail button[data-view="manage"]').click(); return 1`);
  await sleep(600);
  const cur = (await state()).currentProject.projectId;
  await ev(`document.querySelector('[data-action="project-archive"][data-id="${cur}"]').click(); return 1`);
  await sleep(1200);
  check('归档当前项目', (await state()).projects.find((p) => p.id === cur).archived === true);
  await ev(`document.querySelector('[data-action="project-archive"][data-id="${cur}"]').click(); return 1`);
  await sleep(1200);
  check('恢复项目', (await state()).projects.find((p) => p.id === cur).archived === false);

  // ---------- 素材 / 导出 ----------
  await ev(`document.querySelector('#rail button[data-view="video"]').click(); return 1`);
  await sleep(600);
  await ev(`document.querySelector('[data-action="narration-add"]').click(); return 1`);
  await sleep(400);
  check('旁白弹窗', await ev('return !!document.querySelector("#mNarr")'));
  await ev(`document.querySelector('#mNarr').value = '今天雨太大了'; document.querySelector('[data-action="narration-save"]').click(); return 1`);
  await sleep(1200);
  check('旁白写入素材', await ev(`const d = (await (await fetch('/api/bootstrap')).json()).data; return d.materials.some(m => m.kind === '音频');`));

  check('导出清单', await ev(`const r = await fetch('/api/export/manifest'); return r.status === 200`));
  check('字幕文件', await ev(`const r = await fetch('/api/export/subtitles.srt'); const t = await r.text(); return r.status === 200 && t.includes('-->')`));

  // ---------- 汇总 ----------
  console.log('---');
  console.log('JS exceptions:', errors.length);
  errors.slice(0, 8).forEach((e) => console.log('  EXC', e.split('\n')[0]));
  console.log('console errors:', consoleErrors.length);
  consoleErrors.slice(0, 8).forEach((e) => console.log('  LOG', e));
  const failed = results.filter((r) => !r.ok);
  console.log(`FAILED: ${failed.length} / ${results.length}`);
  process.exit(failed.length || errors.length ? 1 : 0);
}

main().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
