/**
 * 记录区的组合式函数：把「模型定义」翻译成界面要用的几组字段
 * ---------------------------------------------------------------------------
 * 纯函数部分（校验 / 归一 / 过滤 / 显示值）在 utils/recordFields.js，
 * 那里不碰 Vue，可以直接跑单测；这里只负责「响应式」这一层。
 */
import { computed, ref } from 'vue'
import { Api } from '../../api'
import { isChoiceType, isReferenceType } from '../../utils/modelFields.js'
import { fieldChoices } from '../../utils/recordFields.js'

/**
 * @param {import('vue').Ref<object|null>} entityTypeRef 当前模型（带 fields 的完整定义）
 * @param {object} opts
 * @param {import('vue').Ref<Array>} opts.allTypesRef 全量模型列表（解析外键显示名用）
 */
export function useRecordFields(entityTypeRef, { allTypesRef } = {}) {
  const fields = computed(() => entityTypeRef.value?.fields || [])

  // 表格列：长文本与附件在表格里放不下，交给卡片视图
  const displayFields = computed(() => fields.value
    .filter(f => !['file', 'image', 'textarea', 'richtext'].includes(f.type))
    .slice(0, 8))

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
