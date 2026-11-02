<template>
  <div class="page dev-settings">
    <PageTitle
      title="开发设置"
      subtitle="外部依赖都在这里配：本地模型端点、GitHub 仓库与令牌、网络搜索。密钥只存配置里，界面上一律掩码显示"
      icon-key="Setting"
    >
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button type="primary" :loading="saving" @click="save">
        <el-icon><Check /></el-icon>保存
      </el-button>
    </PageTitle>

    <!-- ============ 运行模式 ============ -->
    <section class="card">
      <h3 class="card-title">运行模式</h3>
      <p class="card-desc">
        离线闭环只用本机知识与本地模型，全程不发一个外网请求；
        在线协同才会用到大模型、GitHub 与网络知识。
      </p>
      <el-radio-group v-model="form.mode" class="mode-pick">
        <el-radio-button value="offline">离线闭环</el-radio-button>
        <el-radio-button value="online">在线协同</el-radio-button>
      </el-radio-group>

      <div class="outbound">
        <div class="outbound-text">
          <div class="outbound-title">出网总闸</div>
          <div class="outbound-desc">
            关掉之后，即使在在线模式下也不会发出任何外网请求 ——
            GitHub、网络搜索、云端模型全部停用，只剩本地模型与本机知识。
          </div>
        </div>
        <el-switch v-model="form.outbound_enabled" />
      </div>

      <div class="mode-status">
        <el-tag :type="modeType(form.mode)" effect="plain">
          当前：{{ modeLabel(form.mode) }}
        </el-tag>
        <el-tag v-if="modelReady" type="success" effect="plain">
          模型就绪：{{ modelName }}
        </el-tag>
        <el-tag v-else type="warning" effect="plain">模型未就绪</el-tag>
      </div>
    </section>

    <!-- ============ 本地模型 ============ -->
    <section class="card">
      <h3 class="card-title">本地模型端点</h3>
      <p class="card-desc">
        任何 OpenAI 兼容的本地服务都行（Ollama、llama.cpp server、vLLM…）。
        离线模式只能用它 —— 云端地址在离线模式下会被直接拒绝。
      </p>
      <el-form label-width="120px" class="cfg-form">
        <el-form-item label="接口地址">
          <el-input
            v-model="form.local_model.base_url"
            placeholder="http://127.0.0.1:11434/v1/chat/completions"
          />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.local_model.model" placeholder="例如 qwen2.5-coder:14b" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.local_model.api_key"
            type="password"
            show-password
            placeholder="本地服务一般留空"
          />
          <div v-if="apiKeySet" class="field-hint">
            已设置（留空表示不修改）
            <el-button size="small" text type="danger" @click="clearSecret('local_model.api_key')">
              清除
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="form.local_model.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="最大长度">
          <el-input-number v-model="form.local_model.max_tokens" :min="256" :max="32768" :step="256" />
        </el-form-item>
      </el-form>
    </section>

    <!-- ============ GitHub ============ -->
    <section class="card">
      <h3 class="card-title">GitHub 开源项目</h3>
      <p class="card-desc">
        令牌只用于读公开仓库与搜代码，不会写进日志；
        留空也能用，只是搜代码会不可用。
      </p>
      <el-form label-width="120px" class="cfg-form">
        <el-form-item label="访问令牌">
          <el-input
            v-model="form.github.token"
            type="password"
            show-password
            placeholder="ghp_… （可留空）"
          />
          <div v-if="tokenSet" class="field-hint">
            已设置（留空表示不修改）
            <el-button size="small" text type="danger" @click="clearSecret('github.token')">
              清除
            </el-button>
          </div>
        </el-form-item>
      </el-form>

      <div class="repo-head">
        <span class="repo-title">参考仓库</span>
        <el-button size="small" @click="addRepo">
          <el-icon><Plus /></el-icon>添加
        </el-button>
      </div>
      <div v-if="form.github.repos.length" class="repo-list">
        <div v-for="(r, i) in form.github.repos" :key="i" class="repo-item">
          <el-input v-model="r.owner" placeholder="owner" class="repo-owner" />
          <span class="repo-slash">/</span>
          <el-input v-model="r.repo" placeholder="repo" class="repo-name" />
          <el-input v-model="r.branch" placeholder="分支（可选）" class="repo-branch" />
          <el-input v-model="r.note" placeholder="备注" class="repo-note" />
          <el-button size="small" text type="danger" @click="removeRepo(i)">删除</el-button>
          <el-button size="small" text @click="probe(r)" :loading="probing === i">探测</el-button>
        </div>
      </div>
      <div v-if="probeResult" class="probe-result" :class="{ bad: !probeResult.ok }">
        {{ probeResult.detail || (probeResult.ok ? '可达' : '不可达') }}
      </div>
    </section>

    <!-- ============ 网络搜索 ============ -->
    <section class="card">
      <h3 class="card-title">网络搜索</h3>
      <p class="card-desc">
        自建搜索服务（SearxNG 之类）的地址。
        没配就明说「这次没搜」—— 不会假装搜过。
      </p>
      <el-form label-width="120px" class="cfg-form">
        <el-form-item label="启用">
          <el-switch v-model="form.web_search.enabled" />
        </el-form-item>
        <el-form-item label="服务地址">
          <el-input
            v-model="form.web_search.endpoint"
            placeholder="http://127.0.0.1:8080/search"
          />
        </el-form-item>
      </el-form>
    </section>

    <!-- ============ 能力自检 ============ -->
    <section class="card">
      <div class="card-head">
        <h3 class="card-title">能力自检</h3>
        <el-button size="small" :loading="checking" @click="check">
          <el-icon><FirstAidKit /></el-icon>开始自检
        </el-button>
      </div>
      <div v-if="doctor" class="doctor">
        <div class="doctor-mode">
          模式：{{ doctor.mode_label || modeLabel(doctor.mode) }}
          <el-tag v-if="doctor.outbound_enabled === false" type="warning" size="small" effect="plain">
            出网总闸已关
          </el-tag>
        </div>
        <div class="cap-list">
          <div v-for="c in doctor.capabilities" :key="c.key" class="cap-item">
            <el-tag :type="c.ok ? 'success' : 'warning'" size="small" effect="plain">
              {{ c.ok ? '可用' : '不可用' }}
            </el-tag>
            <span class="cap-label">{{ c.label }}</span>
            <span class="cap-detail">{{ c.detail }}</span>
          </div>
        </div>
        <div v-if="doctor.missing?.length" class="doctor-missing">
          <div class="doctor-missing-title">还差这些：</div>
          <ul>
            <li v-for="(m, i) in doctor.missing" :key="i">{{ m }}</li>
          </ul>
        </div>
        <div v-if="doctor.how_to_fix?.length" class="doctor-fix">
          <div class="doctor-missing-title">怎么配：</div>
          <ul>
            <li v-for="(h, i) in doctor.how_to_fix" :key="i">{{ h }}</li>
          </ul>
        </div>
      </div>
      <div v-else class="doctor-empty">
        点「开始自检」看看现在缺什么 —— 离线模式下不会发任何外网请求。
      </div>
    </section>
  </div>
