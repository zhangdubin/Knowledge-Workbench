<template>
  <section class="stage-panel">
    <header class="panel-head">
      <div class="panel-head-main">
        <h3 class="panel-title">{{ stageMeta('clarify').title }}</h3>
        <p class="panel-sub">{{ stageMeta('clarify').subtitle }}</p>
      </div>
      <div class="panel-ops">
        <el-button
          v-if="stage?.status === 'pending' || !stage"
          type="primary"
          :loading="busy"
          @click="$emit('run')"
        >
          <el-icon><Aim /></el-icon>{{ stageMeta('clarify').action }}
        </el-button>
        <el-button
          v-else
          :loading="busy"
          @click="$emit('run', { force: true })"
        >
          <el-icon><Refresh /></el-icon>{{ stageMeta('clarify').rerun }}
        </el-button>
      </div>
    </header>

    <!-- 还没跑：先讲清楚这一步是干什么的 -->
    <EmptyState
      v-if="!stage || stage.status === 'pending'"
      icon="Aim"
      title="第一步：让模型先读懂你的需求"
      description="模型会结合你喂养的源码知识，写出它对需求的理解，并提出它无法替你决定的问题。"
    />

    <!-- 正在跑 -->
    <div v-else-if="stage.status === 'running'" class="panel-state">
      <el-skeleton :rows="4" animated />
      <p class="panel-state-note">正在理解需求…</p>
    </div>

    <!-- 失败：必须让人看见原因 -->
    <div v-else-if="stage.status === 'failed'" class="panel-state is-failed">
      <el-alert type="error" :closable="false" show-icon title="这一步失败了">
        <div class="fail-line">{{ stage.error || '后端没有给出失败原因' }}</div>
        <div v-if="fixList.length" class="fail-line">
          建议：{{ fixList.join('；') }}
        </div>
      </el-alert>
      <el-button type="primary" :loading="busy" @click="$emit('run', { force: true })">
        重试这一步
      </el-button>
    </div>

    <!-- 有产出 -->
    <template v-else>
      <!-- 需求理解摘要 -->
      <div class="block">
        <div class="block-head">
          <span class="block-title">需求理解摘要</span>
        </div>
        <p class="understanding">{{ understanding || '（后端没有给出理解摘要）' }}</p>
        <div v-if="assumptions.length" class="assumptions">
          <div class="block-subtitle">我们默认了这些（不对就推翻它）</div>
          <ul class="plain-list">
            <li v-for="(a, i) in assumptions" :key="i">{{ a }}</li>
          </ul>
        </div>
      </div>

      <!-- 澄清问题 -->
      <div class="block">
        <div class="block-head">
          <span class="block-title">澄清问题</span>
          <span class="block-note">
            {{ questions.length ? '这些必须由你回答，模型替你猜不得' : '模型认为需求已经够清楚，无需澄清' }}
          </span>
        </div>

        <EmptyState
          v-if="!questions.length"
          compact
          icon="CircleCheck"
          title="无需澄清"
          description="模型没有提出必须由人回答的问题，可以直接进入下一阶段。"
        />

        <div v-else class="q-list">
          <div v-for="(q, i) in questions" :key="q.id || i" class="q-item">
            <div class="q-head">
              <span class="q-index">Q{{ i + 1 }}</span>
              <span class="q-text">{{ q.question }}</span>
            </div>
            <div v-if="q.why" class="q-why">为什么要问这个：{{ q.why }}</div>
            <el-radio-group
              v-if="q.options.length"
              v-model="answers[q.id]"
              class="q-options"
            >
              <el-radio v-for="opt in q.options" :key="opt" :value="opt" class="q-option">
                {{ opt }}
              </el-radio>
            </el-radio-group>
            <el-input
              v-if="q.allow_free"
              v-model="freeText[q.id]"
              class="q-free"
              size="small"
              placeholder="也可以自己写（选了上面的选项就留空）"
            />
          </div>
        </div>
      </div>

      <!-- 提交 -->
      <div class="panel-foot">
        <span class="foot-note">
          <template v-if="missingCount">
            还有 {{ missingCount }} 个问题没回答
          </template>
          <template v-else-if="questions.length">都答完了，可以提交</template>
          <template v-else>需求已澄清，可以进入下一阶段</template>
        </span>
        <el-button
          type="primary"
          :loading="busy"
          :disabled="!!missingCount"
          @click="submit"
        >
          提交答案并继续
        </el-button>
      </div>
    </template>
  </section>
