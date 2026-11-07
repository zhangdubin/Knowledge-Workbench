// 左侧导航的「分组合并」纯函数断言
// 覆盖 composables/useNavItems.js：
//   permForPath(path)              —— 自定义项指向受控页面时该按哪个权限位过滤
//   mergeNavGroups(内置, 自定义, canPage) —— 自定义项怎么并进内置分组
//
// 为什么值得单测：
//   侧边栏的可见性直接由这两个函数决定。
//   合并规则一旦写错，后果全是「静默」的：
//   组名对不上 → 自定义项凭空消失；
//   权限位算错 → 普通用户看见一个点进去就 403 的入口；
//   同路径没去重 → 同一个页面在侧栏里出现两次。
//   这些都不会报错，功能测试也照样通过，只有断言守着才拦得住。
//
// 怎么 import：
//   useNavItems.js 顶部 `import { Api } from '../api'` 指向的是一个目录，
//   Node 的 ESM 不做目录解析（直接 import 会抛
//   "Directory import ... is not supported"），
//   而 api/index.js 又拉进了 element-plus —— 在 Node 里跑不动。
//   这里用 module.register 挂一个解析钩子，只把 '../api' 换成空壳，
//   被测的两个纯函数本身一行都不用改，
//   测的仍然是源码里那份真代码（不是复制出来的副本）。
import { register } from 'node:module'

const API_STUB = 'data:text/javascript,'
  + encodeURIComponent('export const Api = { listNavItems: async () => [] }')

register(
  'data:text/javascript,' + encodeURIComponent(`
    export async function resolve(specifier, context, nextResolve) {
      if (/(^|\\/)\\.\\.\\/api$/.test(specifier) || /(^|\\/)api$/.test(specifier)) {
        return { url: '${API_STUB}', shortCircuit: true, format: 'module' }
      }
      return nextResolve(specifier, context)
    }
  `),
  import.meta.url,
)

const { mergeNavGroups, permForPath } = await import('../src/composables/useNavItems.js')

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log((ok ? '✅' : '❌') + ' ' + name + (detail ? '  ' + detail : ''))
}

const BUILTIN = [
  { title: '工作区', items: [
    { path: '/', label: '工作台', perm: 'dashboard' },
    { path: '/notes', label: '知识库', perm: 'notes' },
  ] },
  { title: '应用', items: [
    { path: '/apps', label: '应用中心', perm: 'apps' },
  ] },
  { title: '系统', items: [
    { path: '/system/users', label: '用户管理', perm: 'system' },
  ] },
]
const allowAll = () => true

// ---------- permForPath：自定义项该按哪个权限位过滤 ----------
{
  assert('精确路径认得出权限位', permForPath('/notes') === 'notes', permForPath('/notes'))
  assert('子路径归到父页面', permForPath('/apps/abc') === 'apps', permForPath('/apps/abc'))
  assert('子路径同样归父（知识库）', permForPath('/notes/12') === 'notes', permForPath('/notes/12'))
  assert('子路径同样归父（系统）', permForPath('/system/audit') === 'system', permForPath('/system/audit'))
  assert('不受控的页面不设权限位', permForPath('/my-own-page') === '', permForPath('/my-own-page'))
  assert('空路径不设权限位', permForPath('') === '', permForPath(''))
  assert('非字符串也不炸', permForPath(undefined) === '', permForPath(undefined))
}

// ---------- mergeNavGroups：自定义项怎么并进去 ----------
{
  // 1. 组名对得上 → 并进已有的组，插在组内最后
  const g = mergeNavGroups(BUILTIN, [
    { path: '/my-page', label: '我的页面', group_name: '工作区' },
  ], allowAll)
  assert('组名对得上就并进已有组', g[0].items.length === 3, JSON.stringify(g[0].items.map(i => i.path)))
  assert('自定义项排在组内最后', g[0].items[2].path === '/my-page')
  assert('并进去的项带 custom 标记', g[0].items[2].custom === true)
  assert('没写图标就用 Link', g[0].items[2].icon === 'Link', g[0].items[2].icon)
  assert('组名对得上时不会多出分组', g.length === 3, g.map(x => x.title).join('/'))
}

