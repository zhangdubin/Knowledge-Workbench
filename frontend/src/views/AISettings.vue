<template>
  <div class="page">
    <PageTitle
      title="AI 设置"
      subtitle="配置大语言模型 API · 支持 OpenAI 兼容协议"
      icon-key="MagicStick"
    >
      <el-button @click="load">
        <el-icon><Refresh /></el-icon>刷新状态
      </el-button>
    </PageTitle>

    <!-- 状态卡 -->
    <div class="status-card" :class="config.enabled && config.api_key ? 'on' : 'off'">
      <el-icon :size="32">
        <CircleCheck v-if="config.enabled && config.api_key" />
        <CircleClose v-else />
      </el-icon>
      <div class="status-info">
        <div class="status-title">
          {{ config.enabled && config.api_key ? 'AI 已启用' : 'AI 未启用（使用本地规则）' }}
        </div>
        <div class="status-desc">
          {{ config.enabled && config.api_key
            ? `已连接到 ${config.provider || '自定义'} / 模型：${config.model || '未设置'}`
            : '配置 API Key 后可启用摘要、改写、问答、OCR 等智能能力' }}
        </div>
      </div>
      <el-button :type="config.enabled ? 'danger' : 'primary'" plain @click="toggleEnabled">
        {{ config.enabled ? '禁用' : '启用' }}
      </el-button>
    </div>

    <!-- 配置表单 -->
    <div class="card">
      <div class="card-title">
        <span>API 配置</span>
        <span style="color:var(--text-tertiary);font-size:12px">
          兼容 OpenAI / DeepSeek / OpenRouter / 通义千问 / Ollama / 自定义 endpoint
        </span>
      </div>
      <el-form :model="form" label-width="120px">
        <el-form-item label="服务提供商">
          <el-select v-model="form.provider" style="width:100%" @change="onProviderChange">
            <el-option label="Mock（本地规则）" value="mock" />
            <el-option label="MiniMax（国际）" value="MiniMax" />
            <el-option label="MiniMax（中国）" value="MiniMax_cn" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="OpenRouter" value="openrouter" />
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="通义千问" value="qwen" />
            <el-option label="Ollama（本地）" value="ollama" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>

        <el-form-item label="API Endpoint URL（完整地址）">
          <el-input v-model="form.base_url" placeholder="https://api.minimax.cn/v1/chat/completions" />
          <div style="color:var(--text-tertiary);font-size:12px;margin-top:4px">
            ⚠️ 必须包含 <code>/chat/completions</code> 后缀，否则 MiniMax 会返回 404。
            <br>MiniMax 国内: <code>https://api.minimax.cn/v1/chat/completions</code>
            <br>MiniMax 国际: <code>https://api.minimax.io/v1/chat/completions</code>
          </div>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="hasKey ? '已保存 Key（留空则不修改）' : 'sk-...'"
          />
          <div v-if="hasKey" style="color:var(--text-tertiary);font-size:12px;margin-top:4px">
            🔒 已保存一个 API Key。留空保存 = 保持不变；要更换请直接粘贴新 Key；要清空请点下方「清空配置」。
          </div>
        </el-form-item>

        <el-form-item label="默认模型">
          <el-input
            v-model="form.model"
            placeholder="如 gpt-3.5-turbo / deepseek-chat / qwen-turbo"
          />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="Temperature">
              <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="最大 Tokens">
              <el-input-number v-model="form.max_tokens" :min="64" :max="8192" :step="64" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="系统提示词">
          <el-input v-model="form.system_prompt" type="textarea" :rows="2" />
        </el-form-item>

        <el-form-item label="代执行操作">
          <div class="agent-write">
            <el-switch v-model="form.agent_write" />
            <span class="hint">
              允许 AI 助理新建/修改/删除业务记录。开启后每次改动仍会先在对话框里
              列出字段、由你点「确认执行」才落库，并记入审计日志；关闭则只能查询。
            </span>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="save">保存配置</el-button>
          <el-button @click="testConn" :loading="testing">
            <el-icon><Connection /></el-icon>测试连接
          </el-button>
          <el-button text type="danger" @click="reset">
            <el-icon><Delete /></el-icon>清空配置
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 向量化（embedding）配置 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><DataAnalysis /></el-icon>向量检索（Embedding）
        </span>
        <el-tag :type="embedReady ? 'success' : 'info'" size="small" effect="plain">
          {{ embedReady ? '已就绪' : '未就绪' }}
        </el-tag>
      </div>

      <div class="embed-hint">
        上传的文件会被自动切块并向量化，AI 与「语义检索」就能按意思找到文件内容，
        而不只是匹配字面关键词。<b>关键词检索（FTS5）不依赖这里</b>，
        即使向量化不可用，文件照样能搜到、能预览、能下载。
      </div>

      <el-form :model="form" label-width="140px">
        <el-form-item label="Embedding 接口">
          <el-input
            v-model="form.embed_base_url"
            :placeholder="derivedEmbedUrl || 'https://api.minimax.cn/v1/embeddings'"
          />
          <div class="form-hint">
            留空则从上方 chat 地址自动推导：<code>{{ derivedEmbedUrl || '（待填写 chat 地址）' }}</code>
          </div>
        </el-form-item>

        <el-form-item label="Embedding 模型">
          <el-input v-model="form.embed_model" placeholder="embo-01" />
          <div class="form-hint">MiniMax 的向量模型是 <code>embo-01</code>。切换模型会改变向量维度，系统会自动重建索引。</div>
        </el-form-item>

        <el-form-item label="请求格式">
          <el-radio-group v-model="form.embed_style">
            <el-radio-button value="auto">自动</el-radio-button>
            <el-radio-button value="minimax">MiniMax</el-radio-button>
            <el-radio-button value="openai">OpenAI</el-radio-button>
          </el-radio-group>
          <div class="form-hint">
            MiniMax 用 <code>texts</code> + <code>type</code> 参数、返回 <code>vectors</code>；
            OpenAI 用 <code>input</code>、返回 <code>data[].embedding</code>。自动模式按域名判断。
          </div>
        </el-form-item>

        <el-form-item label="独立 API Key">
          <el-input
            v-model="form.embed_api_key"
            type="password"
            show-password
            :placeholder="hasEmbedKey ? '已保存（留空则不修改）' : '留空则复用上方 chat 的 Key'"
          />
        </el-form-item>

        <el-form-item>
          <el-button @click="testEmbed" :loading="testingEmbed">
            <el-icon><Connection /></el-icon>测试向量化
          </el-button>
          <span v-if="embedStatus.dim" class="embed-dim">
            已探测维度：{{ embedStatus.dim }}
          </span>
        </el-form-item>
      </el-form>

      <div v-if="embedResult" class="embed-result" :class="embedResult.ok ? 'ok' : 'bad'">
        <el-icon>
          <CircleCheck v-if="embedResult.ok" />
          <WarningFilled v-else />
        </el-icon>
        <div>
          <div>{{ embedResult.ok ? `向量化正常：${embedResult.response}` : embedResult.error }}</div>
          <div v-if="embedResult.url" class="embed-url">{{ embedResult.url }}</div>
        </div>
      </div>
    </div>

    <!-- 测试结果 -->
    <div v-if="testResult" class="card">
      <div class="card-title">
        <span>测试结果</span>
        <el-tag :type="testResult.ok ? 'success' : 'danger'" size="small">
          {{ testResult.ok ? '成功' : '失败' }}
        </el-tag>
      </div>
      <pre v-if="testResult.ok" class="result-text success-text">{{ testResult.response }}</pre>
      <div v-else class="result-error">
        <div v-if="testResult.status" class="result-row">
          <span class="result-label">HTTP 状态码</span>
          <el-tag type="danger" size="small">{{ testResult.status }}</el-tag>
        </div>
        <div v-if="testResult.url" class="result-row">
          <span class="result-label">请求 URL</span>
          <code>{{ testResult.url }}</code>
        </div>
        <div v-if="testResult.model" class="result-row">
          <span class="result-label">使用模型</span>
          <code>{{ testResult.model }}</code>
        </div>
        <div v-if="testResult.hint" class="result-row">
          <span class="result-label">状态说明</span>
          <code>{{ testResult.hint }}</code>
        </div>
        <div class="result-row">
          <span class="result-label">错误信息</span>
          <pre class="result-text error-text">{{ testResult.error }}</pre>
        </div>

        <!-- 智能诊断 -->
        <el-alert
          v-if="diagnosis"
          :title="diagnosis.title"
          :type="diagnosis.type"
          :closable="false"
          show-icon
          style="margin-top:12px"
        >
          <div style="line-height:1.7">{{ diagnosis.message }}</div>
          <div v-if="diagnosis.action" style="margin-top:8px">
            <el-button v-if="diagnosis.link" type="primary" size="small" :href="diagnosis.link" target="_blank">
              <el-icon><Link /></el-icon>{{ diagnosis.action }}
            </el-button>
          </div>
        </el-alert>
      </div>
    </div>

    <!-- 能力清单 -->
    <div class="card">
      <div class="card-title">🧠 AI 可用能力</div>
      <div class="cap-grid">
        <div class="cap-item">
          <el-icon><Document /></el-icon>
          <div>
            <div class="cap-name">笔记摘要</div>
            <div class="cap-desc">一键生成 1-2 句话总结</div>
          </div>
        </div>
        <div class="cap-item">
          <el-icon><PriceTag /></el-icon>
          <div>
            <div class="cap-name">自动标签</div>
            <div class="cap-desc">从内容提取关键标签</div>
          </div>
        </div>
        <div class="cap-item">
          <el-icon><EditPen /></el-icon>
          <div>
            <div class="cap-name">改写/扩写</div>
            <div class="cap-desc">润色、扩写、风格化</div>
          </div>
        </div>
        <div class="cap-item">
          <el-icon><Search /></el-icon>
          <div>
            <div class="cap-name">智能问答</div>
            <div class="cap-desc">基于知识库上下文回答</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../api'
