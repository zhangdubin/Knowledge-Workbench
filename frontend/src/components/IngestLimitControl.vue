<template>
  <div class="ingest-limit">
    <span class="il-label">
      <el-icon><UploadFilled /></el-icon>上传总量上限
      <el-tooltip :content="help" placement="top">
        <el-icon class="il-info"><InfoFilled /></el-icon>
      </el-tooltip>
    </span>
    <!-- 上界必须用 hardMax（允许的上限），不能用 max（当前生效值）：
         用当前值当上界的话，用户根本没法把 256 往上调 ——
         输进去的每一个更大的数都会被组件悄悄夹回 256。 -->
    <el-input-number
      v-model="draft"
      :min="min"
      :max="hardMax"
      :step="64"
      size="small"
      controls-position="right"
      class="il-num"
      @change="onDraftChange"
    />
    <span class="il-unit">MB</span>
    <!-- 按钮文字保持不变：文字一变，自动化脚本与习惯用肌肉记忆的人都会扑空 -->
    <el-button size="small" :loading="saving" :disabled="!dirty || failed" @click="save">
      保存上限
    </el-button>
    <span v-if="failed" class="il-warn">
      读不到当前上限（接口没通），先别调 —— 刷新页面重试
    </span>
    <span v-else-if="overBy" class="il-warn">
      已选 {{ sizeMb }} MB，超出上限 {{ overBy }} MB —— 调大上限或少选一些
    </span>
    <span v-else-if="dirty" class="il-hint">
      保存后上限变成 {{ draft }} MB
    </span>
    <span v-else class="il-ok">
      当前上限 {{ max }} MB<template v-if="sizeMb"> · 已选 {{ sizeMb }} MB，在上限之内</template>
    </span>
  </div>
</template>

<script setup>
/**
 * 源码树上传的「总量上限」调节
 *
 * 为什么上限要能调：
 *   源码树是「拿来蒸馏成基因、原文用完即删」的东西，
 *   但真实仓库动辄几百 MB —— 上限写死 256 MB 就只能让人分批上传，
 *   而分批之后「同一个系统的全貌」被切碎，基因之间的关联也就断了。
 *
 * 为什么单独做成组件而不是直接写在养料库页面里：
 *   这个上限同时影响「整系统源码树」与「单个大文件」两条路，
 *   放在组件里只维护一份取数与保存逻辑。
 *
 * 生效方式是**立刻**的：上限存在后端的 sys_meta 里，
 * 下一个请求就按新值判定，不需要重启容器。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
// 注意：api/index.js 里 default 导出的是 axios 实例本身，
// 接口集合是具名导出 Api —— 写成 default 导入会拿到 axios 实例，
// 于是 Api.dnaLibraryLimits 是 undefined，
// 而下面那个 catch 又会把异常吞掉，界面看着「正常」，其实一条请求都没发。
import { Api } from '../api'

const props = defineProps({
  /** 当前已选文件的总大小（MB）；用于提前提示「超了」 */
  sizeMb: { type: Number, default: 0 },
})

const max = ref(256)
const min = ref(16)
const hardMax = ref(4096)
const draft = ref(256)
const saving = ref(false)
const loaded = ref(false)
// 读不到当前上限时为 true：界面明说「读不到」，而不是假装上限是默认值
const failed = ref(false)

const dirty = computed(() => loaded.value && draft.value !== max.value)

/** 超出的量（MB）；没超就是 0 */
const overBy = computed(() => {
  const over = Number(props.sizeMb || 0) - max.value
  return over > 0 ? Math.round(over) : 0
})

const help = computed(() => {
  return `一次「源码树」上传允许的总大小，当前 ${max.value} MB，可调范围 ${min.value} ~ ${hardMax.value} MB。
调大之前先看两件事：① nginx 的 client_max_body_size（默认 4096m）不能比它小，否则会被 nginx 先挡掉；
② 上传期间文件会完整落在暂存区，磁盘要放得下。`
})

async function load() {
  try {
    const r = await Api.dnaLibraryLimits()
    const l = (r && r.limits) || {}
    max.value = Number(l.max_total_mb || 256)
    min.value = Number(l.min_total_mb || 16)
    hardMax.value = Number(l.max_total_mb_limit || 4096)
    draft.value = max.value
    loaded.value = true
    failed.value = false
  } catch (e) {
    // 读不到就不能装作「当前上限是 256」——
    // 那会让用户以为改不动，其实是一条请求都没发出去。
    // 这里明说读失败，并让输入框变灰。
    failed.value = true
    loaded.value = true
  }
}

function onDraftChange(v) {
  if (v === null || v === undefined) draft.value = max.value
}

async function save() {
  const mb = Number(draft.value)
  if (!Number.isFinite(mb) || mb < min.value || mb > hardMax.value) {
    ElMessage.error(`上限取值范围 ${min.value} ~ ${hardMax.value} MB`)
    draft.value = max.value
    return
  }
  saving.value = true
  try {
    const r = await Api.dnaLibrarySetLimits(mb)
    const applied = Number((r && r.limits && r.limits.max_total_mb) || mb)
    max.value = applied
    draft.value = applied
    ElMessage.success(`上传总量上限已改成 ${applied} MB`)
  } catch (e) {
    draft.value = max.value
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ingest-limit {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 7px 11px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  font-size: 12px;
  color: var(--text-secondary);
}
.il-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: var(--text-primary);
}
.il-info {
  color: var(--text-disabled);
  cursor: help;
}
.il-num { width: 116px; }
.il-unit { color: var(--text-tertiary); }
.il-warn {
  color: var(--warning-text);
  background: var(--warning-bg);
  border-radius: var(--radius-full);
  padding: 1px 9px;
}
.il-hint { color: var(--text-tertiary); }
.il-ok { color: var(--text-tertiary); }
</style>
