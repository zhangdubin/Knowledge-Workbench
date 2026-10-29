<template>
  <div class="rel-panel">
    <!-- 关联关系：记录 ↔ 记录 / 文件 -->
    <section class="rel-card">
      <header class="rel-head">
        <span class="rel-head-title">
          <el-icon class="title-ico"><Connection /></el-icon>关联关系
          <span v-if="relations.length" class="badge badge-ghost">{{ relations.length }}</span>
        </span>
        <el-button size="small" @click="addRelationOpen = true">
          <el-icon><Plus /></el-icon>添加关联
        </el-button>
      </header>

      <div v-if="loading" class="rel-loading">
        <el-skeleton :rows="2" animated />
      </div>

      <div v-else-if="relations.length" class="rel-list">
        <div v-for="r in relations" :key="r.link_id" class="rel-item">
          <span class="rel-name">{{ r.relation }}</span>
          <span class="dir-badge" :class="r.direction">{{ r.direction === 'out' ? '指向' : '来自' }}</span>
          <a class="rel-other" @click="goOther(r)">
            <span class="ro-ico">{{ r.other_icon || '📦' }}</span>
            {{ r.other_label }}
            <el-tag v-if="r.other_kind === 'document'" size="small" effect="plain" type="info">文件</el-tag>
          </a>
          <el-button size="small" type="danger" text :aria-label="`删除关联 ${r.relation}`" @click="delRelation(r.link_id)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>

      <div v-else class="rel-empty">
        <span>暂无关联</span>
        <el-button link type="primary" size="small" @click="addRelationOpen = true">添加一条</el-button>
      </div>
    </section>

    <!-- 关联知识：记录 ↔ 知识库笔记 -->
    <section v-if="!knowledge.is_note" class="rel-card">
      <header class="rel-head">
        <span class="rel-head-title">
          <el-icon class="title-ico"><Notebook /></el-icon>关联知识
          <span v-if="knowledge.notes?.length" class="badge badge-ghost">{{ knowledge.notes.length }}</span>
        </span>
        <div class="rel-head-actions">
          <el-button size="small" @click="openNoteLink">
            <el-icon><Link /></el-icon>关联笔记
          </el-button>
          <el-button size="small" type="primary" plain :loading="materializing" @click="materialize">
            <el-icon><MagicStick /></el-icon>沉淀为笔记
          </el-button>
        </div>
      </header>

      <div v-if="knowledge.notes?.length" class="kb-note-list">
        <div v-for="n in knowledge.notes" :key="n.note_id" class="kb-note-item">
          <div class="kb-note-icon"><el-icon><Notebook /></el-icon></div>
          <div class="kb-note-body">
            <div class="kb-note-title">
              <a @click="goNote(n.note_id)">{{ n.title }}</a>
              <el-tag v-for="t in (n.tags || []).slice(0, 3)" :key="t" size="small" effect="plain">#{{ t }}</el-tag>
              <el-tag v-if="n.empty" size="small" type="info">空笔记</el-tag>
            </div>
            <div class="kb-note-snippet">{{ n.snippet || '（暂无内容）' }}</div>
          </div>
          <el-button size="small" text :aria-label="`查看笔记 ${n.title}`" @click="goNote(n.note_id)">
            <el-icon><View /></el-icon>
          </el-button>
          <el-button size="small" type="danger" text :aria-label="`解除关联 ${n.title}`" @click="unlinkNote(n.note_id)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
      <div v-else class="rel-empty">
        <span>还没有关联任何笔记。业务记录挂接知识库后，可在知识图谱中一起呈现。</span>
      </div>
    </section>

    <!-- 添加关联 -->
    <RelationLinker
      v-model="addRelationOpen"
      :defs="relationDefs"
      :record="record"
      @linked="onLinked"
    />

    <!-- 选笔记挂接 -->
    <el-dialog v-model="noteLinkOpen" title="关联知识库笔记" width="480px" append-to-body>
      <p class="dlg-hint">把当前记录与知识库中的笔记挂接起来。关联后，可在笔记详情与图谱中双向看到。</p>
      <el-select
        v-model="selectedNoteId"
        filterable
        remote
        :remote-method="searchNotes"
        :loading="noteSearching"
        placeholder="搜索笔记标题…"
        style="width: 100%"
      >
        <el-option v-for="o in noteOptions" :key="o.id" :label="o.label" :value="o.id" />
      </el-select>
      <template #footer>
        <el-button size="small" @click="noteLinkOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="linking" @click="linkNote">建立关联</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 记录的「关联关系 + 关联知识」面板
 *
 * 为什么抽出来：这套东西原来只长在「记录」页的详情抽屉里，
 * 结果从应用中心点进某个模型、打开一条记录的抽屉 —— 里面空空如也，
 * 看不到这条记录跟谁有关系。用户会以为「应用里的记录没有关联功能」。
 *
 * 抽成组件后，记录页与应用页共用同一份：
 *   - 数据怎么加载只有一处
 *   - 两边行为不会走偏（以前常见「记录页能删关联、应用页不能」这种不一致）
 */
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Connection, Delete, Link, MagicStick, Notebook, Plus, View } from '@element-plus/icons-vue'
import RelationLinker from '../RelationLinker.vue'
import { Api } from '../../api'

const props = defineProps({
  /** 当前记录（整条，含 id） */
  record: { type: Object, default: null },
})

