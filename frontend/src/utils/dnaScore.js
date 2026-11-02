/**
 * 评分的「翻译层」：后端算分，这里把它变成人能看懂的东西
 *
 * 为什么要单独抽一个文件：分数的解释规则（几分算好、怎么分档、
 * 分项怎么排）如果散在页面里，就只能靠人肉盯页面来验。
 * 抽出来就能单测钉住 —— 改坏了会红，不会等到上线才发现。
 *
 * 口径在后端（backend/app/services/dna_score.py），这里只做展示翻译，
 * 不重算分数，避免两边算出两个不一样的数。
 */

/**
 * 分数显示：保留两位，0.42 而不是 0.4200
 *
 * null / undefined / 空串一律显示为破折号：
 * Number(null) 是 0 —— 不挡一下的话，「没评分」会被显示成「0.00 分」，
 * 看起来像「评过了，得 0 分」，与「还没评」完全是两回事。
 */
export function fmtScore(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

/** 分档：好 / 中 / 差 —— 一眼能看出「这条不行」 */
export function scoreTone(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return 'score-none'
  if (n >= 0.7) return 'score-good'
  if (n >= 0.45) return 'score-mid'
  return 'score-low'
}

/** 百分比（0 到 1 → 0 到 100%） */
export function pct(v) {
  // 空值不当成 0%：没数据与「真的是 0%」不是一回事
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return Math.round(n * 100) + '%'
}

/** 复用结果的说法 */
export function outcomeLabel(o) {
  return { success: '成功', fail: '失败', unknown: '待定' }[o] || o
}

/**
 * 把后端的评分载荷翻译成两栏分项
 *
 * 后端给的是按 key 索引的分项字典，页面要的是有顺序的数组 ——
 * 所以这里做一次转换，顺便兜住缺字段的情况。
 */
export function buildScoreGroups(score) {
  if (!score) return []
  const mk = (key, label, partsMap, penalties) => ({
    key,
    label,
    score: key === 'expressiveness' ? score.expressiveness : score.confidence,
    parts: Object.values(partsMap || {}).map((p) => ({
      key: p.key,
      label: p.label,
      score: p.score,
      weight: p.weight,
      detail: p.detail,
    })),
    penalties: (penalties || []).map((x) => ({
      key: x.key,
      label: x.label,
      amount: x.amount,
      detail: x.detail,
    })),
  })
  const ev = score.evidence || {}
  return [
    mk('expressiveness', '表达度 · 说清楚了没有',
       score.express_parts, ev.expressiveness?.penalties),
    mk('confidence', '置信度 · 有多可信',
       score.confidence_parts, ev.confidence?.penalties),
  ]
}

/** 履历：复用成功/失败、人工纠正、来源数 */
export function scoreHistory(score) {
  const sc = score || {}
  return {
    use_success: sc.use_success || 0,
    use_fail: sc.use_fail || 0,
    corrections: sc.corrections || 0,
    distinct_sources: sc.distinct_sources || 1,
  }
}

/**
 * 一句话体检结论 —— 让人不看分项也知道该干什么
 * 规则简单：先看是不是被纠正过，再看表达度，最后看置信度。
 */
export function scoreVerdict(score) {
  if (!score) return { tone: 'score-none', text: '还没有评分' }
  const h = scoreHistory(score)
  if (h.corrections > 0) {
    return { tone: 'score-low', text: `被纠正过 ${h.corrections} 次，先核对内容` }
  }
  const e = Number(score.expressiveness || 0)
  const c = Number(score.confidence || 0)
  if (e < 0.4) {
    return { tone: 'score-low', text: '说得太含糊，要补充细节才能用' }
  }
  if (c < 0.5) {
    return { tone: 'score-mid', text: '出处不够硬，先补来源或交叉验证' }
  }
  if (e >= 0.7 && c >= 0.7) {
    return { tone: 'score-good', text: '说得清楚又可信，可以直接拿去用' }
  }
  return { tone: 'score-mid', text: '基本可用，再打磨一下细节会更稳' }
}
