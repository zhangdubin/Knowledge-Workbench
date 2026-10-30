/**
 * 静态检查：.vue / .js 里用了没导入的标识符
 *
 * 为什么需要这个：
 * Vue 的 SFC 编译**不会**报「用了没定义的东西」。
 * 少了 `import { computed } from 'vue'`，页面照样编译、照样加载，
 * 只是那个组件一初始化就抛 ReferenceError ——
 * 于是「记录详情抽屉打开是空的」「关联面板不显示」，但控制台只有一条红字。
 *
 * 踩过：RecordRelationsPanel 用了 computed 却没 import，
 * 记录页与应用页的关联面板整个不渲染（而且只在**构建产物**里炸，
 * 开发服务器的热更新版本有时又能跑，排查绕了一圈）。
 *
 * 这个脚本扫一遍所有 .vue/.js：
 *   1. 找出用到但没 import / 没声明的标识符
 *   2. 排除 Vue 模板编译产物、局部变量、对象属性等误报
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.join(__dirname, '..', 'frontend', 'src')

// Vue / 浏览器 / Element Plus 的全局可用名（不需要 import）
const GLOBALS = new Set([
  'window', 'document', 'console', 'setTimeout', 'clearTimeout', 'setInterval',
  'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame', 'fetch',
  'localStorage', 'sessionStorage', 'navigator', 'location', 'history', 'alert',
  'confirm', 'prompt', 'URL', 'URLSearchParams', 'FormData', 'Blob', 'File',
  'Image', 'Event', 'CustomEvent', 'HTMLElement', 'Element', 'Node', 'JSON',
  'Math', 'Date', 'Array', 'Object', 'String', 'Number', 'Boolean', 'Symbol',
  'Promise', 'Map', 'Set', 'WeakMap', 'WeakSet', 'RegExp', 'Error', 'TypeError',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
  'decodeURIComponent', 'structuredClone', 'queueMicrotask', 'globalThis',
  'process', 'Buffer', '__dirname', '__filename', 'require', 'module',
  // Vue 编译宏（编译器会处理，不需要 import）
  'defineProps', 'defineEmits', 'defineExpose', 'defineOptions', 'defineModel',
  'withDefaults', 'defineSlots', 'withCtx', 'useSlots', 'useAttrs',
  // 浏览器/CSS 里常见的
  'getComputedStyle', 'matchMedia', 'requestIdleCallback', 'MutationObserver',
  'IntersectionObserver', 'ResizeObserver', 'CSS', 'Intl', 'Reflect', 'Proxy',
  'WeakRef', 'AggregateError', 'TextEncoder', 'TextDecoder', 'AbortController',
  'Infinity', 'NaN', 'undefined', 'null', 'true', 'false', 'this', 'arguments',
])

// JS 关键字与 CSS 函数 —— 不是「未声明的标识符」
const KEYWORDS = new Set([
  'if', 'for', 'while', 'do', 'switch', 'case', 'default', 'break', 'continue',
  'return', 'throw', 'try', 'catch', 'finally', 'new', 'delete', 'typeof',
  'instanceof', 'in', 'of', 'void', 'yield', 'await', 'async', 'function',
  'class', 'extends', 'super', 'this', 'import', 'export', 'from', 'as',
  'var', 'let', 'const', 'else', 'with', 'debugger', 'static', 'get', 'set',
  // CSS 函数（样式块里会出现）
  'min', 'max', 'clamp', 'calc', 'var', 'repeat', 'minmax', 'rgba', 'rgb',
  'hsl', 'hsla', 'url', 'attr', 'counter', 'linear-gradient', 'radial-gradient',
  'translate', 'translateX', 'translateY', 'scale', 'rotate', 'matrix',
  'not', 'and', 'or', 'only',
  // 样式里的伪类/伪元素函数与 CSS 新函数
  'media', 'supports', 'deep', 'slotted', 'global', 'mix', 'blend', 'light-dark',
  'color', 'hsl', 'hwb', 'lab', 'lch', 'oklab', 'oklch', 'if', 'steps', 'cubic-bezier',
])

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (/\.(vue|js|mjs)$/.test(entry.name)) out.push(full)
  }
  return out
}

/** 取 <script> / <script setup> 块里的代码（只看脚本，样式不是 JS） */
function scriptOf(src) {
  const blocks = []
  const re = /<script\b[^>]*>([\s\S]*?)<\/script>/g
  let m
  while ((m = re.exec(src))) blocks.push(m[1])
  // 脚本里可能还嵌着模板字符串（<template>…</template>）——
  // 那不是 JS，扫了只会误报
  let code = blocks.join('\n')
  code = code.replace(/<template\b[^>]*>[\s\S]*?<\/template>/g, ' ')
  // 整段 <style> 也去掉（万一被内嵌进了脚本字符串）
  code = code.replace(/<style\b[^>]*>[\s\S]*?<\/style>/g, ' ')
  return code
}

