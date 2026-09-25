<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="720px"
    destroy-on-close
    @open="onOpen"
  >
    <div v-if="config && !config.enabled">
      <el-alert type="warning" :closable="false" style="margin-bottom:16px">
        AI 未启用 — 当前为本地规则模式。<el-link type="primary" @click="$router.push('/ai-settings')">前往 AI 设置</el-link>
      </el-alert>
    </div>

    <div v-if="task === 'ask'">
      <el-input
        v-model="input"
        type="textarea"
        :rows="4"
        placeholder="向 AI 提问... 例如：这份采购合同里的付款条件是什么？"
      />

      <div class="ask-scope">
        <el-radio-group v-model="askScope" size="small">
          <el-radio-button value="auto">自动检索全部资料</el-radio-button>
          <el-radio-button value="docs" :disabled="!documentIds.length">
            仅限指定文件{{ documentIds.length ? ` (${documentIds.length})` : '' }}
          </el-radio-button>
        </el-radio-group>
        <div class="ask-scope-hint">
          {{ askScope === 'auto'
            ? '服务端会在文件正文与知识库笔记里做关键词 + 语义混合检索，挑最相关的几条作为上下文'
            : '只把选中的文件正文作为上下文' }}
        </div>
      </div>

      <div v-if="contextItems.length && askScope === 'auto'" class="ask-ctx">
        另附加 {{ contextItems.length }} 条页面上下文
      </div>
    </div>
    <div v-else-if="task === 'rewrite'">
      <el-radio-group v-model="rewriteStyle" style="margin-bottom:8px">
        <el-radio-button value="polish">润色</el-radio-button>
        <el-radio-button value="formal">正式</el-radio-button>
        <el-radio-button value="casual">口语</el-radio-button>
        <el-radio-button value="expand">扩写</el-radio-button>
        <el-radio-button value="shorten">精简</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="input"
        type="textarea"
        :rows="10"
        placeholder="输入要改写的文本..."
      />
    </div>
    <div v-else>
      <el-input
        v-model="input"
        type="textarea"
        :rows="12"
        :placeholder="placeholder"
      />
    </div>

    <div v-if="loading" class="ai-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>AI 处理中...</span>
    </div>

    <div v-if="output" class="ai-output">
      <div class="output-label">AI 输出</div>
      <div v-if="isTagOutput" class="output-tags">
        <el-tag v-for="t in outputTags" :key="t" effect="plain" style="margin:4px">#{{ t }}</el-tag>
      </div>
      <div v-else class="output-text"><MarkdownText :content="output" /></div>

      <div v-if="task === 'ask' && sources.length" class="output-src">
        <div class="src-title">参考来源（{{ sources.length }}）</div>
        <div class="src-list">
          <div v-for="(s, i) in sources" :key="i" class="src-item">
            <el-tag size="small" :type="s.type === 'document' ? 'primary' : 'success'" effect="plain">
              {{ s.type === 'document' ? '文件' : '笔记' }}
            </el-tag>
            <span class="src-name">{{ s.title }}</span>
            <span class="src-why">
              {{ (s.matched_by || []).map(m => m === 'semantic' ? '语义命中'
                  : m === 'keyword' ? '关键词命中'
                  : m === 'selected' ? '指定' : m).join(' · ') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button v-if="!showApply && output" @click="copyOutput">
        <el-icon><CopyDocument /></el-icon>复制
      </el-button>
      <el-button v-if="showApply && output" @click="copyOutput">
        <el-icon><CopyDocument /></el-icon>复制
      </el-button>
      <el-button v-if="showApply && output" type="primary" @click="applyOutput">
        <el-icon><Check /></el-icon>应用到笔记
      </el-button>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :loading="loading" @click="run">
        <el-icon><MagicStick /></el-icon>{{ task === 'ask' ? '提问' : '生成' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../api'
import MarkdownText from './MarkdownText.vue'

const props = defineProps({
  modelValue: Boolean,
  task: { type: String, default: 'summarize' }, // summarize / tags / rewrite / title / ask
  sourceText: { type: String, default: '' },
  contextItems: { type: Array, default: () => [] }, // for ask
  // 指定只在这些文件里检索（不传则服务端自动检索全部资料）
  documentIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'apply'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const title = computed(() => {
  const titles = {
    summarize: '✨ AI 摘要',
    tags: '🏷️ AI 自动标签',
    rewrite: '✏️ AI 改写',
    title: '📝 AI 生成标题',
    ask: '🤖 AI 智能问答',
  }
  return titles[props.task] || 'AI'
})

const input = ref('')
const output = ref('')
const outputTags = ref([])
const sources = ref([])
const askScope = ref('auto')
const isTagOutput = computed(() => props.task === 'tags')
const loading = ref(false)
const rewriteStyle = ref('polish')
const config = ref(null)
const showApply = computed(() => ['rewrite', 'title', 'tags', 'summarize'].includes(props.task))

const placeholder = computed(() => {
  const map = {
    summarize: '请粘贴要摘要的文本...',
    tags: '请粘贴要提取标签的文本...',
    rewrite: '请粘贴要改写的文本...',
    title: '请粘贴要生成标题的内容...',
  }
  return map[props.task] || ''
})

async function onOpen() {
  input.value = props.sourceText || ''
  output.value = ''
  outputTags.value = []
  sources.value = []
  askScope.value = props.documentIds.length ? 'docs' : 'auto'
  config.value = await Api.getAIConfig().catch(() => null)
}

watch(() => props.task, () => {
  output.value = ''
  outputTags.value = []
  sources.value = []
})

async function run() {
  if (!input.value.trim() && props.task !== 'ask') {
    ElMessage.warning('请输入内容')
    return
  }
  if (!input.value.trim() && props.task === 'ask') {
    ElMessage.warning('请输入问题')
    return
  }
  loading.value = true
  output.value = ''
  sources.value = []
  try {
    let resp
    if (props.task === 'summarize') {
      resp = await Api.aiSummarize(input.value)
      output.value = resp.summary
    } else if (props.task === 'tags') {
      resp = await Api.aiTags(input.value)
      outputTags.value = resp.tags
      output.value = JSON.stringify(resp.tags)
    } else if (props.task === 'rewrite') {
      resp = await Api.aiRewrite(input.value, rewriteStyle.value)
      output.value = resp.text
    } else if (props.task === 'title') {
      resp = await Api.aiTitle(input.value)
      output.value = resp.title
    } else if (props.task === 'ask') {
      const ctx = askScope.value === 'auto'
        ? props.contextItems.map(i => typeof i === 'string' ? i : (i.snippet || i.content || ''))
        : []
      const opts = askScope.value === 'docs'
        ? { document_ids: props.documentIds, auto_retrieve: false }
        : { auto_retrieve: true }
      resp = await Api.aiAsk(input.value, ctx, opts)
      output.value = resp.answer
      sources.value = resp.sources || []
      if (!sources.value.length && resp.context_count) {
        sources.value = [{ type: 'context', title: `页面上下文 ${resp.context_count} 条`, matched_by: [] }]
      }
    }
  } catch (e) {
    output.value = '（AI 调用失败：' + (e.message || e) + '）'
  } finally {
    loading.value = false
  }
}


function copyOutput() {
  if (!output.value) return
  navigator.clipboard.writeText(output.value).then(() => {
    ElMessage.success('已复制')
  }).catch(() => {
    ElMessage.warning('复制失败')
  })
}

function applyOutput() {
  emit('apply', { task: props.task, value: output.value, tags: outputTags.value })
  ElMessage.success('已应用到笔记')
  visible.value = false
}
</script>

<style scoped>
.ai-loading {
  text-align: center;
  padding: 20px;
  color: var(--primary);
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.ai-loading .is-loading {
  animation: rotating 1s linear infinite;
}
@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.ai-output {
  margin-top: 16px;
  padding: 12px 16px;
  background: var(--primary-bg);
  border-radius: var(--radius);
  border-left: 3px solid var(--primary);
}
.output-label {
  font-size: 12px;
  color: var(--primary);
  font-weight: 600;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.output-text {
  color: var(--text-primary);
}
.output-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* 检索范围选择 */
.ask-scope { margin-top: 10px; }
.ask-scope-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}
.ask-ctx {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}

/* 来源列表 */
.output-src {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed color-mix(in srgb, var(--primary) 30%, transparent);
}
.src-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.src-list { display: flex; flex-direction: column; gap: 5px; }
.src-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  min-width: 0;
}
.src-name {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.src-why { color: var(--text-tertiary); font-size: 11.5px; flex-shrink: 0; }
</style>