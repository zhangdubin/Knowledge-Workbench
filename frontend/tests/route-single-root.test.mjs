/**
 * 路由组件必须是「单根」—— 空白页事故的回归测试
 *
 * 为什么要有这个测试：
 *   Vue 的 <Transition mode="out-in"> 在切换路由时，
 *   会先等旧组件的 leave 结束，再挂新组件。
 *   而 leave 结束回调（afterLeave）**只在子节点是元素时才会被调用** ——
 *   子节点如果是 Fragment（多根），Vue 的 remove() 会直接 return，
 *   根本不会去调 afterLeave。
 *   结果：旧组件永远处于「正在离场」的状态，新组件永远不挂载 ——
 *   页面就是一个空的 <!---->，刷新才好。
 *
 *   什么时候会出现多根：
 *   模板里根节点前面有一行注释 <!-- xxx --> 时，
 *   编译期会把「注释 + 根元素」当成两个根节点（Fragment）。
 *   开发模式保留注释（comments: true），生产模式会去掉 ——
 *   所以这个 bug **只在开发模式出现**，生产构建是好的，
 *   非常容易被误判成「本地环境的问题」。
 *
 * 怎么判定「多根」：
 *   不能靠正则数标签（根元素内部的注释无害），
 *   必须真的编译一遍，数编译产物 AST 的 children 长度。
 *
 * 判定范围：
 *   只查**路由组件**（router/index.js 里挂上去的那些）。
 *   普通子组件多根没有 router-transition 的风险，不在这里管。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(HERE, '..', 'src')
const ROOT = resolve(HERE, '..')

let failed = 0
const ok = (cond, tag, extra) => {
  if (cond) console.log('✅ ' + tag + (extra ? ' → ' + extra : ''))
  else { console.log('❌ ' + tag + (extra ? ' → ' + extra : '')); failed++ }
}

// @vue/compiler-sfc 在 frontend/node_modules 下
const { parse, compileTemplate } = require('@vue/compiler-sfc')

/** 递归找出 src 下所有 .vue 文件 */
function vueFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) vueFiles(p, out)
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

/**
 * 数一个 .vue 模板编译出来的根节点个数
 * 返回 { roots, hasComment } —— roots > 1 就是多根
 */
function rootCount(file) {
  const src = readFileSync(file, 'utf8')
  const { descriptor, errors } = parse(src, { filename: file })
  if (errors && errors.length) {
    // 解析本身出错不算这个测试要管的事，但得说清楚，不能默默跳过
    return { roots: -1, error: String(errors[0]) }
  }
  if (!descriptor.template) return { roots: 0, error: '' }
  const res = compileTemplate({
    source: descriptor.template.content,
    filename: file,
    // 跟开发模式的编译选项对齐：开发模式保留注释
    compilerOptions: { comments: true },
  })
  if (res.errors && res.errors.length) {
    return { roots: -1, error: String(res.errors[0]) }
  }
  const ast = res.ast
  const children = (ast && ast.children) || []
  // 注释节点本身也算一个根 —— 它正是「多根」的来源
  return { roots: children.length, error: '' }
}

/** 从 router/index.js 里取出所有路由组件对应的 .vue 路径 */
function routeComponentFiles() {
  const routerFile = join(SRC, 'router', 'index.js')
  const code = readFileSync(routerFile, 'utf8')
  const files = new Set()
  // 形如 component: () => import('../views/DnaView.vue')
  // 正则里的反斜杠在写文件时容易被吞掉，所以用 RegExp 构造器写出来
  const re = new RegExp("import\\(\\s*['\"]([^'\"]+\\.vue)['\"]\\s*\\)", 'g')
  let m
  while ((m = re.exec(code))) {
    const rel = m[1].replace('..' + '/', '')
    files.add(join(SRC, rel))
  }
  return [...files]
}

console.log('—— 路由组件必须是单根（否则路由切换会白屏）——')

const routes = routeComponentFiles()
ok(routes.length > 0, '从 router/index.js 里解析出了路由组件', routes.length + ' 个')

const multi = []
const broken = []
for (const f of routes) {
  const { roots, error } = rootCount(f)
  if (roots === -1) { broken.push(f + ' → ' + error); continue }
  if (roots > 1) multi.push(f + ' → ' + roots + ' 个根节点')
}

ok(broken.length === 0, '所有路由组件都能正常编译',
  broken.length ? broken.join(' | ') : '全部通过')
ok(multi.length === 0, '所有路由组件都是单根',
  multi.length ? multi.join(' | ') : '全部通过')

// 全量体检：非路由组件多根只提示，不失败 ——
// 它们不进 router-transition，危害小得多，但值得知道。
const all = vueFiles(SRC)
const nonRoute = []
for (const f of all) {
  if (routes.includes(f)) continue
  const { roots } = rootCount(f)
  if (roots > 1) nonRoute.push(f.replace(ROOT + '/', ''))
}
console.log('ℹ️  非路由组件里还有 ' + nonRoute.length + ' 个是多根（不致命，不进路由过渡）：')
for (const f of nonRoute) console.log('    · ' + f)

if (failed) {
  console.log('\n❌ 有 ' + failed + ' 项没通过')
  process.exit(1)
}
console.log('\n✅ 全部通过')