import PageTitle from '../components/PageTitle.vue'

const config = ref({})
const form = reactive({
  provider: 'mock',
  base_url: '',
  api_key: '',
  model: '',
  temperature: 0.7,
  max_tokens: 1024,
  enabled: false,
  system_prompt: '',
  agent_write: true,
  // 向量化
  embed_base_url: '',
  embed_api_key: '',
  embed_model: 'embo-01',
  embed_style: 'auto',
  embed_group_id: '',
  embed_timeout: 30,
})
const testing = ref(false)
const testResult = ref(null)
const hasKey = ref(false)

// 向量化状态
const embedStatus = ref({})
const hasEmbedKey = ref(false)
const testingEmbed = ref(false)
const embedResult = ref(null)

// 与后端 derive_embed_url 保持一致的推导逻辑，用于给出实时预览
const derivedEmbedUrl = computed(() => {
  if (form.embed_base_url) return form.embed_base_url
  const base = (form.base_url || '').replace(/\/+$/, '')
  if (!base) return ''
  const stripped = base.replace(
    /\/(chat\/completions|text\/chatcompletion_v2|text\/chatcompletion|chatcompletion_v2|chatcompletion|completions|chat)$/, ''
  )
  return stripped + '/embeddings'
})

const embedReady = computed(() =>
  !!(config.value.enabled && (form.embed_base_url || form.base_url) &&
     (hasEmbedKey.value || hasKey.value))
)

