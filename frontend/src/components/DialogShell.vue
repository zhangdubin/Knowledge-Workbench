<template>
  <el-dialog
    v-model="visible"
    class="dialog-shell"
    :class="[`is-size-${size}`, { 'is-busy': loading }]"
    :width="shellWidth"
    :close-on-click-modal="closeOnClickModal"
    :close-on-press-escape="closeOnPressEscape"
    :destroy-on-close="destroyOnClose"
    :append-to-body="appendToBody"
    :show-close="showClose"
    @open="$emit('open')"
    @close="$emit('close')"
    @closed="$emit('closed')"
  >
    <template #header>
      <div class="shell-header">
        <span v-if="$slots.icon" class="shell-header-icon">
          <slot name="icon" />
        </span>
        <div class="shell-header-text">
          <h3 class="shell-title">{{ title }}</h3>
          <!-- 描述放在标题下面而不是正文里：正文区是表单的地盘，
               把说明混进去会被当成表单字段的一部分 -->
          <p v-if="description" class="shell-desc">{{ description }}</p>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="shell-body" :class="{ 'is-loading': loading }">
      <slot />
    </div>

    <template v-if="$slots.footer || $slots['footer-start']" #footer>
      <div class="shell-footer">
        <!-- 破坏性操作单独占位：推到最左，和主按钮拉开距离。
             并排时用户会在两个高饱和按钮之间反复犹豫该按哪个 -->
        <div class="shell-footer-extra">
          <slot name="footer-start" />
        </div>
        <div class="shell-footer-actions">
          <slot name="footer" />
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 统一弹窗外壳
 *
 * 为什么要有这个组件：项目里二十来处 el-dialog 各自写着标题、正文、
 * 底部按钮，间距和按钮顺序各不相同 —— 同一个「确认」按钮在 A 页面在左、
 * 在 B 页面在右。这个组件把外壳（标题 / 描述 / 正文 / 底部动作区 / 尺寸）
 * 固定下来，业务代码只关心内容。
 *
 * 用法：
 *   <DialogShell v-model="open" title="编辑模型" description="改完记得保存" size="md">
 *     <el-form>…</el-form>
 *     <template #footer>
 *       <el-button @click="open = false">取消</el-button>
 *       <el-button type="primary" @click="save">保存</el-button>
 *     </template>
 *   </DialogShell>
 */
import { computed } from 'vue'
import { dialogWidth } from '../utils/ui'

const props = defineProps({
  /** v-model：控制弹窗开关 */
  modelValue: { type: Boolean, default: false },
  /** 标题（一级） */
  title: { type: String, default: '' },
  /** 描述（标题下方的灰色说明，可选） */
  description: { type: String, default: '' },
  /** 尺寸档位：sm 确认框 / md 标准表单 / lg 表格 / xl 宽表格 */
  size: {
    type: String,
    default: 'md',
    validator: v => ['sm', 'md', 'lg', 'xl'].includes(v),
  },
  /** 显式宽度（给了就覆盖 size 档位；数字按 px，字符串原样用，如 '50%'） */
  width: { type: [String, Number], default: '' },
  /** 加载态：正文盖 loading 遮罩 */
  loading: { type: Boolean, default: false },
  /** 点遮罩关闭：表单类弹窗建议保持 false，避免误触丢数据 */
  closeOnClickModal: { type: Boolean, default: false },
  /** ESC 关闭 */
  closeOnPressEscape: { type: Boolean, default: true },
  /** 关闭时销毁内容（省内存，但会重置内部状态） */
  destroyOnClose: { type: Boolean, default: false },
  /** 挂到 body 上，避免被父级 overflow 裁掉 */
  appendToBody: { type: Boolean, default: true },
  /** 显示右上角关闭按钮 */
  showClose: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'open', 'close', 'closed'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const shellWidth = computed(() => dialogWidth(props.size, props.width))
</script>

<style scoped>
.shell-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  min-width: 0;
}
.shell-header-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  font-size: 17px;
}
.shell-header-text { min-width: 0; }
.shell-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 650;
  line-height: 1.4;
  letter-spacing: -0.3px;
  color: var(--text-primary);
}
.shell-desc {
  margin: 6px 0 0;
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--text-tertiary);
}

.shell-body {
  color: var(--text-secondary);
  line-height: 1.65;
  /* 长表单在视口内自己滚，底部动作区始终可见 ——
     否则内容一长，「保存」按钮会被顶到屏幕外面 */
  max-height: calc(100vh - 260px);
  overflow-y: auto;
  scrollbar-width: thin;
}
.shell-body.is-loading { min-height: 120px; }

.shell-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  width: 100%;
}
.shell-footer-extra {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  /* 破坏性按钮靠左，不跟主按钮并排 */
  margin-right: auto;
}
.shell-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}
/* 主按钮在最右：视线自然落在「确认」上 */
.shell-footer-actions :deep(.el-button + .el-button) { margin-left: 0; }

@media (max-width: 768px) {
  .shell-body { max-height: calc(100vh - 220px); }
  .shell-footer { flex-wrap: wrap; }
  .shell-footer-actions { width: 100%; }
}
</style>
