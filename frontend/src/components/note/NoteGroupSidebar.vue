<template>
  <!--
    笔记分组侧栏
    ---------------------------------------------------------------------------
    固定宽度 236px（窄屏由父级变成抽屉）。
    结构：全部笔记 / 未分组 / 各分组（带颜色点与笔记数）。
    分组项 hover 出现「⋯」菜单：重命名 · 改颜色 · 删除。
    底部「+ 新建分组」展开内联表单（名称 + 预设色）——
    内联而不是弹窗，是为了让「建组 → 立刻建笔记」这一步不被打断。
  -->
  <aside
    class="ng-sidebar"
    :class="{ 'is-open': open }"
    aria-label="笔记分组"
  >
    <div class="ng-side-head">
      <span class="ng-side-title">分组</span>
      <!-- 分组数是「有几个分组」，跟上面的笔记数不是一回事，
           放在标题后面容易被当成「分组里有多少笔记」 -->
      <span class="ng-side-count">{{ groups.length }} 个</span>
    </div>

    <nav class="ng-side-list" aria-label="分组列表">
      <!-- 全部笔记 -->
      <button
        type="button"
        class="ng-side-item"
        :class="{ 'is-on': modelValue === null }"
        :aria-current="modelValue === null ? 'true' : 'false'"
        @click="pick(null)"
      >
        <el-icon class="ng-side-ico"><Files /></el-icon>
        <span class="ng-side-name">全部笔记</span>
        <span class="ng-side-num">{{ allCount }}</span>
      </button>

      <!-- 「全部 / 未分组」是总览，下面才是真正的分组列表 ——
           用一条分隔线把两层分开，否则「未分组」看起来像个分组 -->
      <div class="ng-side-sep" aria-hidden="true"></div>

      <!-- 未分组：放在分组列表**下面**。
           它是「没有归属」的归集项，不是跟「产品设计」并列的一个组 ——
           放在总览里会让人以为它也是个可管理的分组。 -->
      <button
        type="button"
        class="ng-side-item is-quiet"
        :class="{ 'is-on': modelValue === 0 }"
        :aria-current="modelValue === 0 ? 'true' : 'false'"
        @click="pick(0)"
      >
        <el-icon class="ng-side-ico"><FolderOpened /></el-icon>
        <span class="ng-side-name">未分组</span>
        <span class="ng-side-num">{{ ungroupedCount }}</span>
      </button>

      <!-- 分组列表标题：告诉用户「⋯」那个按钮能干什么 -->
      <div v-if="groups.length" class="ng-side-sub">
        <span>我的分组</span>
        <span class="ng-side-sub-tip">悬停可重命名 / 改颜色</span>
      </div>

      <!-- 各分组 -->
      <div
        v-for="g in groups"
        :key="g.id"
        class="ng-side-row"
        :class="{ 'is-on': modelValue === g.id }"
      >
        <button
          type="button"
          class="ng-side-item is-group"
          :aria-current="modelValue === g.id ? 'true' : 'false'"
          @click="pick(g.id)"
        >
          <span class="ng-dot" :style="{ backgroundColor: g.color }" aria-hidden="true"></span>
          <span class="ng-side-name">{{ g.name }}</span>
          <span class="ng-side-num">{{ countOf(g) }}</span>
        </button>

        <el-dropdown trigger="click" @command="(cmd) => onCommand(cmd, g)">
          <button
            type="button"
            class="ng-side-more"
            :aria-label="`${g.name} 的更多操作`"
            title="更多操作"
            @click.stop
          >
            <el-icon><MoreFilled /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="edit">
                <el-icon><EditPen /></el-icon>重命名 / 改颜色
              </el-dropdown-item>
              <el-dropdown-item command="delete" divided>
                <el-icon><Delete /></el-icon>删除分组
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <!-- 一个分组都没有时给句提示，
           免得侧栏只有「全部 / 未分组」两行，看着像坏了 -->
      <p v-if="!groups.length" class="ng-side-hint">
        还没有分组。<br />按项目、客户或年度建几个，笔记就能各归各位。
      </p>
    </nav>

    <!-- 新建分组：小窗（名称 + 预设色） -->
    <div class="ng-side-foot">
      <button
        type="button"
        class="ng-side-add"
        @click="openCreate"
      >
        <el-icon><Plus /></el-icon>新建分组
      </button>
    </div>

    <el-dialog
      v-model="createOpen"
      title="新建分组"
      width="360px"
      append-to-body
      class="ng-dialog"
      @open="focusCreateName"
    >
      <div class="ng-dialog-body">
        <label class="ng-field">
          <span class="ng-field-label">分组名称</span>
          <input
            ref="nameRef"
            v-model="draftName"
            class="ng-create-name"
            type="text"
            maxlength="40"
            placeholder="分组名称，如「产品设计」（40 字以内）"
            aria-label="分组名称"
            @keydown.esc="createOpen = false"
            @keyup.enter="submitCreate"
          />
        </label>
        <div class="ng-field">
          <span class="ng-field-label">分组颜色</span>
          <div class="ng-create-colors" role="radiogroup" aria-label="分组颜色">
            <button
              v-for="c in GROUP_COLOR_PRESETS"
              :key="c.value"
              type="button"
              class="ng-color"
              :class="{ 'is-on': draftColor === c.value }"
              :style="{ backgroundColor: c.value }"
              :aria-label="`颜色 ${c.label}`"
              :aria-checked="draftColor === c.value"
              role="radio"
              :title="c.label"
              @click="draftColor = c.value"
            ></button>
          </div>
        </div>
        <p v-if="createError" class="ng-create-error" role="alert">{{ createError }}</p>
      </div>
      <template #footer>
        <el-button size="small" @click="createOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑分组：重命名 + 改颜色 -->
    <el-dialog
      v-model="editOpen"
      title="编辑分组"
      width="380px"
      append-to-body
      class="ng-dialog"
    >
      <div class="ng-dialog-body">
        <label class="ng-field">
          <span class="ng-field-label">分组名称</span>
          <el-input
            v-model="editName"
            maxlength="40"
            placeholder="分组名称"
            @keyup.enter="submitEdit"
          />
        </label>
        <div class="ng-field">
          <span class="ng-field-label">分组颜色</span>
          <div class="ng-create-colors" role="radiogroup" aria-label="分组颜色">
            <button
              v-for="c in GROUP_COLOR_PRESETS"
              :key="c.value"
              type="button"
              class="ng-color"
              :class="{ 'is-on': editColor === c.value }"
              :style="{ backgroundColor: c.value }"
              :aria-label="`颜色 ${c.label}`"
              :aria-checked="editColor === c.value"
              role="radio"
              :title="c.label"
              @click="editColor = c.value"
            ></button>
          </div>
        </div>
        <p v-if="editError" class="ng-create-error" role="alert">{{ editError }}</p>
      </div>
      <template #footer>
        <el-button size="small" @click="editOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 删除分组：先说清楚组里的笔记会怎么样 -->
    <el-dialog
      v-model="deleteOpen"
      title="删除分组"
      width="420px"
      append-to-body
      class="ng-dialog"
    >
      <div class="ng-dialog-body">
        <p class="ng-dialog-text">
          确定删除分组「<b>{{ editing?.name }}</b>」吗？
          <span class="ng-dialog-note">
            组里的 <b>{{ editing?.count || 0 }}</b> 篇笔记<b>不会被删除</b>，按下面的选择安置。
          </span>
        </p>
        <el-radio-group v-model="deleteMode" class="ng-radio">
          <el-radio value="ungrouped">移到「未分组」</el-radio>
          <!-- 没有别的分组可选时，别给这个选项：
               选了下拉是空的、提交又报「选一个目标分组」，是条死路 -->
          <el-radio v-if="otherGroups.length" value="move">移到其他分组</el-radio>
        </el-radio-group>
        <el-select
          v-if="deleteMode === 'move'"
          v-model="deleteMoveTo"
          class="ng-select"
          placeholder="选择目标分组"
        >
          <el-option
            v-for="g in otherGroups"
            :key="g.id"
            :value="g.id"
            :label="g.name"
          >
            <span class="ng-opt">
              <span class="ng-dot" :style="{ backgroundColor: g.color }" aria-hidden="true"></span>
              <span class="ng-opt-name">{{ g.name }}</span>
              <span class="ng-opt-num">{{ g.count }}</span>
            </span>
          </el-option>
        </el-select>
        <p v-if="deleteError" class="ng-create-error" role="alert">{{ deleteError }}</p>
      </div>
      <template #footer>
        <el-button size="small" @click="deleteOpen = false">取消</el-button>
        <el-button size="small" type="danger" :loading="saving" @click="submitDelete">删除分组</el-button>
      </template>
    </el-dialog>
  </aside>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, EditPen, Files, FolderOpened, MoreFilled, Plus } from '@element-plus/icons-vue'
