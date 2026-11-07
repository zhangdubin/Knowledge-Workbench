<template>
  <section class="stage-panel">
    <header class="panel-head">
      <div class="panel-head-main">
        <h3 class="panel-title">{{ stageMeta('implement').title }}</h3>
        <p class="panel-sub">{{ stageMeta('implement').subtitle }}</p>
      </div>
      <div class="panel-ops">
        <el-button
          v-if="stage?.status === 'pending' || !stage"
          type="primary"
          :loading="busy"
          @click="$emit('run')"
        >
          <el-icon><Files /></el-icon>{{ stageMeta('implement').action }}
        </el-button>
        <el-button v-else :loading="busy" @click="$emit('run', { force: true })">
          <el-icon><Refresh /></el-icon>{{ stageMeta('implement').rerun }}
        </el-button>
        <el-button
          type="success"
          plain
          :loading="exporting"
          :disabled="!artifacts.length"
          @click="$emit('export')"
        >
          <el-icon><Download /></el-icon>导出项目 ZIP
        </el-button>
      </div>
    </header>

    <div v-if="stage && stage.status === 'running'" class="panel-state">
      <el-skeleton :rows="5" animated />
      <p class="panel-state-note">正在生成项目文件…</p>
    </div>

    <div v-else-if="stage && stage.status === 'failed'" class="panel-state is-failed">
      <el-alert type="error" :closable="false" show-icon title="这一步失败了">
        <div class="fail-line">{{ stage.error || '后端没有给出失败原因' }}</div>
      </el-alert>
      <el-button type="primary" :loading="busy" @click="$emit('run', { force: true })">重试这一步</el-button>
    </div>

    <template v-else>
      <!-- 还没有任何文件时，先把这一步是干什么的讲清楚 -->
      <EmptyState
        v-if="!artifacts.length"
        icon="Files"
        title="第四步：产出真正能跑的项目"
        description="生成源码、依赖清单、README、测试与启动脚本；跑完之后可以一键导出 ZIP。"
      />

      <div v-else class="impl-body">
        <!-- 文件树 -->
        <div class="impl-tree">
          <div class="impl-pane-head">
            <span class="impl-pane-title">项目文件</span>
            <span class="impl-pane-note">{{ artifacts.length }} 个</span>
          </div>
          <div class="impl-tree-scroll">
            <DevFileTree :nodes="tree" :active-path="activePath" @pick="pick" />
          </div>
        </div>

        <!-- 预览 -->
        <div class="impl-preview">
          <div class="impl-pane-head">
            <span class="impl-pane-title">{{ current?.path || current?.filename || '文件预览' }}</span>
            <div class="impl-pane-ops">
              <el-tag v-if="current?.language" size="small" effect="plain" type="info">
                {{ current.language }}
              </el-tag>
              <el-button
                size="small"
                text
                :loading="importing === current?.id"
                @click="$emit('import', current)"
              >入库</el-button>
              <el-button size="small" text type="danger" @click="$emit('remove', current)">删除</el-button>
            </div>
          </div>
          <pre v-if="preview.kind === PREVIEW_READY" class="code">{{ preview.content }}</pre>
          <div v-else class="preview-state" :class="'is-' + preview.kind">
            <div class="preview-state-title">{{ preview.title }}</div>
            <div v-if="preview.detail" class="preview-state-detail">{{ preview.detail }}</div>
            <el-button
              v-if="preview.kind === PREVIEW_ERROR"
              size="small"
              text
              type="primary"
              @click="reloadContent"
            >重试</el-button>
          </div>
        </div>
      </div>

      <div class="panel-foot">
        <span class="foot-note">
          导出的是 ZIP（顶层一个项目目录），含 README、依赖清单、入口文件、测试与启动脚本。
        </span>
      </div>
    </template>
  </section>
</template>

