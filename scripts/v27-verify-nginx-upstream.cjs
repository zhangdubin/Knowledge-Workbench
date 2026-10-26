#!/usr/bin/env node
/**
 * v0.4.1 回归：nginx 上游延迟解析（服务器上 "host not found in upstream" 的修复）
 *
 * 背景：nginx 在**加载配置时**一次性解析 upstream 主机名，解析不到就直接
 * [emerg] 退出。Docker Compose 里只要后端晚起来 / 被重建 / 临时停掉，
 * 前端容器就会陷入崩溃重启循环 —— 服务器上那串越来越长的重启间隔就是它。
 *
 * 本脚本验证四件事：
 *   1. 后端不可解析时，nginx 容器照样能正常启动（不再 [emerg] 退出）
 *   2. 后端不可达时，SPA 首页照常返回 200，/api 返回可解析的 JSON 503
 *   3. 后端起来后，接口自动恢复 200，前端全程零重启
 *   4. 后端容器重建（别名重注册、IP 可能变）后，接口自动恢复，前端零重启
 *
 * 用法：node scripts/v27-verify-nginx-upstream.cjs
 * 前置：docker 可用；会在 kb-workbench 栈上操作（结束时会恢复原状）
 */
const { execSync, spawn } = require('child_process');

const BACKEND = process.env.KB_BACKEND_CONTAINER || 'kb-backend';
const FRONTEND = process.env.KB_FRONTEND_CONTAINER || 'kb-frontend';
const FE_PORT = process.env.KB_FRONTEND_PORT || '8082';
const PROBE = 'kb-nginx-upstream-probe';
const TEST_PORT = 18098;

let pass = 0, fail = 0;
const ok = (m) => { pass++; console.log(`✅ ${m}`); };
const bad = (m) => { fail++; console.log(`❌ ${m}`); };
const check = (cond, m) => (cond ? ok(m) : bad(m));

const sh = (cmd) => execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function containerRunning(name) {
  try {
    return sh(`docker inspect -f '{{.State.Running}}' ${name}`) === 'true';
  } catch { return false; }
}
function restartCount(name) {
  try { return Number(sh(`docker inspect -f '{{.RestartCount}}' ${name}`)); } catch { return -1; }
}
async function http(path) {
  try {
    const r = await fetch(`http://127.0.0.1:${FE_PORT}${path}`, { redirect: 'manual' });
    const text = await r.text();
    return { status: r.status, text, json: (() => { try { return JSON.parse(text); } catch { return null; } })() };
  } catch (e) {
    return { status: 0, text: String(e.message), json: null };
  }
}

(async () => {
  console.log('=== v0.4.1 回归：nginx 上游延迟解析 ===\n');

  // ---------- 场景 1：后端完全不可解析时，nginx 能否启动 ----------
  console.log('--- 1. 后端不可解析时 nginx 仍能启动 ---');
  let probeId = null;
  try {
    sh(`docker rm -f ${PROBE} >/dev/null 2>&1`);
    probeId = sh(`docker run -d --name ${PROBE} -p ${TEST_PORT}:80 kb-workbench-frontend:latest`).split('\n').pop();
    await sleep(4);
    const running = containerRunning(PROBE);
    check(running, `独立容器（无后端可解析）启动成功：running=${running}`);
    const logs = sh(`docker logs ${PROBE} 2>&1 || true`);
    check(!/host not found in upstream/i.test(logs), '启动日志里没有 "host not found in upstream"');
    check(!/\[emerg\]/i.test(logs), '启动日志里没有 [emerg] 致命错误');

    // 场景 2：后端不可达时的降级行为
    const spa = await (async () => {
      const r = await fetch(`http://127.0.0.1:${TEST_PORT}/`);
      return r.status;
    })();
    check(spa === 200, `后端不可达时 SPA 首页仍然 200（实际 ${spa}）`);

    const api = await (async () => {
      const r = await fetch(`http://127.0.0.1:${TEST_PORT}/api/health`);
      const t = await r.text();
      let j = null; try { j = JSON.parse(t); } catch {}
      return { status: r.status, type: r.headers.get('content-type'), json: j, text: t };
    })();
    check(api.status === 503, `后端不可达时 /api 返回 503（实际 ${api.status}）`);
    check(!!api.json && api.json.ok === false, '503 响应体是合法 JSON 且 ok=false');
    check((api.type || '').includes('application/json'), `503 响应 Content-Type 是 JSON（实际 ${api.type}）`);
    check(!/<html/i.test(api.text), '503 响应不是 nginx 默认的 HTML 错误页');
  } catch (e) {
    bad(`场景 1/2 执行异常：${e.message}`);
  } finally {
    try { sh(`docker rm -f ${PROBE} >/dev/null 2>&1`); } catch {}
  }

  // ---------- 场景 3：真实栈 —— 后端断开 / 恢复 / 重建 ----------
  console.log('\n--- 2. 真实栈：后端断开与自动恢复 ---');
  const feRestartsBefore = restartCount(FRONTEND);

  try {
    sh(`docker stop ${BACKEND} >/dev/null 2>&1`);
    await sleep(4);
    const down = await http('/api/health');
    check(down.status === 503, `后端停掉后 /api 返回 503（实际 ${down.status}）`);
    check(!!down.json && down.json.ok === false, '后端停掉后 /api 仍是可解析的 JSON');
    const spaDown = await http('/');
    check(spaDown.status === 200, `后端停掉后 SPA 首页仍 200（实际 ${spaDown.status}）`);
    check(containerRunning(FRONTEND), '后端停掉期间前端容器仍在运行（没有崩溃重启）');

    // 场景 4：后端起来 → 自动恢复
    sh(`docker start ${BACKEND} >/dev/null 2>&1`);
    let up = { status: 0 };
    for (let i = 0; i < 20; i++) {
      await sleep(3000);
      up = await http('/api/health');
      if (up.status === 200) break;
    }
    check(up.status === 200, `后端恢复后接口自动回到 200（实际 ${up.status}）`);
    check(restartCount(FRONTEND) === feRestartsBefore, '整个过程前端容器零重启（未出现崩溃循环）');

    // 场景 5：后端容器重建（别名重注册、IP 可能变化）
    console.log('\n--- 3. 后端容器重建后的自动恢复 ---');
    sh(`docker compose up -d --force-recreate ${BACKEND} >/dev/null 2>&1 || docker compose up -d --force-recreate backend >/dev/null 2>&1`);
    let rec = { status: 0 };
    for (let i = 0; i < 20; i++) {
      await sleep(3000);
      rec = await http('/api/health');
      if (rec.status === 200) break;
    }
    check(rec.status === 200, `后端重建后接口自动恢复 200（实际 ${rec.status}）`);
    check(restartCount(FRONTEND) === feRestartsBefore, '后端重建全程前端零重启');
  } catch (e) {
    bad(`真实栈验证异常：${e.message}`);
  }

  console.log(`\n共 ${pass + fail} 项，${pass} 项通过，${fail} 项失败`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('异常：', e); process.exit(1); });