</template>

<script setup>
/**
 * 阶段一：需求理解（clarify）
 *
 * 这一阶段的产物是「模型的理解」+「它提出的澄清问题」。
 * 契约里 questions 为空是**合法状态**（模型认为需求够清楚），
 * 所以界面上要说「无需澄清」，不能当成出错空着。
 *
 * 澄清问题必须由人回答 —— 这是整条流水线的入口闸门，
 * 因此提交按钮在还有问题没答时是禁用的（而不是提交了再报错）。
 */
import { computed, reactive, ref, watch } from 'vue'
import EmptyState from '../../components/EmptyState.vue'
import { stageMeta, clarifyQuestions } from '../../utils/dev.js'

const props = defineProps({
  stage: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['run', 'submit'])

const answers = reactive({})
const freeText = reactive({})

const questions = computed(() => clarifyQuestions(props.stage?.data))

const understanding = computed(() => String(props.stage?.data?.understanding || ''))

const assumptions = computed(() => {
  const list = props.stage?.data?.assumptions
  return Array.isArray(list) ? list : []
})

const fixList = computed(() => {
  const raw = props.stage?.how_to_fix
  if (Array.isArray(raw)) return raw
  return []
})

/** 后端已保存的答案 + 模型自己带的 answer，作为初值 */
function seedAnswers() {
  questions.value.forEach((q) => {
    if (answers[q.id] === undefined) {
      const saved = (props.stage?.answers || {})[q.id]
      answers[q.id] = saved || q.answer || ''
    }
    if (freeText[q.id] === undefined) freeText[q.id] = ''
  })
}

watch(questions, seedAnswers, { immediate: true, deep: true })

const missingCount = computed(() => {
  return questions.value.filter((q) => !String(answers[q.id] || '').trim()).length
})

function submit() {
  const payload = {}
  questions.value.forEach((q) => {
    const free = String(freeText[q.id] || '').trim()
    const picked = String(answers[q.id] || '').trim()
    payload[q.id] = free || picked
  })
  // 必须按契约包一层：后端收的是 { answers: {...}, notes: '' }，
  // 直接把答案表当请求体发过去，后端一个都收不到。
  emit('submit', { answers: payload, notes: '' })
}
</script>

<style scoped>
.stage-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
  min-height: 0;
  overflow: auto;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.panel-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 650;
  color: var(--text-primary);
}
.panel-sub {
  margin: 2px 0 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.6;
}
.panel-ops {
  flex: 0 0 auto;
}

/* ---------- 分块 ---------- */
.block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.block-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
}
.block-title {
  font-size: var(--text-sm);
  font-weight: 620;
  color: var(--text-primary);
}
.block-subtitle {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 600;
}
.block-note {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.understanding {
  margin: 0;
  padding: var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  line-height: 1.8;
  color: var(--text-primary);
}
.assumptions {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.plain-list {
  margin: 0;
  padding-left: 18px;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--text-secondary);
}

/* ---------- 澄清问题 ---------- */
.q-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.q-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-card);
}
.q-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}
.q-index {
  flex: 0 0 auto;
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-bg);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
}
.q-text {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.6;
}
.q-why {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.6;
}
.q-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.q-option {
  height: auto;
  margin-right: 0;
  padding: 2px 0;
}
.q-free {
  max-width: 520px;
}

/* ---------- 底部 ---------- */
.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.foot-note {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* ---------- 状态 ---------- */
.panel-state {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel-state-note {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.fail-line {
  font-size: var(--text-sm);
  line-height: 1.7;
}
</style>
