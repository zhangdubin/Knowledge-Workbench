/**
 * 记录区的组合式函数：把「模型定义」翻译成界面要用的几组字段
 * ---------------------------------------------------------------------------
 * 纯函数部分（校验 / 归一 / 过滤 / 显示值）在 utils/recordFields.js，
 * 那里不碰 Vue，可以直接跑单测；这里只负责「响应式」这一层。
 */
import { computed, ref } from 'vue'
import { Api } from '../../api'
import { isChoiceType, isReferenceType } from '../../utils/modelFields.js'
import {
  fieldChoices, cleanFilterParams, countActiveFilters, defaultColumnKeys,
  filterColumnsByKeys, tableCandidateFields,
} from '../../utils/recordFields.js'

/**
 * @param {import('vue').Ref<object|null>} entityTypeRef 当前模型（带 fields 的完整定义）
 * @param {object} opts
 * @param {import('vue').Ref<Array>} opts.allTypesRef 全量模型列表（解析外键显示名用）
 */
export function useRecordFields(entityTypeRef, { allTypesRef } = {}) {
  const fields = computed(() => entityTypeRef.value?.fields || [])

  // 表格列的候选字段：长文本与附件在表格里放不下，交给卡片视图
  // 这里不截断到 8 个 —— 「列显示设置」里要能勾到第 9、10 个字段，
  // 默认显示哪几个由 defaultColumnKeys 决定（两页行为一致）。
  const displayFields = computed(() => tableCandidateFields(fields.value))

  // 卡片视图：长文本也要看得到，只把附件排除
  const cardFields = computed(() => fields.value.filter(f => f.type !== 'file' && f.type !== 'image'))

  // 筛选器：枚举与布尔才有明确的取值空间
  const filterFields = computed(() => fields.value.filter(f =>
    f.type === 'select' || f.type === 'multiselect' || f.type === 'boolean'))

  // 每个选择字段的候选项
  const choicesMap = computed(() => {
    const m = {}
    for (const f of fields.value) {
      if (isChoiceType(f.type)) m[f.key] = fieldChoices(f)
    }
    return m
  })

  // 外键显示名缓存：`${目标模型key}:${记录id}` → 名称
  const refLabels = ref({})

  /**
   * 拉取外键目标的记录名
   * 为什么要有这一步：外键字段存的是记录 id，直接显示 12 用户根本认不出来。
   */
  async function loadRefLabels() {
    const types = allTypesRef?.value || []
    const next = { ...refLabels.value }
    for (const f of fields.value) {
      if (!isReferenceType(f.type)) continue
      const tkey = f.options?.target
      if (!tkey) continue
      const et = types.find(t => t.key === tkey)
      if (!et) continue
      try {
        const r = await Api.listRecords(et.id, { page_size: 200 })
        for (const rec of (r.items || [])) {
          next[`${tkey}:${rec.id}`] = rec.data?.name || rec.data?.title || rec.data?.code || `#${rec.id}`
        }
      } catch { /* 目标模型取不到就不显示名字，退化成 id */ }
    }
    refLabels.value = next
  }

  return {
    fields, displayFields, cardFields, filterFields, choicesMap,
    refLabels, loadRefLabels,
  }
}

/**
 * 记录区的「视图状态」：筛选条件、显示哪些列、表格还是卡片
 * ---------------------------------------------------------------------------
 * 为什么要抽出来：
 * 「记录页」和「应用独立页」进的是同一份数据，但之前两边的筛选器、列设置、
 * 视图切换各写一遍 —— 结果用户在应用里勾掉的列、设好的筛选，一进记录页就全丢了，
 * 看起来就像「记录页功能坏了」。
 * 抽成一份之后，两个入口的行为完全一致，改一处两处都生效。
 *
 * @param {import('vue').Ref<object|null>} entityTypeRef 当前模型（带 fields 的完整定义）
 */
export function useRecordView(entityTypeRef) {
  // 筛选条件：字段 key → 期望值（多选是数组）
  const filters = ref({})
  // 显示哪些列：字段 key 列表
  const visibleKeys = ref([])
  // 表格还是卡片
  const viewMode = ref('table')

  const fields = computed(() => entityTypeRef.value?.fields || [])

  // 表格列 = 可显示的字段 ∩ 用户勾选的字段
  const columns = computed(() => filterColumnsByKeys(
    tableCandidateFields(fields.value),
    visibleKeys.value,
  ))

  const activeFilterCount = computed(() => countActiveFilters(filters.value))

  /** 模型切换时重置视图状态：上一个模型的列名对不上新模型 */
  function resetForType() {
    filters.value = {}
    visibleKeys.value = defaultColumnKeys(fields.value)
    viewMode.value = 'table'
  }

  /** 清空筛选（筛选器里的「清空筛选」按钮） */
  function clearFilters() {
    filters.value = {}
  }

  /**
   * 发给接口的筛选参数
   * 服务端筛才是真筛：本地筛要把记录整个拉下来（上限 500 条），
   * 超过这个数用户根本筛不到，而且分页数字是假的。
   */
  function filterParams() {
    return cleanFilterParams(filters.value)
  }

  return {
    filters, visibleKeys, viewMode, columns, activeFilterCount,
    resetForType, clearFilters, filterParams,
  }
}
