/**
 * 搜索 / 图谱请求的「去重 + 取消」小工具
 *
 * 为什么要有它：
 *
 * 1. **同一个词重复搜不重复发**。
 *    回车连按两下、或者用户把同一个词搜了两次，后端就要跑两遍完整检索。
 *    而语义检索那一步要打远端算向量（实测一次 250~400ms），
 *    是整条链路上最贵的一段 —— 重复请求在这里被直接丢掉。
 *
 * 2. **换了关键词就取消上一个**。
 *    不取消的话两个请求并行跑，而且先发后到的那个可能把新结果盖掉：
 *    用户看到的是旧结果，却以为是自己刚搜的那个。
 *
 * 3. **序号兜底**。
 *    万一取消没赶上（响应已经回来了），也只认最后一次请求的结果。
 *
 * 抽成独立模块是为了能写单测 —— 这段逻辑全是「时序」，
 * 光看页面是验不出「旧结果有没有被盖掉」的。
 */

/**
 * 建一个请求调度器
 *
 * @returns {{ begin: (key: string) => {seq:number, controller:AbortController, duplicated:boolean},
 *             isCurrent: (seq:number) => boolean,
 *             end: (seq:number) => void }}
 */
export function createSearchRequest() {
  let seq = 0
  let inflight = null

  return {
    begin(key) {
      // 同一个 key 已经在飞 → 复用它，不发第二次
      if (inflight && inflight.key === key) {
        return {
          seq: inflight.seq,
          controller: inflight.controller,
          duplicated: true,
        }
      }
      // 换了 key → 取消上一个
      if (inflight) {
        try { inflight.controller.abort() } catch (e) { /* 取消失败不影响新请求 */ }
      }
      const controller = new AbortController()
      const mySeq = ++seq
      inflight = { key, controller, seq: mySeq }
      return { seq: mySeq, controller, duplicated: false }
    },

    /** 这个响应还是不是「最新的那次」 */
    isCurrent(mySeq) {
      return mySeq === seq
    },

    /** 请求结束（成功 / 失败 / 取消）时收尾 */
    end(mySeq) {
      if (inflight && inflight.seq === mySeq) inflight = null
    },
  }
}

/**
 * 把后端返回的「降级 / 截断」说明转成一句人话
 *
 * 后端会在结果里带上 degraded / truncated 两个标记和一句说明。
 * 直接透传给用户：「命中过多，已取前 50 条」比用户自己猜
 * 「是不是没搜全」要好得多 —— 「搜不到」和「没搜全」在用户看来
 * 是一样的，但只有后者能解释。
 *
 * @param {object|null} res 后端返回
 * @returns {string} 提示文案，空串表示这次没有需要提示的事
 */
export function buildSearchNotice(res) {
  if (!res || typeof res !== 'object') return ''
  const bits = []
  if (res.degraded) {
    bits.push(res.degraded_reason || '语义通道已降级，结果可能不完整')
  }
  if (res.truncated) {
    bits.push(res.truncated_reason || '命中过多，已截断')
  }
  return bits.join('；')
}
