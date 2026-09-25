<template>
  <div class="page">
    <PageTitle
      title="知识库"
      :subtitle="`Obsidian 风格的笔记 · 双向链接 · 全文检索 · 共 ${data.total || 0} 条`"
      icon-key="Notebook"
    >
      <el-button @click="$router.push('/knowledge/graph')">
        <el-icon><DataAnalysis /></el-icon>知识图谱
      </el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建笔记
      </el-button>
    </PageTitle>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索笔记..."
        clearable
        style="width:280px"
        @keyup.enter="load(1)"
        @clear="load(1)"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select
        v-model="tagFilter"
        placeholder="按标签筛选"
        clearable
        style="width:200px"
        @change="load(1)"
      >
        <el-option v-for="t in allTags" :key="t" :label="`#${t}`" :value="t" />
      </el-select>
      <div style="flex:1"></div>
      <el-segmented
        v-model="viewMode"
        :options="[
          { label: '网格', value: 'grid' },
          { label: '列表', value: 'list' },
        ]"
      />
    </div>

    <!-- 笔记内容 -->
    <div v-if="viewMode === 'grid'" class="notes-grid">
      <div
        v-for="n in (data.items || [])"
        :key="n.id"
        class="note-card"
        @click="openNote(n.id)"
      >
        <div class="note-title">
          <el-icon class="note-icon" :size="18"><Document /></el-icon>
          <span class="note-title-text">{{ n.data.title || `未命名笔记 #${n.id}` }}</span>
          <el-tag v-if="!n.data.content" size="small" type="info" effect="plain" class="placeholder-tag">占位</el-tag>
          <div class="note-actions">
            <el-button
              size="small"
              text
              type="danger"
              class="delete-btn"
              @click.stop="(e) => confirmDelete(n, e)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="note-snippet">
          {{ cleanSnippet(n.data.content) || '（空笔记）' }}
        </div>
        <div class="note-meta">
          <el-tag
            v-for="t in (n.data.tags || []).slice(0, 3)"
            :key="t"
            size="small"
            effect="plain"
            @click.stop="tagFilter = t; load(1)"
          >#{{ t }}</el-tag>
          <span class="note-time">{{ formatTime(n.updated_at) }}</span>
        </div>
      </div>
    </div>

    <div v-else class="card" style="padding:0">
      <el-table :data="data.items || []" stripe @row-click="row => openNote(row.id)">
        <el-table-column label="" width="56">
          <template #default="{ row }">
            <div class="row-icon">
              <el-icon :size="20"><Document /></el-icon>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <span style="font-weight:500">{{ row.data.title || `#${row.id}` }}</span>
            <el-tag v-if="!row.data.content" size="small" type="info" style="margin-left:8px">占位</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="摘要" min-width="300">
          <template #default="{ row }">
            <span style="color:var(--text-secondary);font-size:13px">
              {{ (row.data.content || '').slice(0, 100) || '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="160">
          <template #default="{ row }">
            <el-tag
              v-for="t in (row.data.tags || [])"
              :key="t"
              size="small"
              effect="plain"
            >{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 空状态 -->
    <div v-if="!data.items?.length && !loading" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><Document /></el-icon></div>
      <div class="empty-title">还没有笔记</div>
      <div class="empty-desc">开始你的第一条笔记，用 [[双链]] 自动建立反向链接。所有笔记都可以通过全文检索和知识图谱找到。</div>
      <div class="empty-actions">
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>新建笔记
        </el-button>
        <el-button @click="$router.push('/knowledge/graph')">
          <el-icon><DataAnalysis /></el-icon>知识图谱
        </el-button>
      </div>
    </div>

    <el-pagination
      v-if="data.items?.length"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="data.total || 0"
      layout="total, prev, pager, next, jumper"
      @current-change="load()"
      @size-change="load(1)"
      style="margin-top:20px;justify-content:flex-end"
    />

    <!-- 新建对话框 -->
    <el-dialog
      v-model="dialogOpen"
      title="新建笔记"
      width="560px"
      class="rich-dialog"
      :close-on-click-modal="false"
    >
      <div class="dialog-summary">
        <el-icon :size="18"><Document /></el-icon>
        <span>创建后可在详情页使用 AI 辅助、双链关联与文件附件。</span>
      </div>
      <div class="form-section" style="margin-bottom:0">
        <div class="form-section-title">基本信息</div>
        <el-form :model="form" label-width="70px">
          <el-form-item label="标题" required>
            <el-input v-model="form.title" placeholder="给笔记起个名字…" />
          </el-form-item>
          <el-form-item label="标签">
            <el-input
              v-model="tagsInput"
              placeholder="逗号分隔，如：架构, 设计"
              @change="form.tags = tagsInput.split(/[,，]/).map(s=>s.trim()).filter(Boolean)"
            />
          </el-form-item>
          <el-form-item label="内容">
            <el-input
              v-model="form.content"
              type="textarea"
              :rows="6"
              placeholder="支持 [[双链]] 自动创建关联…"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" @click="createNote">
          <el-icon><Plus /></el-icon>创建笔记
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Delete, Plus, Search, DataAnalysis } from '@element-plus/icons-vue'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import PageTitle from '../components/PageTitle.vue'

const router = useRouter()
const noteTypeId = ref(null)
const data = ref({ items: [], total: 0 })
const keyword = ref('')
const tagFilter = ref('')
const allTags = ref([])
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const viewMode = ref('grid')

const dialogOpen = ref(false)
const form = ref({ title: '', content: '', tags: [] })
const tagsInput = ref('')

function cleanSnippet(content) {
  if (!content) return ''
  // 去掉上传元数据（JSON）残留标记，避免 snippet 显示原始机器文本
  return content
    .replace(/\[\[[\s\S]*?\]\]/g, '')
    .replace(/upload\s*\[[\s\S]*?\]/g, '')
    .replace(/attachment_id\s*\d+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 220)
}

async function load(p) {
  if (!noteTypeId.value) return
  if (p) page.value = p
  loading.value = true
  try {
    data.value = await Api.listRecords(noteTypeId.value, {
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value,
    })
    const tags = new Set()
    for (const n of (data.value.items || [])) {
      for (const t of (n.data.tags || [])) tags.add(t)
    }
    allTags.value = [...tags]
  } finally {
    loading.value = false
  }
}

function openNote(id) {
  router.push(`/notes/${id}`)
}

function openCreate() {
  form.value = { title: '', content: '', tags: [] }
  tagsInput.value = ''
  dialogOpen.value = true
}

async function createNote() {
  if (!form.value.title) {
    ElMessage.warning('请填写标题')
    return
  }
  try {
    const r = await Api.createRecord(noteTypeId.value, {
      title: form.value.title,
      content: form.value.content || '',
      tags: form.value.tags,
    })
    if (form.value.content) {
      await Api.syncNoteLinks(r.id, form.value.content)
    }
    ElMessage.success('已创建')
    dialogOpen.value = false
    router.push(`/notes/${r.id}`)
  } catch (e) {}
}

async function confirmDelete(note, e) {
  e?.stopPropagation?.()
  try {
    await ElMessageBox.confirm(
      `确定删除笔记「${note.data.title || '未命名'}」？反向链接和正链都会被解除。`,
      '删除笔记',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await Api.deleteRecord(note.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e === 'cancel' || e?.code === 'cancel' || e?.message === 'cancel') return
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

onMounted(async () => {
  const et = await Api.getEntityTypeByKey('note')
  noteTypeId.value = et.id
  await load(1)
})
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  margin-bottom: var(--space-5);
  flex-wrap: wrap;
}

.note-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.note-icon {
  color: var(--primary);
  flex-shrink: 0;
}
.note-title-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note-actions {
  display: flex;
  gap: 6px;
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-out);
}
.note-card:hover .note-actions { opacity: 1; }
.note-actions .delete-btn { padding: 4px; height: auto; }
.placeholder-tag { margin-left: auto; }

.row-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-summary {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  background: var(--primary-bg);
  border: 1px solid var(--primary-100);
  border-radius: var(--radius);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.6;
  margin-bottom: 20px;
}
.dialog-summary .el-icon { color: var(--primary); margin-top: 2px; }
</style>