import { GROUP_COLOR_PRESETS, validateGroupName } from './group-utils'
import { useNoteGroups } from './useNoteGroups'

const props = defineProps({
  // null = 全部笔记；0 = 未分组；>0 = 具体分组
  modelValue: { type: [Number, null], default: null },
  allCount: { type: Number, default: 0 },
  ungroupedCount: { type: Number, default: 0 },
  // 窄屏抽屉是否展开
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'changed', 'removed', 'navigate'])

const { groups, create, update, remove } = useNoteGroups()

/** 分组下的笔记数：接口直接给（count 数的是记录形态的笔记） */
function countOf(g) {
  return g.count || 0
}

// ---- 新建分组 ----
const createOpen = ref(false)
const draftName = ref('')
const draftColor = ref(GROUP_COLOR_PRESETS[0].value)
const createError = ref('')
const saving = ref(false)
const nameRef = ref(null)

function openCreate() {
  createOpen.value = true
  createError.value = ''
  draftName.value = ''
  draftColor.value = GROUP_COLOR_PRESETS[0].value
}

// 弹窗打开后光标落在名称输入框上（少一次鼠标点击）
function focusCreateName() {
  nextTick(() => nameRef.value?.focus())
}

async function submitCreate() {
  const name = draftName.value.trim()
  const bad = validateGroupName(name, groups.value)
  if (bad) {
    createError.value = bad
    return
  }
  saving.value = true
  createError.value = ''
  try {
    const g = await create({ name, color: draftColor.value })
    ElMessage.success(`分组「${g?.name || name}」已创建`)
    createOpen.value = false
    emit('changed')
  } catch (e) {
    // 409 重名等：就地提示，不静默失败
    createError.value = e?.message || '创建分组失败'
  } finally {
    saving.value = false
  }
}

