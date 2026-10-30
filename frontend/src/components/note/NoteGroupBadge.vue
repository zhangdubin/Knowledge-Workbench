<template>
  <!--
    分组徽标：色点 + 组名。

    原来只有一个小圆点（8px），在一屏几十行里根本看不见 ——
    「这篇笔记属于哪个组」这个信息等于没有。
    现在做成一枚**带底色的胶囊**：底色是分组自己的颜色（淡化版），
    扫一眼就能看出每行属于哪一组。

    未分组（muted）保持中性灰 —— 它是「没有归属」，不该抢眼。
  -->
  <span
    class="ng-badge"
    :class="{ 'is-muted': muted }"
    :style="color && !muted ? badgeStyle : null"
    :title="`分组：${name}`"
  >
    <span
      class="ng-dot"
      :style="color ? { backgroundColor: color } : null"
      aria-hidden="true"
    ></span>
    <span class="ng-badge-name">{{ name }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, default: '未分组' },
  color: { type: String, default: '' },
  // 未分组：色点用中性色，整体弱化
  muted: { type: Boolean, default: false },
})

/**
 * 把分组自己的颜色变成「淡底 + 深色文字 + 同色描边」
 *
 * ⚠️ 文字色不能直接用分组原色：
 * 橙色（#e8833a）配白底只有 2.71:1、青色（#0f8b8d）只有 4.12:1 ——
 * 都达不到正文要求的 4.5:1（实测被 v28 体检抓出来）。
 *
 * 所以文字色要把原色**压暗**（保持色相，降到够对比度），
 * 底色还是原色的淡色版 —— 色相不变，一眼还能认出是哪个分组。
 */
/** 相对亮度（WCAG） */
function luminance(r, g, b) {
  const ch = [r, g, b].map((v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
}

/** 与白底的对比度 */
function contrastOnWhite(r, g, b) {
  const l1 = luminance(r, g, b)
  const l2 = luminance(255, 255, 255)
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
}

/**
 * 压暗到对比度达标
 *
 * 不能用固定的压暗比例 —— 橙色天生亮（#e8833a 压暗 42% 才 3.90:1，还是不够），
 * 而深色本来就已经达标（青 4.12 → 压完 19.17，过头了）。
 * 所以按步长一点点压，**压到 4.5:1 就停**，色相尽量保留。
 */
function darkenUntil(r, g, b, target = 4.5) {
  // 往「同一个色相的更暗版本」压，而不是往灰色压 ——
  // 往灰压会让橙/绿/青变成灰色，分组就认不出来了（色相是分组的身份）。
  //
  // 做法：把 RGB 转成 HSL，**只降明度**（L），色相 H 与饱和度 S 保持不变，
  // 再转回 RGB。这样颜色还是那个颜色，只是深到看得清。
  let cur = { r, g, b }
  for (let step = 0; step < 14; step++) {
    if (contrastOnWhite(cur.r, cur.g, cur.b) >= target) return cur
    const hsl = rgbToHsl(cur.r, cur.g, cur.b)
    const next = hslToRgb(hsl.h, Math.max(0, hsl.s, 0.35), Math.max(0, hsl.l - 0.07))
    cur = next
  }
  return cur
}

/** RGB → HSL（h: 0-360, s/l: 0-1） */
function rgbToHsl(r, g, b) {
  const rr = r / 255, gg = g / 255, bb = b / 255
  const max = Math.max(rr, gg, bb), min = Math.min(rr, gg, bb)
  const l = (max + min) / 2
  let h = 0, s = 0
  if (max !== min) {
    const d = max - min
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    if (max === rr) h = ((gg - bb) / d + (gg < bb ? 6 : 0))
    else if (max === gg) h = (bb - rr) / d + 2
    else h = (rr - gg) / d + 4
    h *= 60
  }
  return { h, s, l }
}

/** HSL → RGB */
function hslToRgb(h, s, l) {
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2
  let rgbv
  if (h < 60) rgbv = [c, x, 0]
  else if (h < 120) rgbv = [x, c, 0]
  else if (h < 180) rgbv = [0, c, x]
  else if (h < 240) rgbv = [0, x, c]
  else if (h < 300) rgbv = [x, 0, c]
  else rgbv = [c, 0, x]
  return { r: Math.round((rgbv[0] + m) * 255), g: Math.round((rgbv[1] + m) * 255), b: Math.round((rgbv[2] + m) * 255) }
}

const badgeStyle = computed(() => {
  const c = props.color
  if (!c) return {}
  const m = c.replace('#', '')
  if (m.length !== 6) return {}
  const r = parseInt(m.slice(0, 2), 16)
  const g = parseInt(m.slice(2, 4), 16)
  const b = parseInt(m.slice(4, 6), 16)
  const dark = darkenUntil(r, g, b)
  return {
    backgroundColor: `rgb(${r} ${g} ${b} / 0.10)`,
    borderColor: `rgb(${r} ${g} ${b} / 0.28)`,
    color: `rgb(${dark.r} ${dark.g} ${dark.b})`,
  }
})
</script>

<style scoped>
.ng-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-secondary);
  max-width: 160px;
  padding: 0 7px 0 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
}
.ng-badge-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ng-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-disabled);
}
.ng-badge.is-muted {
  color: var(--text-tertiary);
  background: transparent;
  border-color: var(--border-light);
  padding-right: 7px;
}
</style>
