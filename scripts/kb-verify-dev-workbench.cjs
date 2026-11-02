/**
 * 软件开发工作台 · 浏览器级验收
 *
 * 为什么 API 级验证还不够：
 *   API 通过 ≠ 用户看得见。进度条是不是真的在动、
 *   阶段导航是不是把「卡在哪、为什么卡」说清楚了、
 *   澄清表单答不完是不是真的不让提交 —— 这些只有真浏览器能验。
 *
 * 用法：node scripts/kb-verify-dev-workbench.cjs
 */
const puppeteer = require('/Users/trisome/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')
const path = require('path')
const { execFileSync } = require('child_process')

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const BASE = process.env.BASE || 'http://127.0.0.1:8082'
const ROOT = path.resolve(__dirname, '..')
const sleep = ms => new Promise(r => setTimeout(r, ms))

const errors = []
const checks = []
function check(name, cond, detail) {
  checks.push({ name, ok: !!cond, detail: detail || "" })
  console.log(`  ${cond ? "✓" : "✗"} ${name}${cond ? "" : "  ← " + (detail || "")}`)
}

function sessionToken() {
  return execFileSync("python3", [path.join(__dirname, "kb-session-token.py")],
    { encoding: "utf8", cwd: ROOT }).trim()
}

async function api(pathname, opts) {
  const res = await fetch("http://127.0.0.1:8001" + pathname, {
    ...(opts || {}),
    headers: { "Cookie": "kb_session=" + sessionToken(), "Content-Type": "application/json" },
  })
  const ct = res.headers.get("content-type") || ""
  const body = ct.includes("json") ? await res.json() : await res.arrayBuffer()
  return { status: res.status, body, ct }
}

async function createProject() {
  const res = await api("/api/dev/projects", {
    method: "POST",
    body: JSON.stringify({
      name: "工作台验收-" + Date.now(),
      goal: "做一个内部工单统计后台：录入工单、按人按周统计、超期提醒、导出 CSV。",
      tech_stack: ["Python", "FastAPI", "SQLite"],
      tech_notes: "团队熟悉 Python，数据量小",
      mode: "online",
    }),
  })
  return res.body.project.id
}

