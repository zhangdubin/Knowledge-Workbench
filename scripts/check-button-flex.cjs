/**
 * 静态检查：<button> 是不是被当成了 flex / grid 容器
 *
 * 为什么查这个：
 * Chrome 对 <button> 有个特殊处理 —— 它用的是**浏览器给按钮的固有高度**
 * （大约一行文字那么高），**不会**按内容撑开。
 * 所以把 <button> 设成 display:flex / grid 之后，
 * 内容会溢出到按钮外面，看起来就是「一行行文字互相叠着」。
 *
 * 踩过：RelationLinker 的「关联定义」每行三行内容（标题/方向/计数），
 * 按钮只有 28px 高、内容要 74px —— 一堆条目叠成一团（用户截图）。
 *
 * 正确做法：按钮只负责边框与点击，内容包一层普通元素用 flex/grid 排。
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..', 'frontend', 'src')

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (/\.(vue|js)$/.test(e.name)) out.push(full)
  }
  return out
}

const problems = []
for (const file of walk(ROOT)) {
  const src = fs.readFileSync(file, 'utf8')
  if (!src.endsWith('.vue')) continue

  // 模板里 <button class="xxx" …>
  const buttons = [...src.matchAll(/<button\b[^>]*class="([^"]+)"[^>]*>/g)].map(m => m[1].split(/\s+/))
  if (!buttons.length) continue

  // 样式块里的规则
  const styleBlocks = [...src.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n')
  if (!styleBlocks) continue

  for (const cls of buttons) {
    for (const c of cls) {
      if (!c || c.includes('{')) continue
      // 找 .c { … } 规则
      const re = new RegExp(`(?:^|[\\s,}])\\.${c.replace(/[-]/g, '\\-')}\\s*\\{([^}]*)\\}`, 'g')
      let m
      while ((m = re.exec(styleBlocks))) {
        const body = m[1]
        const disp = (body.match(/display\s*:\s*(flex|grid|inline-flex|inline-grid)/) || [])[1]
        if (disp) {
          const line = styleBlocks.slice(0, m.index).split('\n').length
          problems.push({ file: path.relative(ROOT, file), cls: c, disp, line })
        }
      }
    }
  }
}

// 同一份样式里可能有多处；按 file+cls 去重
const seen = new Set()
const uniq = problems.filter(p => {
  const k = p.file + '|' + p.cls + '|' + p.disp
  if (seen.has(k)) return false
  seen.add(k); return true
})

console.log(`扫了 ${walk(ROOT).length} 个文件`)
if (!uniq.length) {
  console.log('✅ 没有把 <button> 当 flex/grid 容器用的')
  process.exit(0)
}
console.log(`\n❌ ${uniq.length} 处 <button> 被当成 flex/grid 容器（内容会溢出按钮）：\n`)
for (const p of uniq) {
  console.log(`  ${p.file}:${p.line}  .${p.cls} → display:${p.disp}`)
  console.log(`     （按钮用浏览器给的固有高度，内容会叠到下一行）`)
}
process.exit(1)
