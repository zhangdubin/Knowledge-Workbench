/**
 * Element Plus 命令式组件的样式与文案 —— 防止「确认框透明」再犯
 *
 * 背景（真踩过）：
 *   vite.config.js 里的 ElementPlusResolver 是**扫模板**的：
 *   模板里写了 <el-xxx> 才把它的样式带进包。
 *   而 ElMessage / ElMessageBox 是命令式调用，模板里一个都没有 ——
 *   扫不到，样式就不进包。
 *   结果是 .el-message-box 身上一条 background 规则都没有，
 *   确认框成了一块**透明**浮层，字飘在灰色遮罩上，完全看不清。
 *   ElMessage 的提示条则没有 fixed 定位、没有图标样式，顶在正文里跑。
 *
 * 为什么单测守着它：
 *   这种问题功能上完全正常（弹窗照样弹），只是「看不见」，
 *   靠人工点才发现得了 —— 而大多数时候没人去点每一个弹窗。
 *   样式是从别处漏进来的，光靠代码审查看不出来，得有断言守着。
 *
 * 这里断言的是**源码**：引了哪些样式、写了哪些规则。
 * 真要确认样式确实进了产物，看 scripts/verify-ep-imperative-styles.py
 * （它读 dist/ 里的 CSS）。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p) => readFileSync(join(ROOT, p), 'utf8')

let n = 0
const ok = (v, msg) => { assert.ok(v, msg); n++ }

const main = read('src/main.js')
const css = read('src/styles/main.css')

// ---------- 命令式组件的样式必须显式引入 ----------
for (const cssFile of ['el-message.css', 'el-message-box.css']) {
  ok(
    main.includes('element-plus/theme-chalk/' + cssFile),
    'main.js 显式引入了 ' + cssFile + '（扫模板扫不到命令式组件）'
  )
}

// ---------- 确认框必须有底色 ----------
const boxRule = css.match(/\.el-message-box\s*\{[^}]*\}/g) || []
ok(boxRule.length > 0, 'main.css 里有 .el-message-box 规则')
ok(
  boxRule.some(r => /background(-color)?\s*:/.test(r)),
  '.el-message-box 显式写了底色（样式没进包时也不会变透明）'
)
ok(
  boxRule.some(r => /background(-color)?\s*:[^;]*var\(--el-bg-color-overlay\)/.test(r)),
  '底色走 --el-bg-color-overlay（跟着明暗主题走）'
)

// ---------- 提示条同理 ----------
const msgRule = css.match(/\.el-message\s*\{[^}]*\}/g) || []
ok(msgRule.length > 0, 'main.css 里有 .el-message 规则')
ok(
  msgRule.some(r => /background(-color)?\s*:/.test(r)),
  '.el-message 显式写了底色'
)

// ---------- 弹窗按钮文案统一中文 ----------
ok(main.includes("utils/feedback.js"), 'main.js 引入了 utils/feedback.js')
const fb = read('src/utils/feedback.js')
for (const m of ['confirm', 'alert', 'prompt']) {
  ok(fb.includes("'" + m + "'"), 'feedback.js 给 ' + m + ' 兜了中文按钮文案')
}
ok(
  fb.includes("confirmButtonText: '确定'") && fb.includes("cancelButtonText: '取消'"),
  '默认按钮文案是「确定 / 取消」'
)
ok(
  /\.\.\.options/.test(fb),
  '调用点显式传了按钮文案时仍然以它为准（...options 在后）'
)

console.log('✅ Element Plus 命令式组件的样式与文案 —— 全部通过（' + n + ' 项断言）')