/** 取 import 进来的名字 + 顶层声明的名字 */
function declaredNames(code) {
  const names = new Set()
  // import { a, b as c } from '...'
  for (const m of code.matchAll(/import\s+(?:([\w$]+)\s*,\s*)?(?:\{([^}]*)\}|\*\s+as\s+([\w$]+)|([\w$]+))\s+from/g)) {
    if (m[1]) names.add(m[1])
    if (m[2]) {
      for (const part of m[2].split(',')) {
        const t = part.trim()
        if (!t) continue
        const as = t.split(/\s+as\s+/)
        names.add((as[1] || as[0]).trim())
      }
    }
    if (m[3]) names.add(m[3])
    if (m[4]) names.add(m[4])
  }
  // import '...'
  for (const m of code.matchAll(/import\s+['"][^'"]+['"]/g)) { /* 副作用导入，无绑定 */ }
  // const/let/var/function/class 声明
  for (const m of code.matchAll(/\b(?:const|let|var|function|class)\s+([\w$]+)/g)) names.add(m[1])
  // 解构声明：const { a, b } = ...
  for (const m of code.matchAll(/\b(?:const|let|var)\s*\{([^}]*)\}\s*=/g)) {
    for (const part of m[1].split(',')) {
      const t = part.trim()
      if (!t) continue
      const as = t.split(/[:=]/)
      names.add((as[1] || as[0]).split('=')[0].trim())
    }
  }
  // 函数参数（内层作用域的参数名也算「声明过」）
  for (const m of code.matchAll(/\(([^)]*)\)\s*(?:=>|\{)/g)) {
    for (const part of m[1].split(',')) {
      const t = part.split('=')[0].trim().replace(/^\.\.\./, '')
      if (/^[A-Za-z_$][\w$]*$/.test(t)) names.add(t)
    }
  }
  for (const m of code.matchAll(/([A-Za-z_$][\w$]*)\s*=>/g)) names.add(m[1])
  return names
}

/** 找出「像标识符的调用」—— 只认 `name(` 这种形式 */
function usedNames(code) {
  const used = new Map()
  // 排除：字符串里的、模板串里的、注释里的
  let clean = code
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\/\/[^\n]*/g, ' ')
    .replace(/`(?:\\.|[^`\\])*`/g, ' ')
    .replace(/'(?:\\.|[^'\\])*'/g, " '' ")
    .replace(/"(?:\\.|[^"\\])*"/g, ' "" ')
  // 正则字面量：/pattern/ —— 里面也可能有 name( 这种，会被误当成调用
  // （比如 /position (\d+)/ 会报「position 未定义」）
  clean = clean.replace(/\/(?![/*])(?:\\.|[^\/\\\n])+\/[gimsuy]*/g, ' RE ')
  const re = /(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(/g
  let m
  while ((m = re.exec(clean))) {
    const name = m[1]
    if (KEYWORDS.has(name)) continue
    if (!used.has(name)) used.set(name, clean.slice(Math.max(0, m.index - 60), m.index + name.length + 30).replace(/\n/g, ' '))
  }
  return used
}

const files = walk(ROOT)
const problems = []

for (const file of files) {
  const src = fs.readFileSync(file, 'utf8')
  // 注意：文件名要 trim —— 文件末尾有换行时 endsWith('.vue') 是 false，
  // 于是整份源码（含 <style>）都被当成 JS 扫，误报一堆 CSS 函数。
  const isVue = file.trimEnd().endsWith('.vue')
  const code = isVue ? scriptOf(src) : src
  if (!code.trim()) continue

  const declared = declaredNames(code)
  const used = usedNames(code)

  for (const [name, ctx] of used) {
    if (declared.has(name)) continue
    if (GLOBALS.has(name)) continue
    // 模板编译产物 / 组件名（首字母大写）不做检查
    if (/^[A-Z]/.test(name)) continue
    problems.push({ file: path.relative(ROOT, file), name, ctx })
  }
}

console.log(`扫了 ${files.length} 个文件`)
if (!problems.length) {
  console.log('✅ 没有「用了但没导入」的标识符')
  process.exit(0)
}

console.log(`\n❌ 发现 ${problems.length} 处可疑：\n`)
const seen = new Set()
for (const p of problems) {
  const key = p.file + ':' + p.name
  if (seen.has(key)) continue
  seen.add(key)
  console.log(`  ${p.file}  →  ${p.name}()`)
  console.log(`     ${p.ctx}`)
}
process.exit(1)