// ---- 编辑分组（重命名 + 改颜色）----
const editOpen = ref(false)
const editName = ref('')
const editColor = ref('')
const editError = ref('')
const editing = ref(null)

function onCommand(cmd, g) {
  if (cmd === 'edit') {
    editing.value = g
    editName.value = g.name
    editColor.value = g.color
    editError.value = ''
    editOpen.value = true
  } else if (cmd === 'delete') {
    editing.value = g
    deleteMode.value = 'ungrouped'
    deleteMoveTo.value = null
    deleteError.value = ''
    deleteOpen.value = true
  }
}

async function submitEdit() {
  const name = editName.value.trim()
  const bad = validateGroupName(name, groups.value, editing.value?.id)
  if (bad) {
    editError.value = bad
    return
  }
  saving.value = true
  editError.value = ''
  try {
    await update(editing.value.id, { name, color: editColor.value })
    ElMessage.success('已保存')
    editOpen.value = false
    emit('changed')
  } catch (e) {
    editError.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

// ---- 删除分组 ----
const deleteOpen = ref(false)
const deleteMode = ref('ungrouped')
const deleteMoveTo = ref(null)
const deleteError = ref('')

const otherGroups = computed(() => groups.value.filter(g => g.id !== editing.value?.id))

async function submitDelete() {
  if (deleteMode.value === 'move' && !deleteMoveTo.value) {
    // 没有别的分组可选时「移到其他分组」这条路走不通 ——
    // 直接按「移到未分组」处理，别把用户卡在这儿
    if (!otherGroups.value.length) {
      deleteMode.value = 'ungrouped'
    } else {
      deleteError.value = '选一个目标分组'
      return
    }
  }
  saving.value = true
  deleteError.value = ''
  const target = editing.value
  const moveTo = deleteMode.value === 'move' ? deleteMoveTo.value : null
  try {
    await remove(target.id, moveTo)
    ElMessage.success(`分组「${target.name}」已删除，笔记按你的选择安置`)
    deleteOpen.value = false
    // 删掉的正好是当前选中的分组 → 回到「全部笔记」
    if (props.modelValue === target.id) emit('update:modelValue', null)
    // 通知父级：组内笔记的归属后端已经处理好了（记录形态的 data.group_id），
    // 这里只是让父级刷新计数与列表
    emit('removed', { group: target, moveTo })
    emit('changed')
  } catch (e) {
    deleteError.value = e?.message || '删除失败'
  } finally {
    saving.value = false
  }
}

// ---- 选中 ----
function pick(id) {
  emit('update:modelValue', id)
  emit('navigate')
}
</script>

<style scoped>
.ng-sidebar {
  width: 232px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 8px 8px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  align-self: start;
  position: sticky;
  top: var(--space-4);
  /* 分组少的时候侧栏就矮一点 —— 不要撑出一大片空白。
     （原来写死 min-height:320px + 列表 flex:1，
       两个分组也能把每行撑到 111px，一大片空白） */
  max-height: calc(100vh - var(--space-8));
}

.ng-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 8px 8px;
}
.ng-side-title {
  /* 侧栏标题要压得住下面的条目 ——
     原来和条目一样大，看着像又一条导航项 */
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  color: var(--text-tertiary);
}
/* 未分组：弱化一点（它是「没有归属」，不是并列的分组） */
.ng-side-item.is-quiet { color: var(--text-tertiary); }
.ng-side-item.is-quiet .ng-side-ico { opacity: 0.7; }

.ng-side-sep {
  height: 1px;
  background: var(--border-light);
  margin: 7px 8px;
}

.ng-side-sub {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  padding: 2px 8px 4px;
  font-size: 10px;
  /* 不能用 --text-disabled：那是 3.05:1，达不到 4.5:1 的正文对比度。
     这行是给用户看的说明文字，不是装饰。 */
  color: var(--text-tertiary);
  letter-spacing: 0.2px;
}
.ng-side-sub-tip {
  font-size: 10px;
  color: var(--text-tertiary);
}

.ng-side-hint {
  margin: 10px 8px 4px;
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-tertiary);
}

