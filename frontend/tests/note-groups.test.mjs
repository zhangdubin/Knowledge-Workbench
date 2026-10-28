// 知识库分组相关的纯函数断言
// 覆盖 components/note/group-utils.js：分组规整（裸数组 / {items} / 字段缺失）、
// 名称校验（空名 / 超长 / 重名 / 改自己不算重名）、错误翻译（409 / 404 / 400）、
// 笔记归属取值（null / 缺键 = 未分组）
import {
  DEFAULT_GROUP_COLOR, GROUP_COLOR_PRESETS, GROUP_NAME_MAX,
  groupErrorMessage, normalizeGroup, normalizeGroups, noteGroupId, validateGroupName,
} from '../src/components/note/group-utils.js'

let failed = 0
function assert(name, cond, detail = '') {
  const ok = typeof cond === 'function' ? cond() : cond
  if (!ok) failed++
  console.log(`${ok ? '✅' : '❌'}${name}${detail ? '  ' + detail : ''}`)
}

// ---------- normalizeGroup：字段缺失也不炸 ----------
{
  const g = normalizeGroup({ id: 3, name: '  产品设计 ', color: '#5b5fc7', count: 7, sort_order: 2 })
  assert('id 转成数字', g.id === 3)
  assert('名字去掉首尾空格', g.name === '产品设计', g.name)
  assert('count 保留', g.count === 7)
  assert('sort_order 保留', g.sort_order === 2)
}
{
  const g = normalizeGroup({ id: 1 })
  assert('缺名字给兜底名', g.name === '分组 1', g.name)
  assert('缺颜色给主色', g.color === DEFAULT_GROUP_COLOR, g.color)
  assert('缺 count 当 0', g.count === 0)
  assert('缺 sort_order 用下标', g.sort_order === 0)
}
{
  assert('不是对象返回 null', normalizeGroup(null) === null)
  assert('没有 id 返回 null', normalizeGroup({ name: 'x' }) === null)
  assert('id 不是数字返回 null', normalizeGroup({ id: 'abc' }) === null)
}
{
  const g = normalizeGroup({ id: '5', count: '9' })
  assert('字符串 id/count 会转成数字', g.id === 5 && g.count === 9, JSON.stringify(g))
}

// ---------- normalizeGroups：两种返回形状 + 排序 ----------
{
  const arr = normalizeGroups([
    { id: 2, name: 'B', sort_order: 1 },
    { id: 1, name: 'A', sort_order: 0 },
  ])
  assert('裸数组能解析', arr.length === 2)
  assert('按 sort_order 排', arr[0].name === 'A' && arr[1].name === 'B', arr.map(x => x.name).join(','))
}
{
  const obj = normalizeGroups({ items: [{ id: 1, name: 'A' }] })
  assert('{items:[...]} 也能解析', obj.length === 1 && obj[0].name === 'A')
}
{
  assert('空/垃圾输入返回空数组', normalizeGroups(null).length === 0 && normalizeGroups('x').length === 0)
}
{
  const mixed = normalizeGroups([{ id: 1, name: 'ok' }, null, { name: '没有 id' }])
  assert('坏数据被丢掉', mixed.length === 1, JSON.stringify(mixed))
}

// ---------- validateGroupName ----------
{
  const groups = [{ id: 1, name: '工作' }, { id: 2, name: '学习' }]
  assert('空名报错', validateGroupName('', groups) === '给分组起个名字')
  assert('全空格算空名', validateGroupName('   ', groups) === '给分组起个名字')
  assert('正常名通过', validateGroupName('新分组', groups) === '')
  assert('重名被拦', validateGroupName('工作', groups).includes('同名'))
  assert('重名忽略大小写', validateGroupName('工作'.toUpperCase(), groups).includes('同名'))
  assert('改自己不算重名', validateGroupName('工作', groups, 1) === '')
  assert('超长被拦', validateGroupName('x'.repeat(GROUP_NAME_MAX + 1), groups).includes('40'))
  assert('刚好 40 字通过', validateGroupName('x'.repeat(GROUP_NAME_MAX), groups) === '')
}

// ---------- groupErrorMessage ----------
{
  const e409 = { response: { status: 409, data: { detail: '分组名已存在' } } }
  assert('409 读后端 detail', groupErrorMessage(e409) === '分组名已存在')
  assert('404 有专门文案', groupErrorMessage({ response: { status: 404, data: {} } }).includes('不存在'))
  assert('400 读后端 detail', groupErrorMessage({ response: { status: 400, data: { detail: '分组名不能为空' } } }) === '分组名不能为空')
  assert('没有响应时用兜底', groupErrorMessage({}, '出错了') === '出错了')
  assert('空错误对象不炸', typeof groupErrorMessage(null) === 'string')
}

// ---------- noteGroupId：null / 缺键 = 未分组 ----------
{
  assert('有分组时取 id', noteGroupId({ data: { group_id: 3 } }) === 3)
  assert('null 算未分组', noteGroupId({ data: { group_id: null } }) === 0)
  assert('缺键算未分组', noteGroupId({ data: { title: 'x' } }) === 0)
  assert('没有 data 也不炸', noteGroupId(null) === 0)
  assert('字符串数字也认', noteGroupId({ data: { group_id: '2' } }) === 2)
}

// ---------- 色板 ----------
{
  assert('预设色至少 6 个', GROUP_COLOR_PRESETS.length >= 6, String(GROUP_COLOR_PRESETS.length))
  assert('预设色都是 #rrggbb',
    GROUP_COLOR_PRESETS.every(c => /^#[0-9a-f]{6}$/i.test(c.value)),
    GROUP_COLOR_PRESETS.map(c => c.value).join(' '))
  assert('色板值不重复', new Set(GROUP_COLOR_PRESETS.map(c => c.value)).size === GROUP_COLOR_PRESETS.length)
}

console.log(failed ? `\n❌ ${failed} 项失败` : '\n✅ 分组纯函数断言全部通过')
process.exit(failed ? 1 : 0)
