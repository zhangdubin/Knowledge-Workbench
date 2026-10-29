/**
 * 图谱配色的纯计算单测
 * 重点盯住两件事：
 *   · 节点底色必须不透明（半透明会让连线从文字底下穿过去）
 *   · 截断后不能再超长
 */
import assert from 'node:assert/strict'
import {
  VIA_META, viaMeta, labelBudget, minScaleFor,
  hex2rgb, mix, lift, truncateLabel, textWidth,
} from '../src/utils/graphStyle.js'

let passed = 0
function t(name, fn) {
  fn()
  passed++
  console.log(`  ✓ ${name}`)
}

console.log('graphStyle')

t('连线的每种语义都有独立色相', () => {
  const slots = Object.values(VIA_META).map(m => m.slot)
  assert.equal(new Set(slots).size, slots.length, '色相不能重复，否则没法区分类型')
})

t('只有双向链接是虚线无箭头', () => {
  assert.equal(VIA_META.wikilink.dash, true)
  assert.equal(VIA_META.wikilink.arrow, false)
  for (const key of ['relation', 'reference', 'field']) {
    assert.equal(VIA_META[key].dash, false)
    assert.equal(VIA_META[key].arrow, true)
  }
})

t('未知语义按关联关系处理', () => {
  assert.equal(viaMeta('nope').label, VIA_META.relation.label)
  assert.equal(viaMeta(undefined).label, VIA_META.relation.label)
})

t('窄屏标签留得更短', () => {
  assert.ok(labelBudget(390) < labelBudget(1600))
  assert.equal(labelBudget(390), 8)
  assert.equal(labelBudget(1600), 14)
})

t('窄屏缩放下限更高：看得清比看得全重要', () => {
  assert.ok(minScaleFor(390) > minScaleFor(1600))
  assert.ok(minScaleFor(390) >= 0.6, '手机端缩到 0.6 以下字就认不出了')
})

t('hex 解析支持三位与六位', () => {
  assert.deepEqual(hex2rgb('#ffffff'), [255, 255, 255])
  assert.deepEqual(hex2rgb('#000'), [0, 0, 0])
  assert.deepEqual(hex2rgb('#5b5fc7'), [91, 95, 199])
})

t('mix 出来的颜色是不透明的 rgb', () => {
  // 节点底色 = 16% 类型色 + 84% 卡片色（浅色模式卡片是白的）
  const c = mix('#ffffff', '#5b5fc7', 0.16)
  assert.match(c, /^rgb\(\d+, \d+, \d+\)$/, '不能是 rgba，否则挡不住线')
  const [r, g, b] = c.match(/\d+/g).map(Number)
  assert.ok(r > 200 && g > 200 && b > 200, '浅色底的三个通道都该很亮')
  assert.ok(b > r, '紫色混白之后蓝色通道仍然最高')
})

t('mix 的比例方向：ratio 是混入色的占比', () => {
  assert.equal(mix('#000000', '#ffffff', 0), 'rgb(0, 0, 0)')
  assert.equal(mix('#000000', '#ffffff', 1), 'rgb(255, 255, 255)')
  assert.equal(mix('#000000', '#ffffff', 0.5), 'rgb(128, 128, 128)')
})

t('lift 会把颜色往白里提', () => {
  const before = hex2rgb('#5b5fc7')
  const after = lift('#5b5fc7', 0.3).match(/\d+/g).map(Number)
  assert.ok(after[0] > before[0] && after[1] > before[1] && after[2] > before[2])
})

t('截断后长度不超限，且带省略号', () => {
  const long = '知识工作台概览-这是一个非常非常长的记录名字'
  const cut = truncateLabel(long, 14)
  assert.equal(cut.length, 14)
  assert.ok(cut.endsWith('…'))
})

t('短标签原样返回', () => {
  assert.equal(truncateLabel('短名字', 14), '短名字')
  assert.equal(truncateLabel('', 14), '')
})

t('中文按一个字宽算，英文按 0.55 算', () => {
  assert.equal(textWidth('知识', 12), 24)
  assert.ok(Math.abs(textWidth('ab', 12) - 13.2) < 0.001)
})

console.log(`\n通过 ${passed} 项`)
