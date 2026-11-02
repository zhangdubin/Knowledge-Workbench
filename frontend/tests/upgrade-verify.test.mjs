/**
 * 升级后的「服务端权威核验」在前端这一侧的契约
 *
 * 背景：以前界面自己拿 /api/health 的 version 跟目标比字符串，
 * 比出来只有一个「对不上」，用户只能自己去猜。
 * 现在判定在后端（它看得见镜像、容器与源码），
 * 前端只负责把「**差在哪一层** + **该执行什么**」讲清楚。
 *
 * 所以这里验的是：
 *   1. 后端给的每一层结论，前端都能渲染成一句能照着做的话；
 *   2. 那句话里必须带**具体命令**（不能又是一句「请检查日志」）；
 *   3. 「页面拿到的是旧响应」要被识别成缓存问题，而不是「升级失败」。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  verifyFailureText,
  detectCacheLayer,
  VERIFY_LAYER,
  VERIFY_LAYER_TEXT,
} from '../src/utils/update.js'

// ---------- 层枚举 ----------
test('四层 + ok 都有说法', () => {
  for (const key of ['ok', 'source', 'image', 'container', 'cache']) {
    assert.ok(VERIFY_LAYER_TEXT[key], `层 ${key} 必须有中文说法`)
  }
  assert.equal(VERIFY_LAYER.OK, 'ok')
  assert.equal(VERIFY_LAYER.SOURCE, 'source')
  assert.equal(VERIFY_LAYER.IMAGE, 'image')
  assert.equal(VERIFY_LAYER.CONTAINER, 'container')
  assert.equal(VERIFY_LAYER.CACHE, 'cache')
})

// ---------- 核验通过 ----------
test('核验通过时不产生任何失败文案', () => {
  assert.equal(verifyFailureText({ ok: true, layer: 'ok' }), '')
})

// ---------- 每一层都要给出可执行的下一步 ----------
const CASES = [
  {
    layer: 'container',
    title: '容器没重建',
    must: ['--force-recreate'],
  },
  {
    layer: 'image',
    title: '镜像没换',
    must: ['docker compose build'],
  },
  {
    layer: 'source',
    title: '源码没换',
    must: ['git checkout'],
  },
  {
    layer: 'cache',
    title: '缓存没刷新',
    must: ['Cache-Control'],
  },
]

for (const c of CASES) {
  test(`${c.title}：文案里说清是哪一层，并给出具体命令`, () => {
    const verify = {
      ok: false,
      layer: c.layer,
      running: '0.13.0',
      target: 'v1.0.0',
      reason: '镜像里已经是 v1.0.0，但正在运行的容器还是 v0.13.0',
      fix: c.must.join(' ; '),
      commands: c.must.map((m) => `docker compose up -d ${m}`),
    }
    const text = verifyFailureText(verify)
    assert.ok(text.includes('升级没有真正生效'), '保留原来的意思：升级没有真正生效')
    assert.ok(text.includes('0.13.0'), '说清现在跑的是哪一版')
    assert.ok(text.includes('1.0.0'), '说清期望的是哪一版')
    assert.ok(text.includes(VERIFY_LAYER_TEXT[c.layer]), '说清是哪一层没换成功')
    for (const m of c.must) {
      assert.ok(text.includes(m), `文案里必须带具体命令片段：${m}`)
    }
    assert.ok(
      !text.includes('请检查 docker compose logs backend 与镜像标签是否换成功。'),
      '不能还是那句让人自己去猜的话',
    )
  })
}

// ---------- 后端没给命令时也要有下一步 ----------
test('后端没给命令时，用 fix 字段兜底', () => {
  const text = verifyFailureText({
    ok: false,
    layer: 'image',
    running: '0.13.0',
    target: 'v1.0.0',
    reason: '镜像没有换成目标版本',
    fix: 'docker compose build && docker compose up -d',
    commands: [],
  })
  assert.ok(text.includes('下一步：'), '要有「下一步」')
  assert.ok(text.includes('docker compose build'), 'fix 里的命令要出现')
})

// ---------- 老后端（没有核验接口）不能把界面搞空 ----------
test('老后端没有核验结论时退回原来的说法', () => {
  const text = verifyFailureText(null, '0.13.0', 'v1.0.0')
  assert.ok(text.includes('升级没有真正生效'), '仍然说清升级没生效')
  assert.ok(text.includes('0.13.0') && text.includes('1.0.0'), '仍然说清两版号')
  assert.equal(verifyFailureText(null), '', '连版本号都没有时不要瞎说')
})

// ---------- 缓存：版本其实已经对了 ----------
test('后端说已升级、但页面拿到的是旧响应 → 判成缓存问题', () => {
  const verify = { ok: true, running: '1.0.0', target: 'v1.0.0' }
  assert.equal(
    detectCacheLayer(verify, { version: '0.13.0' }),
    VERIFY_LAYER.CACHE,
    '两者对不上就是缓存挡在中间',
  )
  assert.equal(
    detectCacheLayer(verify, { version: '1.0.0' }),
    '',
    '两者一致时不是缓存问题',
  )
  assert.equal(detectCacheLayer(verify, null), '', '拿不到健康检查时不瞎判')
  assert.equal(
    detectCacheLayer({ ok: false, running: '1.0.0' }, { version: '0.13.0' }),
    '',
    '核验没过的时候不是缓存问题（那是真没升成）',
  )
})