</template>

<script setup>
/**
 * 软件开发 · 设置
 *
 * 三块配置对应三种外部依赖：本地模型（离线闭环的命根子）、
 * GitHub（在线取材）、网络搜索（在线取材）。
 *
 * 密钥的处理口径跟 AI 设置一致：
 *   磁盘明文、界面掩码、回传掩码视为「不修改」。
 * 前端绝不能因为「界面上是掩码」就把真值存到本地 state 再回传 ——
 * 那等于把密钥复制一份到浏览器内存之外的地方。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageTitle from '../../components/PageTitle.vue'
import DevApi from '../../api/dev.js'
import { modeLabel, modeType } from '../../utils/dev.js'

const loading = ref(false)
const saving = ref(false)
const checking = ref(false)
const probing = ref('')
const doctor = ref(null)
const probeResult = ref(null)
const tokenSet = ref(false)
const apiKeySet = ref(false)
// 要清掉的密钥字段名（保存时一起提交给后端）
const clearSecrets = ref([])

const form = reactive({
  mode: 'offline',
  outbound_enabled: true,
  github: { token: '', repos: [] },
  local_model: { base_url: '', model: '', api_key: '', temperature: 0.3, max_tokens: 2048 },
  web_search: { endpoint: '', enabled: false },
})

const modelReady = computed(() => {
  const m = (doctor.value && doctor.value.model) || null
  return !!(m && m.ready)
})
const modelName = computed(() => {
  const m = (doctor.value && doctor.value.model) || {}
  return m.name || m.model || ''
})

async function load() {
  loading.value = true
  try {
    const cfg = await DevApi.config()
    if (!cfg) return
    form.mode = cfg.mode || 'offline'
    form.outbound_enabled = cfg.outbound_enabled !== false
    const gh = cfg.github || {}
    form.github.token = gh.token || ''
    form.github.repos = Array.isArray(gh.repos) ? gh.repos.map((r) => ({ ...r })) : []
    tokenSet.value = !!gh.token_set
    const lm = cfg.local_model || {}
    form.local_model.base_url = lm.base_url || ''
    form.local_model.model = lm.model || ''
    form.local_model.api_key = lm.api_key || ''
    form.local_model.temperature = lm.temperature === undefined ? 0.3 : lm.temperature
    form.local_model.max_tokens = lm.max_tokens === undefined ? 2048 : lm.max_tokens
    apiKeySet.value = !!lm.api_key_set
    const ws = cfg.web_search || {}
    form.web_search.endpoint = ws.endpoint || ''
    form.web_search.enabled = !!ws.enabled
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '读配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {
      mode: form.mode,
      outbound_enabled: form.outbound_enabled,
      github: {
        token: form.github.token,
        repos: form.github.repos.map((r) => ({
          owner: (r.owner || '').trim(),
          repo: (r.repo || '').trim(),
          branch: (r.branch || '').trim(),
          note: (r.note || '').trim(),
        })),
      },
      local_model: {
        base_url: form.local_model.base_url.trim(),
        model: form.local_model.model.trim(),
        api_key: form.local_model.api_key,
        temperature: form.local_model.temperature,
        max_tokens: form.local_model.max_tokens,
      },
      web_search: {
        endpoint: form.web_search.endpoint.trim(),
        enabled: form.web_search.enabled,
      },
    }
    if (clearSecrets.value.length) payload.clear_secrets = clearSecrets.value.slice()
    const res = await DevApi.saveConfig(payload)
    if (res) {
      tokenSet.value = !!(res.github && res.github.token_set)
      apiKeySet.value = !!(res.local_model && res.local_model.api_key_set)
      // 保存后把输入框里的密钥清掉：掩码串不该留在前端状态里
      form.github.token = ''
      form.local_model.api_key = ''
      clearSecrets.value = []
    }
    ElMessage.success('已保存')
    await check()
  } catch (e) {
    const d = (e.response && e.response.data) || {}
    ElMessage.error(d.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function check() {
  checking.value = true
  try {
    const res = await DevApi.doctor(form.mode)
    doctor.value = res
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '自检失败')
  } finally {
    checking.value = false
  }
}

function clearSecret(field) {
  if (!clearSecrets.value.includes(field)) clearSecrets.value.push(field)
  ElMessage.info('保存后生效：清除 ' + field)
}

function addRepo() {
  form.github.repos.push({ owner: '', repo: '', branch: '', note: '' })
}

function removeRepo(i) {
  form.github.repos.splice(i, 1)
}

async function probe(r) {
  const spec = ((r.owner || '').trim() + '/' + (r.repo || '').trim())
  if (!r.owner || !r.repo) {
    ElMessage.warning('owner 和 repo 都要填')
    return
  }
  probing.value = form.github.repos.indexOf(r)
  probeResult.value = null
  try {
    const res = await DevApi.probeRepo(spec, r.branch)
    probeResult.value = res || { ok: false, detail: '没有返回结果' }
  } catch (e) {
    const d = (e.response && e.response.data) || {}
    probeResult.value = { ok: false, detail: d.detail || '探测失败' }
  } finally {
    probing.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
.dev-settings {
  padding: var(--space-6);
  max-width: 960px;
}
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
  margin-bottom: var(--space-4);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.card-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-base);
  font-weight: 620;
  color: var(--text-primary);
}
.card-head .card-title {
  margin-bottom: 0;
}
.card-desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--text-secondary);
}
.mode-pick {
  margin-bottom: var(--space-3);
}
.outbound {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  margin-bottom: var(--space-3);
}
.outbound-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.outbound-desc {
  margin-top: 3px;
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-secondary);
}
.mode-status {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.cfg-form {
  max-width: 640px;
}
.field-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 2px;
}
.repo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}
.repo-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.repo-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.repo-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.repo-owner { width: 130px; }
.repo-name { width: 150px; }
.repo-branch { width: 130px; }
.repo-note { width: 180px; }
.repo-slash {
  color: var(--text-tertiary);
}
.probe-result {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--success-text);
}
.probe-result.bad {
  color: var(--danger-text);
}
.doctor-mode {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}
.cap-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cap-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}
.cap-label {
  font-size: var(--text-sm);
  color: var(--text-primary);
  min-width: 110px;
}
.cap-detail {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.doctor-missing {
  margin-top: var(--space-3);
}
.doctor-missing-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.doctor-missing ul {
  margin: var(--space-1) 0 0;
  padding-left: 1.2em;
  font-size: var(--text-xs);
  line-height: 1.9;
  color: var(--text-secondary);
}
.doctor-empty {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
</style>