async function load() {
  const cfg = await Api.getAIConfig()
  config.value = cfg
  hasKey.value = !!cfg.api_key
  hasEmbedKey.value = !!cfg.embed_api_key
  Object.assign(form, cfg)
  // 关键：永远不要把掩码（***abcd）回填到表单，否则保存时会把掩码当成真 Key 写回
  form.api_key = ''
  form.embed_api_key = ''
  try {
    embedStatus.value = await Api.getEmbeddingStatus()
  } catch (e) {
    embedStatus.value = {}
  }
}

async function testEmbed() {
  testingEmbed.value = true
  embedResult.value = null
  try {
    // 先保存（Key 为空时后端保留原值），否则测的是旧配置
    await Api.updateAIConfig({ ...form, clear_api_key: false })
    await load()
    embedResult.value = await Api.testEmbedding()
    if (embedResult.value.ok) ElMessage.success('向量化连通')
  } catch (e) {
    embedResult.value = { ok: false, error: String(e) }
  } finally {
    testingEmbed.value = false
  }
}


// 切换 provider 时自动填完整 endpoint（含 /chat/completions）
const PRESETS = {
  openai: 'https://api.openai.com/v1/chat/completions',
  openrouter: 'https://openrouter.ai/api/v1/chat/completions',
  deepseek: 'https://api.deepseek.com/v1/chat/completions',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
  ollama: 'http://localhost:11434/v1/chat/completions',
  MiniMax: 'https://api.minimax.io/v1/chat/completions',
  MiniMax_cn: 'https://api.minimax.cn/v1/chat/completions',
}
const MODEL_PRESETS = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-3.5-turbo'],
  openrouter: ['anthropic/claude-3.5-sonnet', 'openai/gpt-4o', 'meta-llama/llama-3.1-70b'],
  deepseek: ['deepseek-chat', 'deepseek-coder'],
  qwen: ['qwen-turbo', 'qwen-plus', 'qwen-max'],
  ollama: ['llama3.1', 'qwen2', 'mistral'],
  MiniMax: ['MiniMax-M3', 'MiniMax-M2.7', 'MiniMax-M2.5'],
  MiniMax_cn: ['MiniMax-M2.5', 'MiniMax-M2-her', 'abab6.5s-chat', 'abab6.5-chat'],
}
function onProviderChange(p) {
  if (PRESETS[p]) form.base_url = PRESETS[p]
  if (MODEL_PRESETS[p] && !form.model) {
    form.model = MODEL_PRESETS[p][0]
  }
}