// 2. 组名对不上 → 落到「自定义」组，且排在所有内置组之后
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/my-page', label: '我的页面' },
  ], allowAll)
  assert('没写组名归到「自定义」组', g[3].title === '自定义', g[3].title)
  assert('自定义组排在最后', g.slice(0, 3).map(x => x.title).join('/') === '工作区/应用/系统')
}

// 2b. 组名写的是内置组之外的名字 → 新建一个同名组，排在最后
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/my-page', label: '我的页面', group_name: '我的分组' },
  ], allowAll)
  assert('组名对不上就按这个名字新建一组', g[3].title === '我的分组', g[3].title)
  assert('新建的组排在所有内置组之后', g.length === 4, g.map(x => x.title).join('/'))
}

// 3. 同路径只留一个，内置的优先
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/notes', label: '重复的知识库', group_name: '工作区' },
  ], allowAll)
  assert('同路径不重复出现', g[0].items.filter(i => i.path === '/notes').length === 1)
  assert('同路径保留内置的那一个', g[0].items[1].label === '知识库', g[0].items[1].label)
}

// 4. 指向受控页面的自定义项，按那个页面的权限位过滤
//    注意：内置分组本来就在（权限过滤发生在 Layout.vue 里、调用本函数之前），
//    这里要验的是「自定义项有没有被挡掉」，不是「分组还在不在」。
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/notes', label: '知识库入口' },
  ], () => false)
  assert('同路径且没权限：自定义项不显示', !g.some(x => x.items.some(i => i.custom)), JSON.stringify(g.flatMap(x => x.items.map(i => i.path))))
}
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/notes/xyz', label: '某条知识', group_name: '工作区' },
  ], (perm) => perm !== 'notes')
  assert('指向受控页面的自定义项跟着权限走', !g.some(x => x.items.some(i => i.custom)), JSON.stringify(g.flatMap(x => x.items.map(i => i.path))))
  assert('挡掉自定义项后内置分组原样保留', g.length === 3, g.map(x => x.title).join('/'))
}
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/notes/xyz', label: '某条知识', group_name: '工作区' },
  ], (perm) => perm === 'notes')
  assert('有权限就显示', g[0].items.length === 3, JSON.stringify(g[0].items.map(i => i.path)))
}
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/my-page', label: '不受控的页面' },
  ], () => false)
  assert('不受控的页面不看权限位', g.length === 4, JSON.stringify(g.map(x => x.title)))
}

// 5. 空组最后被清掉；内置分组不能被就地改坏
{
  const g = mergeNavGroups(
    [{ title: '空组', items: [] }, { title: '有内容的组', items: [{ path: '/a' }] }],
    [], allowAll)
  assert('没有内容的组不显示', g.length === 1 && g[0].title === '有内容的组', JSON.stringify(g.map(x => x.title)))
}
{
  const src = [{ title: '工作区', items: [{ path: '/' }] }]
  mergeNavGroups(src, [{ path: '/x', label: 'X', group_name: '工作区' }], allowAll)
  assert('不改内置分组本身（就地改坏会污染下一次渲染）', src[0].items.length === 1, JSON.stringify(src[0].items))
}

// 6. 边界：没有自定义项 / 自定义项为空数组 / canPage 缺失
{
  const g = mergeNavGroups(BUILTIN, [], allowAll)
  assert('没有自定义项时原样返回', g.length === 3 && g[0].items.length === 2)
  assert('自定义项为 undefined 也不炸', mergeNavGroups(BUILTIN, undefined, allowAll).length === 3)
  assert('没有 canPage 时按「有权限」处理', mergeNavGroups(BUILTIN, [{ path: '/notes', label: 'x' }], undefined).length === 3)
}

// 7. 自定义项之间的同路径也要去重
{
  const g = mergeNavGroups(BUILTIN, [
    { path: '/dup', label: '甲', group_name: '自定义' },
    { path: '/dup', label: '乙', group_name: '自定义' },
  ], allowAll)
  assert('自定义项之间也去重', g[3].items.length === 1 && g[3].items[0].label === '甲',
    JSON.stringify(g[3].items.map(i => i.label)))
}

if (failed) {
  console.log('\n❌ 有 ' + failed + ' 项没通过')
  process.exit(1)
}
console.log('\n✅ 导航分组合并 —— 全部通过')
