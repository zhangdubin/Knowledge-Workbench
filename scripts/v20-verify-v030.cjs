/**
 * v0.3.0 端到端验证：回收站 / CSV 导入导出 / AI 助理
 *
 * 用法：KB_SESSION_TOKEN=xxx node scripts/v20-verify-v030.cjs
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs');

const FE = 'http://127.0.0.1:8082';
const TOKEN = process.env.KB_SESSION_TOKEN;
const SHOTS = '/tmp/kb-v030-shots';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
  ok ? pass++ : fail++;
};

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox', '--force-device-scale-factor=2'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 950, deviceScaleFactor: 2 });
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' });

  const api = (p, method = 'GET', body) => page.evaluate(async (p, method, body) => {
    const r = await fetch(p, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    return { status: r.status, json: await r.json().catch(() => null) };
  }, p, method, body);
  const snap = (n) => page.screenshot({ path: `${SHOTS}/${n}.png` });

  // ---------- 0. 造探测数据并软删 ----------
  console.log('\n[0] 造探测数据');
  await page.goto(`${FE}/#/system/recycle`, { waitUntil: 'domcontentloaded' });
  const created = await api('/api/entity-types', 'POST', {
    key: '__e2e_v030', name: 'E2E探测模型', icon: 'Document', description: '', app: 'default', order: 999,
    fields: [
      { key: 'name', name: '名称', type: 'text', required: true, options: {}, order: 1 },
      { key: 'amt', name: '金额', type: 'number', required: false, options: {}, order: 2 },
    ],
  });
  check('创建探测模型', created.status === 200, `id=${created.json?.id}`);
  const tid = created.json.id;
  await api(`/api/records/type/${tid}`, 'POST', { data: { name: '测试A', amt: 88 } });
  await api(`/api/records/type/${tid}`, 'POST', { data: { name: '测试B', amt: 12 } });
  const recs = await api(`/api/records/type/${tid}`);
  const rid = recs.json.items[0].id;

  // ---------- 1. 回收站页面 ----------
  console.log('\n[1] 回收站页面');
  await page.goto(`${FE}/#/system/recycle`, { waitUntil: 'networkidle2' });
  await sleep(800);
  await snap('01-recycle-empty');
  const hasMenu = await page.evaluate(() =>
    !!document.querySelector('.el-menu-item') &&
    [...document.querySelectorAll('.el-menu-item')].some(m => m.textContent.includes('回收站')));
  check('侧栏有回收站入口', hasMenu);

  // 软删模型 + 一条记录 → 回收站应出现
  await api(`/api/entity-types/${tid}`, 'DELETE');
  await api(`/api/records/${rid}`, 'DELETE');
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(800);
  const pageText = await page.evaluate(() => document.body.innerText);
  check('回收站列出已删模型', pageText.includes('E2E探测模型'));
  check('回收站列出已删记录', pageText.includes('测试A') || pageText.includes('测试B'));
  await snap('02-recycle-populated');

  // ---------- 2. 恢复记录 ----------
  console.log('\n[2] 恢复记录');
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.el-table__row')];
    const row = rows.find(r => r.textContent.includes('测试A') || r.textContent.includes('测试B'));
    if (row) [...row.querySelectorAll('button')].find(b => b.textContent.includes('恢复'))?.click();
  });
  await sleep(1000);
  const toast1 = await page.evaluate(() => document.body.innerText.includes('已恢复'));
  check('记录恢复成功提示', toast1);
  await page.reload({ waitUntil: 'networkidle2' }); await sleep(600);
  // 设计：恢复记录时若所属模型也在回收站，会连带恢复模型
  const modelBack = await page.evaluate(() => !document.body.innerText.includes('E2E探测模型'));
  check('恢复记录连带救回所属模型', modelBack);
  await snap('03-record-restored');

  // ---------- 3. 恢复模型 → 再删 → 彻底删除（输错 Key 拦截 + 正确 Key 放行） ----------
  console.log('\n[3] 模型恢复与彻底删除');
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.el-table__row')];
    const row = rows.find(r => r.textContent.includes('E2E探测模型'));
    if (row) [...row.querySelectorAll('button')].find(b => b.textContent.includes('恢复'))?.click();
  });
  await sleep(1000);
  // 模型回来了，再软删一次走彻底删除
  await api(`/api/entity-types/${tid}`, 'DELETE');
  await page.reload({ waitUntil: 'networkidle2' }); await sleep(700);
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.el-table__row')];
    const row = rows.find(r => r.textContent.includes('E2E探测模型'));
    if (row) [...row.querySelectorAll('button')].find(b => b.textContent.includes('彻底删除'))?.click();
  });
  await page.waitForSelector('.el-message-box', { timeout: 8000 });
  await sleep(400);
  await snap('04-purge-dialog');
  const inputSel = '.el-message-box__input input';
  await page.$eval(inputSel, el => { el.value = ''; el.focus(); });
  await page.keyboard.type('wrong-key');
  await page.evaluate(() => {
    [...document.querySelectorAll('.el-message-box__btns button')]
      .find(b => b.textContent.includes('彻底删除'))?.click();
  });
  await sleep(800);
  const blocked = await page.evaluate(() => !!document.querySelector('.el-message-box__errormsg'));
  check('输错 Key 被拦', blocked);
  await snap('05-purge-wrong-key');
  await page.$eval(inputSel, el => { el.value = ''; el.focus(); });
  await page.keyboard.type('__e2e_v030');
  await page.evaluate(() => {
    [...document.querySelectorAll('.el-message-box__btns button')]
      .find(b => b.textContent.includes('彻底删除'))?.click();
  });
  await sleep(1200);
  const gone = await api(`/api/entity-types/${tid}`);
  check('正确 Key 后物理删除（404=真删了）', gone.status === 404);
  await snap('06-purge-done');

  // ---------- 4. 记录页：导出按钮 + 导入对话框 ----------
  console.log('\n[4] CSV 导入导出 UI');
  const types = await api('/api/entity-types');
  const feiyong = types.json.find(t => t.key === 'feiyong');
  await page.goto(`${FE}/#/records/${feiyong.id}`, { waitUntil: 'networkidle2' });
  await sleep(700);
  const hasExport = await page.evaluate(() =>
    document.body.innerText.includes('导出 CSV') && document.body.innerText.includes('导入'));
  check('记录页有导出/导入按钮', hasExport);
  const before = (await api(`/api/records/type/${feiyong.id}`)).json.total;

  await page.evaluate(() =>
    [...document.querySelectorAll('button')].find(b => b.textContent.includes('导入'))?.click());
  await page.waitForSelector('.el-dialog', { timeout: 8000 });
  await sleep(300);
  await snap('07-import-dialog');
  await page.type('.el-dialog textarea', 'name,fylx,je,date,renyuan\nE2E导入的报销,差旅,66,2026-09-25,测试员');
  await page.evaluate(() =>
    [...document.querySelectorAll('.el-dialog button')].find(b => b.textContent.includes('开始导入'))?.click());
  await sleep(1500);
  const after = (await api(`/api/records/type/${feiyong.id}`)).json.total;
  check('CSV 导入成功 (+1)', after === before + 1, `${before} → ${after}`);
  const toastTxt = await page.evaluate(() =>
    [...document.querySelectorAll('.el-message')].map(e => e.textContent).join('/'));
  check('导入成功提示', toastTxt.includes('新增 1 条'), toastTxt);
  await snap('08-import-done');

  // 删掉刚才导入的（软删进回收站即可，不算脏数据……还是彻底清掉）
  const items = (await api(`/api/records/type/${feiyong.id}?page_size=100`)).json.items;
  const e2e = items.find(i => (i.data?.name || '').includes('E2E导入的报销'));
  if (e2e) {
    await api(`/api/records/${e2e.id}`, 'DELETE');
    await api(`/api/recycle/records/${e2e.id}`, 'DELETE');
  }

  // ---------- 5. AI 助理抽屉 ----------
  console.log('\n[5] AI 助理');
  await page.goto(`${FE}/#/`, { waitUntil: 'networkidle2' });
  await sleep(600);
  const btn = await page.$('.agent-btn');
  check('顶栏 AI 助理按钮', !!btn);
  await btn.click();
  await page.waitForSelector('.agent-drawer', { timeout: 8000 });
  await sleep(600);
  await snap('09-agent-drawer');
  const hasSuggest = await page.evaluate(() => document.body.innerText.includes('系统里现在有哪些数据模型'));
  check('欢迎页与快捷问题', hasSuggest);

  await page.type('.agent-input textarea', '费用管理模型里一共几条记录？');
  await page.evaluate(() =>
    [...document.querySelectorAll('.agent-drawer button')].find(b => b.textContent.includes('发送'))?.click());
  // 等回答（AI 可能要几十秒）
  await page.waitForFunction(
    () => !!document.querySelector('.agent-list .msg.assistant .msg-text')?.textContent,
    { timeout: 120000, polling: 1000 });
  await sleep(600);
  const ansText = await page.evaluate(() =>
    [...document.querySelectorAll('.agent-list .msg.assistant .msg-text')].map(e => e.textContent).join(''));
  check('AI 回答非空且不含思考链', ansText.length > 5 && !ansText.includes('好的，我'), ansText.slice(0, 60));
  const toolCards = await page.evaluate(() => document.querySelectorAll('.agent-drawer .tool-card').length);
  check('工具调用轨迹卡片', toolCards >= 1, `共 ${toolCards} 张`);
  await snap('10-agent-answer');
  // 展开工具详情
  await page.evaluate(() => document.querySelector('.agent-drawer .tool-head')?.click());
  await sleep(400);
  const toolBody = await page.evaluate(() => !!document.querySelector('.agent-drawer .tool-body'));
  check('工具详情可展开', toolBody);
  await snap('11-agent-tool-detail');

  console.log(`\n========== 结果：${pass} 通过 / ${fail} 失败 ==========`);
  console.log('截图目录:', SHOTS);
  await browser.close();
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('脚本异常:', e); process.exit(1); });