async function save(opts = {}) {
  await Api.updateAIConfig({ ...form, clear_api_key: !!opts.clear })
  ElMessage.success('配置已保存')
  await load()
}

async function testConn() {
  testing.value = true
  testResult.value = null
  try {
    // 先临时保存当前表单值（api_key 为空时后端会保留原有 Key，不会误覆盖）
    await Api.updateAIConfig({ ...form, clear_api_key: false })
    await load()
    testResult.value = await Api.testAI()
  } catch (e) {
    testResult.value = { ok: false, error: String(e) }
  } finally {
    testing.value = false
  }
}

async function toggleEnabled() {
  form.enabled = !form.enabled
  await save()
}

// 智能诊断：识别 MiniMax 错误码 + 提供修复指引
const diagnosis = computed(() => {
  if (!testResult.value || testResult.value.ok) return null
  const err = (testResult.value.error || '') + ' ' + (testResult.value.status || '')
  const provider = form.provider || ''

  // 402 / 2067 = 账户额度用尽（Key 本身有效，问题在账户）
  if (testResult.value.status === 402 || /2067|token plan|用量上限|额度已|quota exceeded/i.test(err)) {
    return {
      type: 'warning',
      title: '账户额度已用尽（HTTP 402 / 2067）',
      message:
        '✅ 好消息：API Key 本身是有效的（服务端已经识别并放行了你的身份认证）。' +
        '❌ 当前无法调用是因为该账户的 Token Plan / 免费额度已用完。' +
        '解决办法：① 去 MiniMax 控制台充值或升级套餐 ② 或换一个还有额度的 Key ③ 或暂时切到「Mock（本地规则）」，摘要/标签/改写等功能仍可离线使用。',
      action: provider.startsWith('MiniMax') ? '去 MiniMax 控制台' : null,
      link: provider === 'MiniMax_cn' ? 'https://platform.minimaxi.com/' : (provider === 'MiniMax' ? 'https://platform.minimax.io/' : null),
    }
  }

  // 1004 = API Key 无效（最常见）
  if (/1004|invalid.{0,10}key|login fail|unauthorized/i.test(err)) {
    const isMiniMax = provider.startsWith('MiniMax')
    return {
      type: 'error',
      title: 'API Key 无效（错误码 1004）',
      message: isMiniMax
        ? 'MiniMax 拒绝了请求。最常见原因：① Key 填错了（包括多余的空格）② Key 已过期/被禁用 ③ 国内/国际 Key 弄混（国内控制台拿的 Key 不能用国际 endpoint，反之亦然）'
        : 'API Key 无效。请检查：① 填写的 Key 是否完整（注意多余空格）② Key 是否已过期 ③ provider 选择是否正确（国际 Key 用 OpenAI/MiniMax 国际，国内 Key 用 DeepSeek/通义千问/MiniMax 中国）',
      action: isMiniMax ? '去 MiniMax 控制台查看 Key' : '检查 API Key',
      link: isMiniMax ? 'https://api.minimax.cn/' : null,
    }
  }

  // 2049 = 余额不足
  if (/2049|insufficient|balance/i.test(err)) {
    return {
      type: 'warning',
      title: '账户余额不足（错误码 2049）',
      message: 'API Key 是有效的，但账户余额/额度用完了。请充值或购买套餐。',
      action: '充值',
      link: form.provider === 'MiniMax_cn' ? 'https://api.minimax.cn/' : 'https://api.openai.com/',
    }
  }

  // 2056 = 权限不足
  if (/2056|permission|access denied|forbidden/i.test(err)) {
    return {
      type: 'warning',
      title: '权限不足（错误码 2056）',
      message: '你的 Key 没有访问该模型的权限。请检查：① 模型名称是否拼写正确 ② 你的 Key 是否开通了该模型的访问权限',
    }
  }

  // 301 = 重定向（endpoint 缺 /chat/completions）
  if (testResult.value.status === 301) {
    const url = testResult.value.url || ''
    const missingPath = !/\/chat\/completions(\?|$)/.test(url)
    return {
      type: 'warning',
      title: '301 重定向 — endpoint 缺 /chat/completions 后缀',
      message: missingPath
        ? `当前 endpoint "${url}" 被 MiniMax 重定向了（说明路径不完整）。请把 URL 改成完整 endpoint，例如 https://api.minimax.cn/v1/chat/completions`
        : `当前 endpoint 返回 301。请确认 URL 拼写正确`,
    }
  }

  // 404 = endpoint 错
  if (testResult.value.status === 404) {
    const url = testResult.value.url || ''
    const missingPath = !/\/chat\/completions(\?|$)/.test(url)
    return {
      type: 'warning',
      title: '接口地址不存在（404）',
      message: missingPath
        ? `当前 endpoint "${url}" 缺 /chat/completions 后缀。OpenAI 兼容协议必须使用完整路径，例如 https://api.minimax.cn/v1/chat/completions`
        : `当前 endpoint "${url}" 返回 404。请确认：① Base URL 拼写正确 ② provider 选择是否匹配（MiniMax 国内/国际不同 endpoint）`,
    }
  }

  // 通用网络错误
  if (/timeout|connect|refused|resolve/i.test(err)) {
    return {
      type: 'warning',
      title: '网络连接失败',
      message: '无法连接到 API 服务端。请检查：① Base URL 是否正确 ② 防火墙/代理是否拦截 ③ 网络是否可达',
    }
  }

  return null
})