const router = useRouter()

const relations = ref([])
const relationDefs = ref([])
const knowledge = ref({ notes: [], is_note: false, note_type: null })
const loading = ref(false)
const materializing = ref(false)

const addRelationOpen = ref(false)
const noteLinkOpen = ref(false)
const selectedNoteId = ref(null)
const noteOptions = ref([])
const noteSearching = ref(false)
const linking = ref(false)

async function loadRelations() {
  if (!props.record?.id) return
  loading.value = true
  try {
    relations.value = await Api.relationsForRecord(props.record.id)
  } catch {
    relations.value = []
  } finally {
    loading.value = false
  }
}

async function loadKnowledge() {
  if (!props.record?.id) return
  try {
    knowledge.value = await Api.getRecordKnowledge(props.record.id)
  } catch {
    knowledge.value = { notes: [], is_note: false, note_type: null }
  }
}

async function loadDefs() {
  try {
    relationDefs.value = await Api.listRelationDefs()
  } catch {
    relationDefs.value = []
  }
}

async function onLinked() {
  await loadRelations()
}

async function delRelation(rid) {
  try {
    await Api.deleteRelationRecord(rid)
    relations.value = relations.value.filter(r => r.link_id !== rid)
    ElMessage.success('已删除')
  } catch { /* 拦截器已提示 */ }
}

/** 关联对象的跳转：文件进数据中心，记录进对应模型 */
function goOther(link) {
  if (!link?.other_id) return
  if (link.other_kind === 'document') {
    router.push({ path: '/library', query: { doc: link.other_id } })
    return
  }
  // 记录：能查到模型就跳模型页
  if (link.other_type_key) {
    router.push({ path: '/types', query: { key: link.other_type_key } })
  }
}

function goNote(noteId) {
  router.push(`/notes/${noteId}`)
}

function openNoteLink() {
  selectedNoteId.value = null
  noteOptions.value = []
  noteLinkOpen.value = true
  searchNotes('')
}

async function searchNotes(q) {
  const ntId = knowledge.value.note_type?.id
  if (!ntId) return
  noteSearching.value = true
  try {
    const r = await Api.listRecords(ntId, { keyword: q || '', page_size: 50 })
    const linked = new Set((knowledge.value.notes || []).map(n => n.note_id))
    noteOptions.value = (r.items || [])
      .filter(x => !linked.has(x.id))
      .map(x => ({ id: x.id, label: x.data?.title || `#${x.id}` }))
  } catch {
    noteOptions.value = []
  } finally {
    noteSearching.value = false
  }
}

async function linkNote() {
  if (!selectedNoteId.value) {
    ElMessage.warning('请先选择一条笔记')
    return
  }
  linking.value = true
  try {
    await Api.linkKnowledge(props.record.id, selectedNoteId.value)
    ElMessage.success('已关联')
    noteLinkOpen.value = false
    await loadKnowledge()
  } finally {
    linking.value = false
  }
}

async function unlinkNote(noteId) {
  try {
    await Api.unlinkKnowledge(props.record.id, noteId)
    ElMessage.success('已解除关联')
    await loadKnowledge()
  } catch { /* 拦截器已提示 */ }
}

async function materialize() {
  materializing.value = true
  try {
    const r = await Api.noteFromRecord(props.record.id)
    ElMessage.success('已生成笔记并关联')
    await loadKnowledge()
    router.push(`/notes/${r.note_id}`)
  } catch { /* 拦截器已提示 */ } finally {
    materializing.value = false
  }
}

onMounted(() => {
  loadDefs()
  loadRelations()
  loadKnowledge()
})

// 切换到另一条记录时重新加载（抽屉里连续看几条的情况）
watch(() => props.record?.id, (id) => {
  if (!id) return
  loadRelations()
  loadKnowledge()
})
</script>

<style scoped>
.rel-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.rel-card {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  padding: var(--space-3);
}
.rel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}
.rel-head-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.rel-head-actions { display: flex; align-items: center; gap: var(--space-1); }
.title-ico { color: var(--primary); }
.badge-ghost {
  font-size: 10px;
  color: var(--text-tertiary);
  border: 1px solid var(--border-light);
  border-radius: 3px;
  padding: 0 4px;
}
.rel-loading { padding: var(--space-1) 0; }

.rel-list { display: flex; flex-direction: column; gap: 6px; }
.rel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.rel-name { color: var(--text-secondary); }
.dir-badge {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 3px;
  border: 1px solid var(--border-light);
  color: var(--text-tertiary);
}
.dir-badge.out { color: var(--primary-dark); border-color: var(--primary-light); }
html.dark .dir-badge.out { color: var(--primary-light); }
.rel-other {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  color: var(--text-primary);
  min-width: 0;
}
.rel-other:hover { color: var(--primary); }
.ro-ico { font-size: 13px; }

.rel-empty {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  padding: var(--space-1) 0;
}

.kb-note-list { display: flex; flex-direction: column; gap: 6px; }
.kb-note-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}
.kb-note-icon { color: var(--primary); flex-shrink: 0; }
.kb-note-body { flex: 1; min-width: 0; }
.kb-note-title {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  font-size: var(--text-sm);
}
.kb-note-title a { cursor: pointer; color: var(--text-primary); font-weight: 500; }
.kb-note-title a:hover { color: var(--primary); }
.kb-note-snippet {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dlg-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}
</style>
