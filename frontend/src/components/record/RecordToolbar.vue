<template>
  <!--
    记录区工具条：筛选器 + 列显示设置 + 视图切换
    ---------------------------------------------------------------------------
    为什么抽成一个组件：「记录页」和「应用独立页」进的是同一份数据，
    但以前两边的筛选器、列设置、视图切换各写一遍，用户会发现「换个入口功能就没了」。
    现在两页共用这一个工具条，能力与手感完全一致。
  -->
  <div class="rt-toolbar">
    <!-- 筛选器：只对枚举 / 布尔字段有意义（文本字段用上面的关键词搜更合适） -->
    <el-popover v-if="filterFields.length" placement="bottom-end" :width="280" trigger="click"
      popper-class="rt-popper">
      <template #reference>
        <el-button class="rt-btn" aria-label="筛选">
          <el-icon><Filter /></el-icon>筛选
          <span v-if="activeFilterCount" class="rt-badge">{{ activeFilterCount }}</span>
        </el-button>
      </template>
      <div class="rt-filters">
        <div v-for="f in filterFields" :key="f.key" class="rt-filter">
          <div class="rt-filter-label">{{ f.name }}</div>
          <el-select
            v-if="f.type === 'boolean'"
            v-model="innerFilters[f.key]"
            clearable
            placeholder="全部"
            @change="onFilterChange"
          >
            <el-option label="是" :value="true" />
            <el-option label="否" :value="false" />
          </el-select>
          <el-select
            v-else
            v-model="innerFilters[f.key]"
            clearable
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="全部"
            @change="onFilterChange"
          >
            <el-option
              v-for="c in choicesMap[f.key] || []"
              :key="c"
              :label="c"
              :value="c"
            />
          </el-select>
        </div>
        <div v-if="activeFilterCount" class="rt-filter-clear">
          <el-button text @click="clearFilters">清空筛选</el-button>
        </div>
      </div>
    </el-popover>

    <!-- 列显示设置 -->
    <el-popover placement="bottom-end" :width="230" trigger="click" popper-class="rt-popper">
      <template #reference>
        <el-button class="rt-btn" aria-label="列显示设置">
          <el-icon><Operation /></el-icon>列
        </el-button>
      </template>
      <div class="rt-cols">
        <div class="rt-cols-title">显示哪些字段</div>
        <!-- 要套 el-checkbox-group：el-checkbox 单独用时 modelValue
             只接受 Boolean/String/Number，绑数组虽然运行时能用
             （Element Plus 内部会 includes 判断），但类型不对，
             每次进页面刷一堆 Vue 警告。官方写法就是套一层 group。 -->
        <el-checkbox-group v-model="innerKeys" class="rt-col-group">
          <el-checkbox
            v-for="f in displayFields"
            :key="f.key"
            :value="f.key"
            class="rt-col-item"
          >{{ f.name }}</el-checkbox>
        </el-checkbox-group>
        <div v-if="!displayFields.length" class="rt-cols-empty">这个模型还没有字段</div>
        <div v-if="displayFields.length" class="rt-cols-actions">
          <el-button text @click="selectAll">全选</el-button>
          <el-button text @click="selectDefault">恢复默认</el-button>
        </div>
      </div>
    </el-popover>

    <!-- 表格 / 卡片 -->
    <el-segmented v-model="innerViewMode" :options="viewOptions" class="rt-view" />

    <!-- 批量操作：选中记录后出现 -->
    <transition name="rt-fade">
      <div v-if="selectedCount" class="rt-batch">
        <span class="rt-batch-count">已选 {{ selectedCount }} 条</span>
        <el-button size="small" @click="$emit('clear-selection')">取消选择</el-button>
        <el-button size="small" type="danger" plain :disabled="!canManage" @click="$emit('batch-remove')">
          <el-icon><Delete /></el-icon>批量删除
        </el-button>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Delete, Filter, Operation } from '@element-plus/icons-vue'

