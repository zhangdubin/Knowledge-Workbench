<template>
  <el-dialog
    :model-value="modelValue"
    title="添加关联"
    width="620px"
    class="rich-dialog"
    :close-on-click-modal="false"
    @update:model-value="v => emit('update:modelValue', v)"
    @open="reset"
  >
    <div class="rl-steps">
      <div class="rl-step" :class="{ on: step === 1, done: step > 1 }">
        <span class="rs-no">1</span>选择关联定义
      </div>
      <div class="rl-line" />
      <div class="rl-step" :class="{ on: step === 2 }">
        <span class="rs-no">2</span>选择另一端
      </div>
    </div>

    <!-- 第一步：选定义 -->
    <template v-if="step === 1">
      <div class="dialog-summary">
        <el-icon :size="18"><Connection /></el-icon>
        <span>
          当前{{ selfKind === 'document' ? '文件' : '记录' }}是
          <strong>{{ selfLabel || `#${selfId}` }}</strong>。
          选一条关联定义，再挑出要连过去的对象。
        </span>
      </div>
      <div v-if="eligible.length" class="rl-defs">
        <button v-for="d in eligible" :key="d.id" class="rl-def" @click="chooseDef(d)">
          <span class="rd-name">{{ d.name }}</span>
          <span class="rd-dir">
            <em>{{ d.source_icon || '📦' }} {{ d.source_label }}</em>
            <el-icon :size="12"><Right /></el-icon>
            <em class="tgt">{{ d.target_icon || '📦' }} {{ d.target_label }}</em>
          </span>
          <span class="rd-meta">
            {{ cardLabel(d.cardinality) }} · 已有 {{ d.link_count || 0 }} 条关联
          </span>
        </button>
      </div>
      <div v-else class="rl-empty">
        <el-icon :size="26"><Connection /></el-icon>
        <div class="re-title">没有可用的关联定义</div>
        <div class="re-desc">
          需要先到「关联定义」里，把「数据中心文件」和某个业务模型连起来。
        </div>
      </div>
    </template>

    <!-- 第二步：选另一端 -->
    <template v-else>
      <div class="rl-head">
        <el-button size="small" link @click="step = 1">
          <el-icon><ArrowLeft /></el-icon>换一条定义
        </el-button>
        <span class="rl-def-name">{{ pickedDef.name }}</span>
      </div>

      <div v-if="sides.length > 1" class="rl-side">
        <span class="side-label">当前{{ selfKind === 'document' ? '文件' : '记录' }}作为</span>
        <el-radio-group v-model="selfSide" size="small" @change="loadCandidates">
          <el-radio-button value="source">源端</el-radio-button>
          <el-radio-button value="target">目标端</el-radio-button>
        </el-radio-group>
        <span class="side-hint">{{ sideHint }}</span>
      </div>

      <el-input v-model="keyword" clearable placeholder="按名称搜索…"
                @input="onSearch" @clear="loadCandidates">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <div v-loading="loadingCands" class="rl-cands">
        <button v-for="c in candidates" :key="c.id" class="rl-cand"
                :class="{ on: picked?.id === c.id }" @click="picked = c">
          <span class="rc-label">{{ c.label }}</span>
          <span class="rc-sub">{{ c.sub }}</span>
          <el-icon v-if="picked?.id === c.id" class="rc-check" :size="15"><Select /></el-icon>
        </button>
        <div v-if="!loadingCands && !candidates.length" class="rl-empty small">
          <div class="re-desc">
            {{ keyword ? '没有匹配的结果' : '这一端还没有可关联的对象' }}
          </div>
        </div>
      </div>
    </template>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button v-if="step === 2" type="primary" :loading="saving" :disabled="!picked"
                 @click="submit">
        <el-icon><Link /></el-icon>建立关联
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 通用「添加关联」弹窗
 *
 * 记录详情与文件详情共用：调用方只需要给出「自己是谁」（selfKind + selfId）
 * 和一份关联定义清单，剩下的方向判断、候选拉取、payload 组装都在这里，
 * 页面不必各自判断 source/target 与 record/document 的组合。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  defs: { type: Array, default: () => [] },
  selfKind: { type: String, default: 'record' },   // record | document
  selfId: { type: [Number, String], default: null },
  selfLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'linked'])

const CARD_LABELS = {
  'many-to-many': '多对多', 'one-to-many': '一对多',
  'many-to-one': '多对一', 'one-to-one': '一对一',
}
const cardLabel = (c) => CARD_LABELS[c] || c || '多对多'

const step = ref(1)
const pickedDef = ref(null)
const selfSide = ref('source')
const keyword = ref('')
const candidates = ref([])
const picked = ref(null)
const loadingCands = ref(false)
const saving = ref(false)

const eligible = computed(() => props.defs.filter(d =>
  d.source_kind === props.selfKind || d.target_kind === props.selfKind))