.ng-side-count {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.ng-side-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow-y: auto;
  /* 不要 flex:1 —— 分组少的时候会把每一行拉高撑出一片空白 */
  flex: 0 1 auto;
  min-height: 0;
}

.ng-side-row {
  position: relative;
  display: flex;
  align-items: center;
  border-radius: var(--radius-sm);
}
.ng-side-row:hover { background: var(--bg-subtle); }
.ng-side-row.is-on { background: var(--primary-bg); }
.ng-side-row.is-on::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 2px;
  border-radius: 2px;
  background: var(--primary);
}

.ng-side-item {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 8px;
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  text-align: left;
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast);
}
.ng-side-item:hover { background: var(--bg-subtle); color: var(--text-primary); }
.ng-side-row.is-on .ng-side-item { color: var(--primary-dark); font-weight: 600; }
html.dark .ng-side-row.is-on .ng-side-item { color: var(--primary-light); }
.ng-side-ico { color: var(--text-tertiary); flex-shrink: 0; }
.ng-side-row.is-on .ng-side-ico { color: var(--primary); }
/* 分组名：条目里最重要的信息，字要够重 */
.ng-side-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ng-side-num {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ng-side-row.is-on .ng-side-num { color: var(--primary); }

.ng-dot {
  /* 色点是这个分组唯一的身份标识，要看得见：
     9px 太小，10px + 一圈同底色的描边才既清楚又不会糊在文字上 */
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 2px var(--bg-card);
}

.ng-side-more {
  width: 24px;
  height: 24px;
  margin-right: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  border-radius: var(--radius-xs);
  cursor: pointer;
  opacity: 0;
  transition: opacity var(--duration-fast), color var(--duration-fast), background var(--duration-fast);
}
.ng-side-row:hover .ng-side-more,
.ng-side-row.is-on .ng-side-more { opacity: 1; }
.ng-side-more:hover { background: var(--bg-sunken); color: var(--text-primary); }
.ng-side-more:focus-visible { opacity: 1; }

.ng-side-foot {
  border-top: 1px solid var(--border-light);
  padding-top: 8px;
  margin-top: 6px;
}
.ng-side-add {
  width: 100%;
  height: 30px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast), color var(--duration-fast);
}
.ng-side-add:hover { background: var(--bg-subtle); color: var(--primary-dark); }
html.dark .ng-side-add:hover { color: var(--primary-light); }

/* 名称输入框（新建 / 编辑分组用） */
.ng-create-name {
  width: 100%;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: var(--text-sm);
  outline: none;
}
.ng-create-name:focus-visible {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-ring);
}
.ng-create-colors {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ng-color {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
  transition: transform var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast);
}
.ng-color:hover { transform: scale(1.12); }
.ng-color.is-on {
  box-shadow: 0 0 0 2px var(--bg-card), 0 0 0 4px var(--primary);
}
.ng-create-error {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--danger);
  line-height: 1.5;
}
/* 弹窗 */
.ng-dialog-body { display: flex; flex-direction: column; gap: 12px; }
.ng-field { display: flex; flex-direction: column; gap: 6px; }
.ng-field-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: 500;
}
.ng-dialog-text {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--text-primary);
}
.ng-dialog-note {
  display: block;
  margin-top: 4px;
  color: var(--text-secondary);
}
.ng-radio { display: flex; flex-direction: column; gap: 6px; }
.ng-select { width: 100%; }
.ng-opt { display: flex; align-items: center; gap: 8px; }
.ng-opt-name { flex: 1; }
.ng-opt-num { font-size: var(--text-xs); color: var(--text-tertiary); }
</style>
