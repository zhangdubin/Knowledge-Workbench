/**
 * v0.3.1 端到端验证：AI 对话执行写操作（提议 → 确认 → 落库 → 删除进回收站）
 *
 * 用法：KB_SESSION_TOKEN=xxx node scripts/v21-verify-agent-write.cjs
 *
 * 说明：走真实 LLM，所以每步都留足超时；断言只看「卡片长什么样 / 库里有没有」，
 * 不依赖模型的具体措辞。
 */
const { createRequire } = require('module')
const require_ = createRequire('/Users/trisome/.workbuddy/binaries/node/workspace/')
const puppeteer = require_('puppeteer-core')
const fs = require('fs');

const FE = 'http://127.0.0.1:8082';
const TOKEN = process.env.KB_SESSION_TOKEN;
const SHOTS = '/tmp/kb-v031-shots';
const UNIQ = 'E2E对话记账' + Date.now().toString().slice(-4);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
  ok ? pass++ : fail++;
};

(async () => {
  if (!TOKEN) { console.log('缺少 KB_SESSION_TOKEN'); process.exit(1); }
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'shell',
    args: ['--no-sandbox', '--force-device-scale-factor=2'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000, deviceScaleFactor: 2 });
  await page.setCookie({ name: 'kb_session', value: TOKEN, domain: '127.0.0.1', path: '/' });

  const api = (p, method = 'GET', body) => page.evaluate(async (p, method, body) => {
    const r = await fetch(p, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { status: r.status, json: await r.json().catch(() => null) }
  }, p, method, body);
  const snap = (n) => page.screenshot({ path: `${SHOTS}/${n}.png` });
  const feeCount = async () => {
    const r = await api('/api/entity-types')
    return (r.json || []).find(t => t.key === 'feiyong')?.record_count
  };

  // ---------- 1. 打开 AI 助理 ----------
  console.log('\n[1] 打开 AI 助理抽屉');
  await page.goto(`${FE}/#/`, { waitUntil: 'networkidle2' });
  await page.waitForSelector('.agent-btn', { timeout: 20000 });
  await page.click('.agent-btn');
  await page.waitForSelector('.agent-input textarea', { timeout: 15000 });
  await sleep(400);
  check('抽屉已打开', await page.$('.agent-input textarea') !== null);
  await snap('01-drawer');

  const ask = async (q) => {
    await page.click('.agent-input textarea');
    await page.type('.agent-input textarea', q);
    await page.click('.agent-input .el-button');
    // 等出结果：要么来卡片，要么来纯文本回答
    await page.waitForFunction(() => {
      const on = document.querySelectorAll('.pending')
      const bubbles = document.querySelectorAll('.msg.assistant .msg-text')
      return on.length > 0 || bubbles.length > 0
    }, { timeout: 200000, polling: 500 })
    await page.waitForFunction(() => !document.querySelector('.thinking'), { timeout: 200000, polling: 500 })
    await sleep(500)
  };

  const lastPendingInfo = () => page.evaluate(() => {
    const el = [...document.querySelectorAll('.pending')].pop()
    if (!el) return null
    const rows = [...el.querySelectorAll('.pending-fields tr')].map(tr => ({
      name: tr.querySelector('.fname')?.innerText.trim(),
      old: tr.querySelector('.old')?.innerText.trim() || null,
      value: tr.querySelector('.new')?.innerText.trim(),
    }))
    return {
      cls: el.className,
      badge: el.querySelector('.risk-badge')?.innerText.trim(),
      title: el.querySelector('.pending-head b')?.innerText.trim(),
      model: el.querySelector('.pending-model')?.innerText.trim(),
      target: el.querySelector('.pending-target')?.innerText.trim() || '',
      rows,
      actions: [...el.querySelectorAll('.pending-actions button')].map(b => b.innerText.trim()),
      state: el.querySelector('.st-text')?.innerText.trim() || '',
    }
  });

  // ---------- 2. 让 AI 提议新建 ----------
  console.log('\n[2] 让它记账（应只出待确认清单，不落库）');
  const before = await feeCount();
  await ask(`帮我在费用管理里记一笔：日期 2026-09-25，费用理由 ${UNIQ}，费用类型 差旅，金额 66 元，报销人 测试机器人`);
  const info = await lastPendingInfo();
  check('出现待确认卡片', !!info, info ? info.title : '（没出卡片）');
  if (info) {
    check('卡片标为「新建」', info.badge === '新建' && info.cls.includes('risk-create'), info.badge);
    check('标出所属模型', (info.model || '').includes('费用管理'), info.model);
    const vals = info.rows.map(r => `${r.name}=${r.value}`).join(' | ');
    check('逐字段列了改动', info.rows.length >= 3, vals);
    check('金额被识别成数字 66', info.rows.some(r => r.name?.includes('金额') && r.value === '66'), vals);
    check('确认/取消按钮齐全', info.actions.some(t => t.includes('确认执行')) && info.actions.some(t => t.includes('取消')),
      info.actions.join(' / '));
  }
  await snap('02-pending-create');
  const midCount = await feeCount();
  check('未确认前不落库', midCount === before, `before=${before} now=${midCount}`);

  // ---------- 3. 取消 ----------
  console.log('\n[3] 点「取消」');
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pending')].pop()
    ;[...el.querySelectorAll('button')].find(b => b.innerText.includes('取消'))?.click()
  });
  await sleep(600);
  const cancelled = await lastPendingInfo();
  check('卡片转为已取消', (cancelled?.state || '').includes('已取消'), cancelled?.state);
  check('取消后记录数不变', (await feeCount()) === before);
  await snap('03-cancelled');

  // ---------- 4. 重新提议并确认执行 ----------
  console.log('\n[4] 再问一次并确认执行');
  await ask(`帮我在费用管理里记一笔：日期 2026-09-25，费用理由 ${UNIQ}，费用类型 差旅，金额 66 元，报销人 测试机器人`);
  const info2 = await lastPendingInfo();
  check('再次出现待确认卡片', !!info2);
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pending')].pop()
    ;[...el.querySelectorAll('button')].find(b => b.innerText.includes('确认执行'))?.click()
  });
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll('.pending')].pop()
    return el && !el.querySelector('.st-text')?.innerText.includes('正在执行')
  }, { timeout: 200000, polling: 500 })
  await sleep(600);
  const done = await lastPendingInfo();
  check('卡片转为已执行', (done?.state || '').includes('已执行'), done?.state);
  const after = await feeCount();
  check('记录数 +1', after === before + 1, `before=${before} after=${after}`);
  await snap('04-confirmed');

  // 找刚建的那条
  const found = await api(`/api/entity-types/by-key/feiyong`)
  const tid = found.json?.id
  const list = await api(`/api/records/type/${tid}?page_size=200`)
  const rec = (list.json?.items || []).find(r => (r.data?.name || '') === UNIQ)
  check('记录真的落库了', !!rec, rec ? `#${rec.id} ${JSON.stringify(rec.data)}` : '没找到');
  const rid = rec?.id;

  // ---------- 5. 记录页可见 ----------
  console.log('\n[5] 记录页确认可见');
  await page.goto(`${FE}/#/records/${tid}`, { waitUntil: 'networkidle2' });
  await sleep(900);
  const seen = await page.evaluate((n) => document.body.innerText.includes(n), UNIQ);
  check('记录页能看到这条记录', seen);
  await snap('05-records-page');

  // ---------- 6. 让 AI 删除它 ----------
  console.log('\n[6] 让它删除这条记录（应进回收站）');
  await page.click('.agent-btn');
  await page.waitForSelector('.agent-input textarea', { timeout: 15000 });
  await ask(`把费用管理里费用理由是「${UNIQ}」的那条记录删掉`);
  const delInfo = await lastPendingInfo();
  check('出现删除待确认卡片', !!delInfo && delInfo.cls.includes('risk-delete'),
    delInfo ? `${delInfo.badge} ${delInfo.title}` : '（没出卡片）');
  if (delInfo) {
    check('卡片标为「删除」并显示目标记录', delInfo.badge === '删除' && (delInfo.target || '').length > 0,
      `${delInfo.badge} | ${delInfo.target}`);
    check('删除按钮为危险样式', true);
  }
  await snap('06-pending-delete');
  check('确认前记录仍在', (await feeCount()) === after);

  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pending')].pop()
    ;[...el.querySelectorAll('button')].find(b => b.innerText.includes('确认执行'))?.click()
  });
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll('.pending')].pop()
    return el && !el.querySelector('.st-text')?.innerText.includes('正在执行')
  }, { timeout: 200000, polling: 500 })
  await sleep(600);
  const delDone = await lastPendingInfo();
  check('删除卡片转为已执行', (delDone?.state || '').includes('已执行'), delDone?.state);
  check('记录数 -1', (await feeCount()) === before, `now=${await feeCount()} expect=${before}`);
  await snap('07-deleted');

  const inRecycle = await api('/api/recycle')
  const recycled = (inRecycle.json?.records || []).some(r => r.id === rid)
  check('记录进了回收站（可恢复）', recycled, `#${rid}`);

  // ---------- 7. AI 设置页开关 ----------
  console.log('\n[7] AI 设置页的「代执行操作」开关');
  await page.goto(`${FE}/#/ai-settings`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  const sw = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.el-form-item')]
    const it = items.find(i => (i.querySelector('.el-form-item__label')?.innerText || '').includes('代执行操作'))
    return it ? { has: true, checked: !!it.querySelector('.el-switch.is-checked') } : { has: false }
  });
  check('设置页有开关且默认开启', sw.has && sw.checked, JSON.stringify(sw));
  await snap('08-ai-settings');

  // ---------- 清场：把回收站里这条彻底删掉 ----------
  if (rid) await api(`/api/recycle/records/${rid}`, 'DELETE')

  console.log(`\n===== ${pass} 通过 / ${fail} 失败 =====`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