/** 这条定义里，哪些端与本体的 kind 一致（两端同 kind 时要让用户指定方向） */
const sides = computed(() => {
  const d = pickedDef.value
  if (!d) return []
  return ['source', 'target'].filter(s => d[`${s}_kind`] === props.selfKind)
})

const otherSide = computed(() => (selfSide.value === 'source' ? 'target' : 'source'))
const otherKind = computed(() => pickedDef.value?.[`${otherSide.value}_kind`] || 'record')

const sideHint = computed(() => (
  otherKind.value === 'document' ? '另一端是文件' : '另一端是业务记录'
))

function reset() {
  step.value = 1
  pickedDef.value = null
  selfSide.value = 'source'
  keyword.value = ''
  candidates.value = []
  picked.value = null
}

function chooseDef(d) {
  pickedDef.value = d
  // 两端同 kind 时默认把本体当源端（多数定义的语义是 A 属于 B）
  selfSide.value = (d.source_kind === props.selfKind) ? 'source' : 'target'
  step.value = 2
  loadCandidates()
}

let timer = null
function onSearch() {
  clearTimeout(timer)
  timer = setTimeout(loadCandidates, 280)
}

async function loadCandidates() {
  if (!pickedDef.value) return
  loadingCands.value = true
  picked.value = null
  try {
    const r = await Api.relationPick(pickedDef.value.id, otherSide.value, keyword.value)
    candidates.value = r.items || []
  } catch (e) {
    candidates.value = []
  } finally {
    loadingCands.value = false
  }
}

async function submit() {
  if (!picked.value || !pickedDef.value) return
  const payload = { relation_def_id: pickedDef.value.id }
  // 字段名由「端 + 类型」拼出：source_record_id / target_document_id …
  payload[`${selfSide.value}_${props.selfKind}_id`] = Number(props.selfId)
  payload[`${otherSide.value}_${otherKind.value}_id`] = picked.value.id
  saving.value = true
  try {
    await Api.createRelationRecord(payload)
    ElMessage.success('已建立关联')
    emit('update:modelValue', false)
    emit('linked')
  } catch (e) { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.rl-steps { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.rl-step {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: var(--text-sm); color: var(--text-tertiary); font-weight: 600;
}
.rl-step.on { color: var(--primary); }
.rl-step.done { color: var(--success); }
.rs-no {
  width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: var(--text-xs); background: var(--bg-sunken); color: var(--text-tertiary);
}
.rl-step.on .rs-no { background: var(--primary); color: #fff; }
.rl-step.done .rs-no { background: var(--success); color: #fff; }
.rl-line { flex: 1; height: 1px; background: var(--border); max-width: 60px; }

.rl-defs { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow: auto; }
.rl-def {
  display: grid; grid-template-columns: 1fr auto; gap: 4px 12px;
  align-items: center; text-align: left; width: 100%;
  padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); cursor: pointer; font-family: inherit;
  transition: all var(--duration) var(--ease-out);
}
.rl-def:hover { border-color: var(--primary); background: var(--primary-bg); }
.rd-name { font-size: var(--text-base); font-weight: 650; color: var(--text-primary); }
.rd-dir {
  grid-row: 2; grid-column: 1 / -1;
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--text-sm); color: var(--text-tertiary);
}
.rd-dir em { font-style: normal; }
.rd-dir em.tgt { color: var(--primary); }
.rd-meta { grid-row: 3; grid-column: 1 / -1; font-size: var(--text-xs); color: var(--text-disabled); }

.rl-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.rl-def-name { font-size: var(--text-base); font-weight: 650; color: var(--text-primary); }

.rl-side { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.side-label { font-size: var(--text-sm); color: var(--text-secondary); }
.side-hint { font-size: var(--text-xs); color: var(--text-tertiary); }

.rl-cands {
  margin-top: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  max-height: 300px; overflow: auto; min-height: 96px; background: var(--bg-card);
}
.rl-cand {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 10px 13px; border: none; border-bottom: 1px solid var(--border-light);
  background: transparent; cursor: pointer; font-family: inherit; text-align: left;
  transition: background var(--duration) var(--ease-out);
}
.rl-cand:last-child { border-bottom: none; }
.rl-cand:hover { background: var(--bg-subtle); }
.rl-cand.on { background: var(--primary-bg); }
.rc-label { flex: 1; font-size: var(--text-base); color: var(--text-primary); min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rc-sub { font-size: var(--text-xs); color: var(--text-tertiary); flex-shrink: 0; }
.rc-check { color: var(--primary); flex-shrink: 0; }

.rl-empty { text-align: center; padding: 32px 20px; color: var(--text-tertiary); }
.rl-empty .el-icon { color: var(--text-disabled); margin-bottom: 10px; }
.rl-empty.small { padding: 24px 16px; }
.re-title { font-size: var(--text-base); font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; }
.re-desc { font-size: var(--text-sm); line-height: 1.65; }
</style>