const props = defineProps({
  /** 可筛选的字段（枚举 / 布尔） */
  filterFields: { type: Array, default: () => [] },
  /** 每个选择字段的候选项 */
  choicesMap: { type: Object, default: () => ({}) },
  /** 可显示成列的字段 */
  displayFields: { type: Array, default: () => [] },
  /** 筛选条件（v-model:filters） */
  filters: { type: Object, default: () => ({}) },
  /** 勾选显示的列（v-model:visibleKeys） */
  visibleKeys: { type: Array, default: () => [] },
  /** 视图：table / card（v-model:viewMode） */
  viewMode: { type: String, default: 'table' },
  /** 已选中的记录数 */
  selectedCount: { type: Number, default: 0 },
  canManage: { type: Boolean, default: true },
  /** 恢复默认列时用到的默认 key 列表 */
  defaultKeys: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'update:filters', 'update:visibleKeys', 'update:viewMode',
  'change', 'clear-filters', 'batch-remove', 'clear-selection',
])

const viewOptions = [
  { label: '表格', value: 'table' },
  { label: '卡片', value: 'card' },
]

// 本地副本：筛选器里的 el-select 直接改它，改完同步给父组件
// （直接改 props 里的对象会触发 Vue 的「不要直接改 prop」警告）
const innerFilters = ref({ ...(props.filters || {}) })
const innerKeys = ref([...(props.visibleKeys || [])])
const innerViewMode = ref(props.viewMode)

// 父组件换模型时（筛选条件被清空）要把本地副本同步过去
watch(() => props.filters, v => {
  innerFilters.value = { ...(v || {}) }
}, { deep: true })
watch(() => props.visibleKeys, v => {
  const next = [...(v || [])]
  if (next.join('|') !== innerKeys.value.join('|')) innerKeys.value = next
}, { deep: true })
watch(() => props.viewMode, v => {
  if (v !== innerViewMode.value) innerViewMode.value = v
})

function onFilterChange() {
  emit('update:filters', { ...innerFilters.value })
  emit('change')
}

function clearFilters() {
  innerFilters.value = {}
  emit('update:filters', {})
  emit('clear-filters')
  emit('change')
}

watch(innerKeys, v => {
  emit('update:visibleKeys', [...v])
}, { deep: true })

watch(innerViewMode, v => {
  emit('update:viewMode', v)
})

function selectAll() {
  innerKeys.value = props.displayFields.map(f => f.key)
}

function selectDefault() {
  innerKeys.value = [...props.defaultKeys]
}

const activeFilterCount = computed(() => Object.values(props.filters || {}).filter(v =>
  v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length)).length)
</script>

<style scoped>
.rt-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap; /* 窄屏时按钮换行，而不是把搜索框挤出屏幕 */
}

.rt-btn { flex: none; }

/* 生效中的筛选条件数量：直接压在按钮上，用户不用点开才知道有筛选 */
.rt-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
}

.rt-filters {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 320px;
  overflow-y: auto;
}
.rt-filter { display: flex; flex-direction: column; gap: 6px; }
.rt-filter-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
}
.rt-filter-clear { text-align: right; }

.rt-cols { display: flex; flex-direction: column; gap: 8px; }
.rt-cols-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
}
.rt-col-group {
  display: flex;
  flex-direction: column;
  max-height: 260px;
  overflow-y: auto;
}
.rt-col-item { height: 28px; }
.rt-cols-empty {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.rt-cols-actions {
  display: flex;
  justify-content: space-between;
  border-top: 1px solid var(--border-light);
  padding-top: 6px;
}

/* 批量操作条 */
.rt-batch {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
}
.rt-batch-count {
  font-size: var(--text-sm);
  color: var(--primary);
  font-weight: 600;
}

/* 弹层内容被 teleport 到 body，scoped 选择器够不着，
   所以用 popper-class 精确限定到本组件的弹层，再在弹层里改占位符颜色。
   为什么改：Element Plus 的占位符用的是 --text-disabled（对比度 3.05:1），
   「全部」两个字在白底上几乎看不清 —— 占位符也是要读的字。 */
:global(.rt-popper) {
  --el-text-color-placeholder: var(--text-tertiary);
}

.rt-fade-enter-active, .rt-fade-leave-active { transition: opacity var(--duration-fast) var(--ease-out); }
.rt-fade-enter-from, .rt-fade-leave-to { opacity: 0; }
</style>
