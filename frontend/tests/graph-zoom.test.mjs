/**
 * 「缩放 → 文字档位」的纯计算单测
 *
 * 为什么值得单独测：
 *   档位阈值是「看起来对不对」的经验值。改了阈值必须能立刻知道
 *   有没有把「缩太小藏字」「放大给全名」这两头改坏 ——
 *   光靠肉眼在浏览器里缩放试，一次要好几分钟，还容易漏看边界。
 */
import assert from 'node:assert/strict'
import {
  LABEL_TIER, ZOOM_RULES, minScaleFor,
  labelTierFor, labelCharsForTier, fontSizeForTier,
  domLabelScaleFor, tierHint,
} from '../src/utils/graphStyle.js'

let passed = 0
function t(name, fn) {
  fn()
  passed++
  console.log(`  ✓ ${name}`)
}

console.log('graphStyle · 缩放文字档位')

t('四档都有名字，且互不相同', () => {
  const vals = Object.values(LABEL_TIER)
  assert.equal(vals.length, 4)
  assert.equal(new Set(vals).size, 4)
})

t('缩得很小时藏字', () => {
  assert.equal(labelTierFor(0.2), LABEL_TIER.hidden)
  assert.equal(labelTierFor(0.44), LABEL_TIER.hidden)
})

t('缩得较小时只留图标', () => {
  assert.equal(labelTierFor(0.6), LABEL_TIER.brief)
  assert.equal(labelTierFor(0.79), LABEL_TIER.brief)
})

t('正常缩放给全名', () => {
  assert.equal(labelTierFor(1), LABEL_TIER.full)
  assert.equal(labelTierFor(1.5), LABEL_TIER.full)
})

t('放大后进入大字档', () => {
  assert.equal(labelTierFor(1.6), LABEL_TIER.large)
  assert.equal(labelTierFor(3), LABEL_TIER.large)
})

t('档位边界是连续的（不跳档、不漏档）', () => {
  let prev = null
  for (let s = 0.05; s <= 3; s += 0.01) {
    const tier = labelTierFor(s)
    if (prev && prev !== tier) {
      const order = [LABEL_TIER.hidden, LABEL_TIER.brief, LABEL_TIER.full, LABEL_TIER.large]
      assert.equal(
        order.indexOf(tier), order.indexOf(prev) + 1,
        `缩放 ${s.toFixed(2)} 从 ${prev} 跳到 ${tier}，中间漏了档`)
    }
    prev = tier
  }
})

t('缩放非法时按「最小」处理（宁可藏字也别画一堆看不清的）', () => {
  assert.equal(labelTierFor(0), LABEL_TIER.hidden)
  assert.equal(labelTierFor(-1), LABEL_TIER.hidden)
  assert.equal(labelTierFor(NaN), LABEL_TIER.hidden)
  assert.equal(labelTierFor(undefined), LABEL_TIER.hidden)
})

t('阈值可以覆盖（不同图谱可以微调）', () => {
  const rules = { hiddenBelow: 0.2, briefBelow: 0.4, largeFrom: 2.5 }
  assert.equal(labelTierFor(0.3, rules), LABEL_TIER.brief)
  assert.equal(labelTierFor(0.1, rules), LABEL_TIER.hidden)
  assert.equal(labelTierFor(2.0, rules), LABEL_TIER.full)
  assert.equal(labelTierFor(2.6, rules), LABEL_TIER.large)
})

t('藏字档一个字都不留', () => {
  assert.equal(labelCharsForTier(LABEL_TIER.hidden, 1440), 0)
})

t('只显示图标的档位只留极少的字', () => {
  assert.ok(labelCharsForTier(LABEL_TIER.brief, 1440) <= 2)
  assert.ok(labelCharsForTier(LABEL_TIER.brief, 500) <= 1)
})

t('正常档按视口宽度的预算留字', () => {
  assert.equal(labelCharsForTier(LABEL_TIER.full, 1440), 14)
  assert.equal(labelCharsForTier(LABEL_TIER.full, 500), 8)
})

t('放大档留的字最多', () => {
  assert.ok(
    labelCharsForTier(LABEL_TIER.large, 1440) > labelCharsForTier(LABEL_TIER.full, 1440))
})

t('放大档字号反而略小（canvas 上的字会跟着缩放一起变大）', () => {
  const base = 13
  assert.equal(fontSizeForTier(LABEL_TIER.full, base), base)
  assert.equal(fontSizeForTier(LABEL_TIER.large, base), Math.round(base * 0.9))
})

t('DOM 文字随缩放同比放大，但有上下限', () => {
  assert.equal(domLabelScaleFor(1), 1)
  assert.ok(domLabelScaleFor(1.5) > 1)
  assert.ok(domLabelScaleFor(0.5) < 1)
  // 太大会撑破布局，太小会看不清 —— 必须夹住
  assert.equal(domLabelScaleFor(99), 1.8)
  assert.equal(domLabelScaleFor(0.001), 0.7)
  assert.equal(domLabelScaleFor(NaN), 1)
})

t('藏字与只显示图标时才给提示，正常档不说话', () => {
  assert.ok(tierHint(LABEL_TIER.hidden).includes('放大'))
  assert.ok(tierHint(LABEL_TIER.brief).length > 0)
  assert.equal(tierHint(LABEL_TIER.full), '')
  assert.equal(tierHint(LABEL_TIER.large), '')
})

t('默认阈值是单调的（hidden < brief < large）', () => {
  assert.ok(ZOOM_RULES.hiddenBelow < ZOOM_RULES.briefBelow)
  assert.ok(ZOOM_RULES.briefBelow < ZOOM_RULES.largeFrom)
})

t('藏字阈值不高于缩放下限：被下限卡住时不能一个字都没有', () => {
  // 两处数值是耦合的：minScaleFor 是「宁可看不清全图也要看得清字」的下限，
  // hiddenBelow 比它还高的话，被下限卡住的画面就一个字都没有了 —— 那是 bug 不是取舍
  assert.ok(ZOOM_RULES.hiddenBelow <= minScaleFor(1440),
    `藏字阈值 ${ZOOM_RULES.hiddenBelow} 高于缩放下限 ${minScaleFor(1440)}`)
  assert.ok(ZOOM_RULES.hiddenBelow <= minScaleFor(500),
    `窄屏同理：${ZOOM_RULES.hiddenBelow} > ${minScaleFor(500)}`)
})

console.log(`\n通过 ${passed} 项`)
