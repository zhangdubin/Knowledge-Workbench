/**
 * 数据模型删除的统一确认与执行
 *
 * v0.3.0 起删除是「进回收站」的软删除：字段定义、记录、关联定义全部保留，
 * 可在 系统管理 → 回收站 里恢复；只有回收站里的「彻底删除」才是物理级联
 * （entity_record / field_definition / relation_def 都是 ondelete=CASCADE）。
 * 即便如此，删除仍是结构性操作 —— 确认门槛保持：必须手输模型 Key。
 *
 * 数据模型列表页与模型编辑器两个入口共用这一份，避免两处文案/强度不一致。
 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
  ))
}

/** 影响范围文案：0 的项不列出来，免得「0 条关联定义」这种噪音干扰判断 */
export function modelImpactText({ field_count = 0, record_count = 0, relation_count = 0 } = {}) {
  const parts = [`${field_count} 个字段定义`]
  if (record_count > 0) parts.push(`${record_count} 条记录`)
  if (relation_count > 0) parts.push(`${relation_count} 条关联定义`)
  return parts.join('、')
}

/**
 * 弹出确认框并执行删除
 * @returns {Promise<boolean>} true = 已删除；false = 用户取消或删除失败
 */
export async function confirmAndDeleteModel(model) {
  const { id, key, name } = model || {}
  if (!id || !key) {
    ElMessage.warning('模型信息不完整，无法删除')
    return false
  }
  const recordCount = model.record_count || 0
  const impact = modelImpactText(model)

  const lines = [
    `即将删除数据模型 <b>${esc(name || key)}</b>（<code>${esc(key)}</code>）。`,
    `模型连同 <b>${impact}</b> 会一起移入回收站，随时可在「系统管理 → 回收站」恢复。`,
    `彻底删除（不可恢复）需要到回收站里再次确认。`,
  ]
  if (recordCount > 0) {
    lines.push(
      '<span class="md-del-warn">该模型下已有 <b>' + recordCount + '</b> 条记录，'
      + '删除期间它们将从各页面隐藏（不算丢失）。</span>'
    )
  }
  lines.push(`<div class="md-del-confirm">请输入模型 Key <code>${esc(key)}</code> 确认：</div>`)

  try {
    // 必须用 prompt 而不是 confirm：Element Plus 只在 boxType === 'prompt' 时才跑
    // inputValidator（见 message-box 源码 handleAction）。
    // 用 confirm 的话输入框照样渲染出来，但校验被静默跳过 —— 输什么都会直接删，
    // 比没有输入框更危险。这个坑是靠「输错 Key 应该被拦住」的负例测试抓出来的。
    await ElMessageBox.prompt(lines.join(''), '删除数据模型（移入回收站）', {
      type: 'warning',
      dangerouslyUseHTMLString: true,
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
      inputPlaceholder: key,
      inputValidator: v => (v || '').trim() === key || '输入与模型 Key 不一致',
      inputErrorMessage: '输入与模型 Key 不一致',
    })
  } catch {
    return false            // 取消不是异常，静默返回，别弹错误提示
  }

  try {
    await Api.deleteEntityType(id)
    ElMessage.success(`模型「${name || key}」已移入回收站`)
    return true
  } catch (e) {
    // 错误提示由 axios 拦截器统一处理，这里只需把结果告诉调用方
    return false
  }
}