async function waitStage(id, stage, want, timeoutMs) {
  const t0 = Date.now()
  while (Date.now() - t0 < (timeoutMs || 900000)) {
    const res = await api("/api/dev/projects/" + id + "/pipeline")
    const st = (res.body.pipeline.stages || {})[stage] || {}
    if (want === "done" && st.status === "done") return true
    if (want === "failed" && (st.status === "failed" || st.status === "done")) return true
    await sleep(4000)
  }
  return false
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  })
  const page = await browser.newPage()
  const token = sessionToken()
  await browser.setCookie(
    { name: "kb_session", value: token, domain: "127.0.0.1", path: "/" },
    { name: "kb_session", value: token, domain: "localhost", path: "/" },
  )
  await page.setViewport({ width: 1600, height: 950 })
  const consoleErrors = []
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()) })
  page.on("pageerror", e => consoleErrors.push("pageerror: " + e.message))

  console.log("\n▶  建项目")
  // 复用已有项目（PROJECT_ID）时跳过建项目与跑阶段 ——
  // 每次跑都要几分钟（真模型），调试脚本时很有用
  const reuse = process.env.PROJECT_ID
  const pid = reuse ? Number(reuse) : await createProject()
  console.log("  项目 id =", pid, reuse ? "（复用）" : "")

  console.log("\n▶  打开工作台")
  await page.goto(BASE + "/#/dev/" + pid, { waitUntil: "networkidle2" })
  await sleep(4000)

  const nav = await page.evaluate(() => {
    const items = [...document.querySelectorAll(".stage-item")]
    return items.map(el => ({
      text: el.innerText.replace(/\s+/g, " ").trim(),
      cls: el.className,
    }))
  })
  check("左栏渲染出四个阶段", nav.length === 4, "实际 " + nav.length + " 个")
  check("四个阶段名字齐全",
    ["需求理解", "需求补全", "需求转化", "项目生成"].every(n =>
      nav.some(x => x.text.includes(n))),
    JSON.stringify(nav.map(x => x.text.slice(0, 20))))
  const gateText = nav.map(x => x.text).join(" | ")
  check("没做的阶段写清了为什么卡住", /还没|先回答|先完成/.test(gateText), gateText.slice(0, 160))

  console.log("\n▶  跑「需求理解」，盯进度条")
  if (reuse) {
    console.log("  （复用项目，跳过运行阶段）")
  } else {
  const clicked = await page.evaluate(() => {
    // 只认**主按钮**（.el-button--primary），别点左栏的阶段导航按钮
    // —— 阶段名里也含「需求理解」，点到它只会切面板，不会真的跑。
    const btns = [...document.querySelectorAll("button.el-button--primary")]
    const b = btns.find(x => /开始理解|理解需求|生成|运行/.test(x.innerText))
    if (b) { b.click(); return b.innerText.trim() }
    return null
  })
  check("点得到「需求理解」的运行按钮", !!clicked, "没找到按钮")

  const seen = new Set()
  const percents = []
  for (let i = 0; i < 180; i++) {
    const st = await page.evaluate(() => {
      const bar = document.querySelector(".el-progress")
      const txt = bar ? (bar.querySelector(".el-progress__text") || {}).innerText : null
      const inner = bar ? bar.querySelector(".el-progress-bar__inner") : null
      const jobText = document.querySelector(".ws-progress-note, .job-text")
      return {
        percent: txt ? txt.trim() : null,
        width: inner ? inner.style.width : null,
        note: jobText ? jobText.innerText.replace(/\s+/g, " ").trim() : "",
      }
    })
    if (st.percent) { seen.add(st.percent); percents.push(st.percent) }
    if (st.percent === "100%") break
    await sleep(2000)
  }
  check("进度条出现过真实百分比", seen.size >= 1, [...seen].join(","))
  check("进度条**没有**停在假的 50%",
    percents.length === 0 || percents[percents.length - 1] !== "50%" || seen.size > 1,
    "采样到的百分比: " + [...seen].join(","))
  console.log("  采样到的百分比序列:", [...seen].join(" → "))
  }

  console.log("\n▶  阶段跑完后，界面应该有澄清问题表单")
  await sleep(6000)
  const clarify = await page.evaluate(() => {
    const radios = document.querySelectorAll(".el-radio, .el-radio-group label, .answer-opt")
    const textarea = document.querySelectorAll("textarea")
    // 只认面板底部的提交按钮（.panel-foot）：
    // 左栏阶段导航的按钮文本里也带「回答」（如「有 8 个问题待回答」），
    // 全局 find 会抓到它 —— 抓到它就永远测不到真正的提交按钮。
    const foot = document.querySelector(".panel-foot")
    const submit = foot
      ? [...foot.querySelectorAll("button")].find(b => /提交/.test(b.innerText))
      : null
    return {
      radioCount: radios.length,
      textareaCount: textarea.length,
      submitText: submit ? submit.innerText.trim() : null,
      submitDisabled: submit ? !!submit.disabled : null,
      bodyText: document.body.innerText.replace(/\s+/g, " ").slice(0, 400),
    }
  })
  check("澄清问题渲染成可作答的表单",
    clarify.radioCount > 0 || clarify.textareaCount > 0,
    JSON.stringify({ r: clarify.radioCount, t: clarify.textareaCount }))
  check("没答完不许提交", clarify.submitDisabled === true,
    "提交按钮 disabled=" + clarify.submitDisabled)

  console.log("\n▶  控制台")
  check("页面没有 JS 报错", consoleErrors.length === 0,
    consoleErrors.slice(0, 3).join(" / "))

  await browser.close()

  console.log("")
  const bad = checks.filter(c => !c.ok)
  if (bad.length) {
    console.log(`✗ ${bad.length} 项不通过（共 ${checks.length} 项）：`)
    bad.forEach(b => console.log("   - " + b.name + (b.detail ? "：" + b.detail : "")))
    process.exit(1)
  }
  console.log(`✓ 全部 ${checks.length} 项检查通过`)
})().catch(e => { console.error("脚本异常：", e); process.exit(1) })
