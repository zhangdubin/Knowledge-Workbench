// JSON 解析 / 序列化 / 树形展开
//
// 取代原先的 Jevko 自定义语法：
// - 解析、报错口径与后端 services/jsontree.py 完全一致（含行列号）
// - toTree / summarize 的口径也与后端保持一致，
//   这样「本地即时预览」与「服务端解析」得到的结果不会打架

export const MAX_PREVIEW = 400
export const MAX_NODES = 5000
export const MAX_DEPTH = 24

/**
 * 解析 JSON 文本（不抛异常）
 * @param {string} text
 * @returns {{ok: boolean, value: any, error: string}}
 */
export function parseJson(text) {
  if (text == null || !String(text).trim()) {
    return { ok: false, value: null, error: '内容为空' }
  }
  try {
    return { ok: true, value: JSON.parse(String(text)), error: '' }
  } catch (e) {
    return { ok: false, value: null, error: locateError(String(text), e.message) }
  }
}

/**
 * 把原生报错翻译成「第 x 行第 y 列」这种可定位的提示
 *
 * 注意：不同版本的 V8 报错格式不一样 ——
 * 「Expected ',' or '}' ... at position N」带位置，
 * 而「Unexpected token '}' ... is not valid JSON」不带位置。
 * 后者退一步用坏 token 的首次出现位置做近似定位，够用且不会让人对着一段
 * 上千行的 JSON 干瞪眼。
 */
export function locateError(text, rawMessage) {
  const msg = rawMessage || ''
  let pos = -1
  const m = /position (\d+)/.exec(msg)
  if (m) pos = Number(m[1])
  if (pos < 0) {
    const quoted = /Unexpected token '([^']*)'/.exec(msg)
    if (quoted && quoted[1]) pos = text.indexOf(quoted[1])
  }
  if (pos < 0) return msg || '解析失败'
  const before = text.slice(0, pos)
  const line = before.split('\n').length
  const col = pos - before.lastIndexOf('\n')
  return `第 ${line} 行第 ${col} 列：${msg}`
}

/**
 * 序列化（中文不转义，方便直接阅读）
 * @param {any} value
 * @param {number} indent
 */
export function stringifyJson(value, indent = 2) {
  try {
    return JSON.stringify(value, null, indent)
  } catch (e) {
    return ''
  }
}

/** 归一化类型名，与后端 kind_of 保持一致 */
export function kindOf(value) {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  switch (typeof value) {
    case 'boolean': return 'boolean'
    case 'number': return 'number'
    case 'string': return 'string'
    case 'object': return 'object'
    default: return 'string'
  }
}

function scalarText(value) {
  if (value === null) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

/**
 * 把任意 JSON 值展开成可渲染节点数组（与后端 to_tree 同构）
 * @param {any} value
 * @returns {Array<object>}
 */
export function toTree(value) {
  let budget = MAX_NODES

  function build(val, key, isIndex, depth) {
    const kind = kindOf(val)
    const node = {
      key,
      isIndex,
      kind,
      value: null,
      chars: null,
      count: 0,
      truncated: false,
      children: [],
    }
    if (kind === 'object' || kind === 'array') {
      const entries = kind === 'object'
        ? Object.keys(val).map(k => [k, val[k]])
        : val.map((v, i) => [i, v])
      node.count = entries.length
      if (depth >= MAX_DEPTH) {
        node.truncated = true
        return node
      }
      for (const [k, v] of entries) {
        if (budget <= 0) {
          node.truncated = true
          break
        }
        budget -= 1
        node.children.push(build(v, String(k), kind === 'array', depth + 1))
      }
    } else if (kind === 'string') {
      node.chars = val.length
      node.value = val.length > MAX_PREVIEW ? val.slice(0, MAX_PREVIEW) + '…' : val
    } else {
      node.value = scalarText(val)
    }
    return node
  }

  budget -= 1
  return [build(value, null, false, 0)]
}

/**
 * 结构统计（与后端 get_summary 口径一致）
 * @param {any} value
 * @returns {{textLength:number, nodeCount:number, maxDepth:number, directChildren:number, rootType:string}}
 */
export function summarize(value) {
  const stat = { textLength: 0, nodeCount: 0, maxDepth: 0, directChildren: 0 }
  function walk(val, depth) {
    stat.nodeCount += 1
    const kind = kindOf(val)
    if (kind === 'string') {
      stat.textLength += val.length
    } else if (kind === 'object' || kind === 'array') {
      if (depth > stat.maxDepth) stat.maxDepth = depth
      const children = kind === 'object' ? Object.values(val) : val
      for (const c of children) walk(c, depth + 1)
    }
  }
  walk(value, 0)
  const kind = kindOf(value)
  if (kind === 'object' || kind === 'array') stat.directChildren = Object.keys(value).length
  stat.rootType = kind
  return stat
}

/** 一行摘要，例如 `对象 · 6 个字段` */
export function briefOf(value) {
  const kind = kindOf(value)
  if (kind === 'object') return `对象 · ${Object.keys(value).length} 个键`
  if (kind === 'array') return `数组 · ${value.length} 项`
  if (kind === 'null') return 'null'
  return `${kind} · ${scalarText(value)}`
}

/** 语法着色 token 类名 */
export function kindLabel(kind) {
  return {
    object: '对象', array: '数组', string: '文本',
    number: '数字', boolean: '布尔', null: '空',
  }[kind] || kind
}
