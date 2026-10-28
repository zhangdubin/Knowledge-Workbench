/**
 * 笔记分组的共享状态
 * ---------------------------------------------------------------------------
 * 侧栏、列表、详情页都要用同一份分组数据。
 * 这里用「模块级单例」而不是每次调用都新建一份：
 * 一来组件里 `useNoteGroups()` 拿到的就是同一份状态，
 * 二来只发一次请求 —— 侧栏和详情页同时挂着时不会各拉一遍。
 *
 * 分组接口还没上线时（404 / 后端未重启 / 网络不通），
 * available 会被置为 false，调用方据此安静降级：隐藏分组相关 UI，不弹错误框。
 */
import { computed, reactive } from 'vue'
import { NoteGroupsApi } from '../../api/note-groups'
import { groupErrorMessage, normalizeGroup, normalizeGroups } from './group-utils'

const state = reactive({
  groups: [],
  loading: false,
  available: true,      // 接口可用？
  loaded: false,        // 试过一次没有（避免反复重试打后端）
  error: '',
})

let inflight = null

export function useNoteGroups() {
  /** id → 分组 的索引 */
  const byId = computed(() => {
    const m = new Map()
    for (const g of state.groups) m.set(g.id, g)
    return m
  })

  const groups = computed(() => state.groups)
  const available = computed(() => state.available)
  const loading = computed(() => state.loading)
  const error = computed(() => state.error)

  /** 拉分组列表（默认只拉一次；force=true 时强制刷新） */
  async function load(force = false) {
    if (state.loaded && !force) return state.groups
    if (inflight) return inflight
    inflight = (async () => {
      state.loading = true
      try {
        const raw = await NoteGroupsApi.list()
        state.groups = normalizeGroups(raw)
        state.available = true
        state.error = ''
        state.loaded = true
      } catch (e) {
        // 接口没上线：安静降级，页面照常用（只是没有分组）
        state.groups = []
        state.available = false
        state.error = '分组功能暂不可用'
        state.loaded = true
      } finally {
        state.loading = false
        inflight = null
      }
      return state.groups
    })()
    return inflight
  }

  /** 新建分组；失败时抛出带中文说明的错误（409 重名由调用方就地提示） */
  async function create(payload) {
    try {
      const raw = await NoteGroupsApi.create(payload)
      const g = normalizeGroup(raw, state.groups.length)
      if (g) {
        state.groups = [...state.groups, g].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
      }
      return g
    } catch (e) {
      throw new Error(groupErrorMessage(e, '创建分组失败'))
    }
  }

  /** 改分组（重命名 / 换颜色） */
  async function update(id, payload) {
    try {
      const raw = await NoteGroupsApi.update(id, payload)
      const g = normalizeGroup(raw)
      if (g) {
        state.groups = state.groups
          .map(x => (x.id === id ? { ...x, ...g } : x))
          .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
      }
      return g
    } catch (e) {
      throw new Error(groupErrorMessage(e, '修改分组失败'))
    }
  }

  /** 删分组；moveTo 指定时把组内笔记搬到那个分组，否则变成「未分组」 */
  async function remove(id, moveTo = null) {
    try {
      await NoteGroupsApi.remove(id, moveTo)
      state.groups = state.groups.filter(g => g.id !== id)
      return true
    } catch (e) {
      throw new Error(groupErrorMessage(e, '删除分组失败'))
    }
  }

  /** 按 id 找分组；找不到返回 null（分组可能被删了） */
  function groupOf(id) {
    if (id == null) return null
    return byId.value.get(Number(id)) || null
  }

  /** 分组名（找不到时给个兜底文案，而不是 undefined） */
  function groupName(id, fallback = '未分组') {
    return groupOf(id)?.name || fallback
  }

  return { state, groups, byId, available, loading, error, load, create, update, remove, groupOf, groupName }
}