<script setup>
/**
 * 阶段四：项目生成（implement）
 *
 * 产物不是一段说明文字，而是一批**文件**（dev_artifact 行，
 * path 是项目内相对路径）。所以这一阶段的界面是：
 * 左边文件树、右边内容预览，右上角导出 ZIP。
 *
 * 导出必须带会话 cookie，所以不能用 window.open 裸链 ——
 * 裸链没有会话会直接 401，浏览器还会跳一个 JSON 错误页，
 * 用户完全不知道发生了什么。见 api/dev.js 的 downloadExport。
 *
 * ⚠️ 正文是**按需懒加载**的，不要改回「从列表里直接读 content」：
 *   后端的列表接口（GET /projects/{id}）刻意不带正文 ——
 *   一个项目几十个文件、单个几 KB 到几十 KB，全塞进列表接口会让它变得很重，
 *   而列表页根本用不到正文。正文一律点开哪个文件才去单条接口取哪个。
 *   （原来就是这里断链的：`current?.content` 恒为 undefined，
 *     于是预览区永远显示「（这个文件没有内容）」，
 *     而内容其实好好地躺在库里 —— 是显示链路断了，不是没生成。）
 */
import { computed, ref, watch } from 'vue'
import EmptyState from '../../components/EmptyState.vue'
import DevFileTree from './DevFileTree.vue'
import DevApi from '../../api/dev.js'
import {
  stageMeta, buildFileTree,
  // ⚠️ 这几个状态常量必须**全部**导入：
  //   少导一个（曾经漏了 PREVIEW_LOADING），脚本里一赋值就是
  //   ReferenceError，整个取正文的流程当场中断 ——
  //   表现是「点了文件，预览区永远是空的」，而且控制台里只有一句
  //   很难联想到界面的报错。状态多一个就少导一个，这种错一定要在
  //   浏览器里点一遍才能发现，纯函数测试测不到。
  PREVIEW_IDLE, PREVIEW_LOADING, PREVIEW_READY, PREVIEW_EMPTY, PREVIEW_ERROR,
  previewView, previewErrorText, unwrapArtifactContent,
  hasArtifactContent, contentSizeMatches, nextRequestSeq, isStaleSeq,
} from '../../utils/dev.js'

const props = defineProps({
  stage: { type: Object, default: null },
  artifacts: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  exporting: { type: Boolean, default: false },
  importing: { type: [String, Number], default: null },
})

const emit = defineEmits(['run', 'export', 'import', 'remove'])

const activePath = ref('')
const current = ref(null)

/**
 * 预览区状态。
 *
 * 为什么要拆成「状态 + 正文 + 错误」三份：
 *   「取到了」「没取到」「确实是空的」必须能同时存在于模型里，
 *   界面才能把这三件事分开说。合成一个字符串就又回到老问题上去了。
 */
const previewStatus = ref(PREVIEW_IDLE)
const previewContent = ref('')
const previewError = ref('')

/** 请求序号：慢请求回来时不能把上一个文件的正文盖到当前文件上 */
let previewSeq = 0

/**
 * 已经取过的正文（按产出物 id 存）。
 * 来回切文件不用反复请求；同时靠 size 对账，
 * 发现产出物被重建（重跑项目生成后 id 可能被复用）就重新取。
 */
const contentCache = new Map()

const tree = computed(() => buildFileTree(props.artifacts))

/** 预览区该显示什么：状态、正文、错误 → 一份可直接渲染的视图 */
const preview = computed(() =>
  previewView(previewStatus.value, previewContent.value, previewError.value))

/**
 * 默认选中第一个文件：空着预览区会让人以为没生成。
 *
 * 列表刷新之后（父组件的 load() 会换一整批新对象），
 * 把 current 换成列表里的新对象 —— id 相同、内容相同，
 * 但对象换新之后抬头里的路径/语言才是最新的。
 */
watch(() => props.artifacts, (list) => {
  const arr = Array.isArray(list) ? list : []
  if (!arr.length) {
    current.value = null
    activePath.value = ''
    previewStatus.value = PREVIEW_IDLE
    previewContent.value = ''
    previewError.value = ''
    return
  }
  const found = current.value ? arr.find((a) => a.id === current.value.id) : null
  if (!found) {
    pick(arr[0])
    return
  }
  current.value = found
}, { immediate: true, deep: true })

/** 选文件 → 去取正文（懒加载的入口） */
function pick(file) {
  if (!file) return
  current.value = file
  activePath.value = String(file.path || file.filename || '')
  loadContent(file)
}

/**
 * 取某个产出物的正文。
 *
 * 三种结果要分开：
 *   · 取到了 → 显示正文；
 *   · 文件本来就是空的 → 明说「确实是空的」；
 *   · 没取到 → 显示后端给的错误，绝不冒充「没有内容」。
 */