async function reset() {
  Object.assign(form, {
    provider: 'mock', base_url: '', api_key: '', model: '',
    temperature: 0.7, max_tokens: 1024, enabled: false,
    system_prompt: '你是一个知识工作台 AI 助手，简洁准确。',
  })
  await save({ clear: true })
}

onMounted(load)
</script>

<style scoped>
.status-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 20px 24px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.status-card.on { border-color: var(--success); background: var(--success-bg); }
.status-card.off { border-color: var(--warning); background: var(--warning-bg); }
.status-info { flex: 1; }
.status-title { font-weight: 600; font-size: 16px; }
.status-desc { font-size: 13px; color: var(--text-secondary); margin-top: 4px; }

.result-text {
  background: var(--bg);
  padding: 12px;
  border-radius: var(--radius);
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 13px;
  white-space: pre-wrap;
  margin: 0;
}
.success-text { color: var(--success); }
.error-text { color: var(--danger); }
.result-error { display: flex; flex-direction: column; gap: 12px; }
.result-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.result-label {
  flex-shrink: 0;
  width: 100px;
  color: var(--text-tertiary);
  font-size: 13px;
  font-weight: 500;
  padding-top: 4px;
}
.result-row code {
  background: var(--bg);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 12px;
  word-break: break-all;
}
.result-row pre { flex: 1; }

.cap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.cap-item {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  background: var(--bg);
  border-radius: var(--radius);
}
.cap-item .el-icon {
  color: var(--primary);
  font-size: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}
.cap-name { font-weight: 600; font-size: 14px; }
.cap-desc { font-size: 12px; color: var(--text-tertiary); margin-top: 2px; }

/* ============ 向量化配置卡 ============ */
.embed-hint {
  background: var(--bg-subtle);
  border-left: 3px solid var(--primary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
}
.embed-hint b { color: var(--text-primary); font-weight: 600; }

.embed-dim {
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.embed-result {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  line-height: 1.6;
}
.embed-result.ok {
  background: var(--success-bg);
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 26%, transparent);
}
.embed-result.bad {
  background: var(--warning-bg);
  color: var(--warning);
  border: 1px solid color-mix(in srgb, var(--warning) 26%, transparent);
}
.embed-result .el-icon { margin-top: 2px; flex-shrink: 0; }
.embed-url {
  margin-top: 4px;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 11.5px;
  opacity: 0.85;
  word-break: break-all;
}
html.dark .embed-hint { background: var(--bg-elevated); }
html.dark .embed-result.ok { background: color-mix(in srgb, var(--success) 14%, transparent); }
html.dark .embed-result.bad { background: color-mix(in srgb, var(--warning) 14%, transparent); }

code {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 12px;
}
.agent-write {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.agent-write .hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
</style>