async function loadContent(file) {
  const id = file && file.id
  // 序号只增不减：只有序号等于最新序号的响应才准写进界面
  const seq = nextRequestSeq(previewSeq)
  previewSeq = seq

  // 已经有正文（别的链路带过来的）：直接显示，不用再请求
  if (hasArtifactContent(file)) {
    previewStatus.value = PREVIEW_READY
    previewContent.value = file.content
    previewError.value = ''
    return
  }
  // 缓存命中，但要先跟列表对一下尺寸：
  // 产出物被重建之后 id 可能被复用，留着旧正文会看到上一轮的代码
  const hit = id != null ? contentCache.get(id) : null
  if (hit && contentSizeMatches(hit.content, file.size)) {
    previewStatus.value = hit.status
    previewContent.value = hit.content
    previewError.value = ''
    return
  }

  previewStatus.value = PREVIEW_LOADING
  previewContent.value = ''
  previewError.value = ''
  try {
    const res = await DevApi.artifact(id)
    // 过期响应直接丢掉：先点的文件后回来时，不能盖掉当前文件的内容
    if (isStaleSeq(seq, previewSeq)) return
    const got = unwrapArtifactContent(res)
    if (got.status === PREVIEW_ERROR) {
      previewStatus.value = PREVIEW_ERROR
      previewError.value = '接口返回里没有正文（content 字段缺失）—— 是没取到，不是文件是空的'
      return
    }
    if (id != null) contentCache.set(id, { status: got.status, content: got.content })
    previewStatus.value = got.status
    previewContent.value = got.content
  } catch (e) {
    if (isStaleSeq(seq, previewSeq)) return
    previewStatus.value = PREVIEW_ERROR
    previewError.value = previewErrorText(e, '读取文件内容失败')
  }
}

/** 重试：失败时给的出口（先清缓存再取一次） */
function reloadContent() {
  const file = current.value
  if (!file) return
  if (file.id != null) contentCache.delete(file.id)
  loadContent(file)
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
.panel-title { margin: 0; font-size: var(--text-lg); font-weight: 650; color: var(--text-primary); }
.panel-sub { margin: 2px 0 0; font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.6; }
.panel-ops { display: flex; gap: var(--space-2); flex: 0 0 auto; }
.block { display: flex; flex-direction: column; gap: var(--space-2); }

/* ---------- 文件树 + 预览 ---------- */
.impl-body {
  display: grid;
  grid-template-columns: minmax(180px, 260px) minmax(0, 1fr);
  gap: var(--space-3);
  min-height: 320px;
}
.impl-tree,
.impl-preview {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.impl-pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
}
.impl-pane-title {
  font-size: var(--text-xs);
  font-weight: 620;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.impl-pane-note { font-size: var(--text-xs); color: var(--text-tertiary); }
.impl-pane-ops { display: flex; align-items: center; gap: var(--space-1); }
.impl-tree-scroll { padding: var(--space-2); overflow: auto; }
.code {
  flex: 1 1 auto;
  margin: 0;
  padding: var(--space-3);
  overflow: auto;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-primary);
  background: var(--bg-subtle);
  white-space: pre;
}
/* 非正文的几种状态：加载中 / 没取到 / 确实是空的。
   三者必须长得不一样 —— 尤其「没取到」要和「空文件」在视觉上分得开，
   免得用户把读取失败当成「模型没生成」。 */
.preview-state {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--bg-subtle);
}
.preview-state-title { font-size: var(--text-sm); font-weight: 620; color: var(--text-secondary); }
.preview-state-detail {
  font-size: var(--text-xs);
  line-height: 1.8;
  color: var(--text-tertiary);
  white-space: pre-wrap;
  word-break: break-word;
}
.preview-state.is-error .preview-state-title { color: var(--danger-text); }
.preview-state.is-error .preview-state-detail { color: var(--danger-text); }
.preview-state.is-empty .preview-state-title { color: var(--text-tertiary); }
.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.foot-note { font-size: var(--text-xs); color: var(--text-tertiary); }
.panel-state { display: flex; flex-direction: column; gap: var(--space-3); }
.panel-state-note { margin: 0; font-size: var(--text-sm); color: var(--text-tertiary); }
.fail-line { font-size: var(--text-sm); line-height: 1.7; }
</style>
