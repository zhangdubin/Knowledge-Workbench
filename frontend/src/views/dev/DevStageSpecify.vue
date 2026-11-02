<template>
  <section class="stage-panel">
    <header class="panel-head">
      <div class="panel-head-main">
        <h3 class="panel-title">{{ stageMeta('specify').title }}</h3>
        <p class="panel-sub">{{ stageMeta('specify').subtitle }}</p>
      </div>
      <div class="panel-ops">
        <el-button
          v-if="stage?.status === 'pending' || !stage"
          type="primary"
          :loading="busy"
          @click="$emit('run')"
        >
          <el-icon><Document /></el-icon>{{ stageMeta('specify').action }}
        </el-button>
        <el-button v-else :loading="busy" @click="$emit('run', { force: true })">
          <el-icon><Refresh /></el-icon>{{ stageMeta('specify').rerun }}
        </el-button>
      </div>
    </header>

    <EmptyState
      v-if="!stage || stage.status === 'pending'"
      icon="Document"
      title="第二步：把需求写成可验收的规格"
      description="生成用户故事、验收标准、非功能需求、数据模型、边界与明确不做的范围。"
    />

    <div v-else-if="stage.status === 'running'" class="panel-state">
      <el-skeleton :rows="5" animated />
      <p class="panel-state-note">正在生成需求规格…</p>
    </div>

    <div v-else-if="stage.status === 'failed'" class="panel-state is-failed">
      <el-alert type="error" :closable="false" show-icon title="这一步失败了">
        <div class="fail-line">{{ stage.error || '后端没有给出失败原因' }}</div>
      </el-alert>
      <el-button type="primary" :loading="busy" @click="$emit('run', { force: true })">重试这一步</el-button>
    </div>

    <template v-else>
      <div v-if="!sections.length" class="block">
        <EmptyState compact icon="Document" title="这次没有产出规格" description="可以点右上角重新生成。" />
      </div>

      <!-- 分区展示：规格是给人审阅的，层次要清楚 -->
      <div v-for="sec in sections" :key="sec.key" class="block">
        <div class="block-head">
          <span class="block-title">{{ sec.title }}</span>
          <span class="block-note">{{ sec.items.length }} 项</span>
        </div>

        <!-- 用户故事 -->
        <div v-if="sec.type === 'stories'" class="story-list">
          <div v-for="(st, i) in sec.items" :key="st.id || i" class="story-card">
            <div class="story-head">
              <span class="story-id">{{ st.id || ('S' + (i + 1)) }}</span>
              <span class="story-title">{{ st.title || '（无标题的用户故事）' }}</span>
            </div>
            <p class="story-line">
              作为 <b>{{ st.as_a || '—' }}</b>，
              我想要 <b>{{ st.i_want || '—' }}</b>，
              以便 <b>{{ st.so_that || '—' }}</b>。
            </p>
            <div v-if="(st.acceptance || []).length" class="story-acc">
              <div class="block-subtitle">验收标准</div>
              <ul class="plain-list">
                <li v-for="(a, ai) in st.acceptance" :key="ai">{{ a }}</li>
              </ul>
            </div>
          </div>
        </div>

        <!-- 数据模型 -->
        <div v-else-if="sec.type === 'entities'" class="entity-list">
          <div v-for="(e, i) in sec.items" :key="e.entity || i" class="entity-card">
            <div class="entity-name">{{ e.entity || '（未命名的实体）' }}</div>
            <div class="entity-fields">
              <el-tag
                v-for="(f, fi) in (e.fields || [])"
                :key="fi"
                size="small"
                effect="plain"
                type="info"
              >{{ f }}</el-tag>
              <span v-if="!(e.fields || []).length" class="entity-empty">没有列出字段</span>
            </div>
          </div>
        </div>

        <!-- 普通清单 -->
        <ul v-else class="plain-list is-boxed">
          <li v-for="(it, i) in sec.items" :key="i">{{ it }}</li>
        </ul>
      </div>

      <!-- 修订说明 -->
      <div class="block">
        <div class="block-head">
          <span class="block-title">修订说明</span>
          <span class="block-note">有要改的地方写在这里，提交后后端会记下这轮修订</span>
        </div>
        <el-input
          v-model="notes"
          type="textarea"
          :rows="3"
          placeholder="例如：S2 改成不需要审批流；性能指标放宽到 P95 < 1s"
        />
        <div class="panel-foot">
          <span class="foot-note">规格由模型起草，你来定稿</span>
          <el-button :loading="busy" @click="submitNotes">保存修订</el-button>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
/**
 * 阶段二：需求补全（specify）
 *
 * 这一阶段的产物是**需求规格**：用户故事 + 验收标准、非功能需求、
 * 数据模型、边界与异常、明确不做的范围（契约 3.2 specify.data）。
 *
 * 为什么分区展示而不是一把糊上来：规格是给人逐条审阅、
 * 逐条推翻的东西，混成一段就没人看了。
 */
import { computed, ref, watch } from 'vue'
import EmptyState from '../../components/EmptyState.vue'
import { stageMeta, specifySections } from '../../utils/dev.js'

const props = defineProps({
  stage: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['run', 'submit'])

const notes = ref('')

const sections = computed(() => specifySections(props.stage?.data))

watch(() => props.stage?.stage_id, () => { notes.value = '' })

/** 保存修订：契约里 specify/design 用 notes + 可选的 data 覆盖 */
function submitNotes() {
  emit('submit', { notes: notes.value })
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
.panel-ops { flex: 0 0 auto; }
.block { display: flex; flex-direction: column; gap: var(--space-2); }
.block-head { display: flex; align-items: baseline; gap: var(--space-3); }
.block-title { font-size: var(--text-sm); font-weight: 620; color: var(--text-primary); }
.block-subtitle { font-size: var(--text-xs); color: var(--text-tertiary); font-weight: 600; }
.block-note { font-size: var(--text-xs); color: var(--text-tertiary); }
.plain-list {
  margin: 0;
  padding-left: 18px;
  font-size: var(--text-sm);
  line-height: 1.9;
  color: var(--text-secondary);
}
.plain-list.is-boxed {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
}
.story-list { display: flex; flex-direction: column; gap: var(--space-3); }
.story-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.story-head { display: flex; align-items: baseline; gap: var(--space-2); }
.story-id {
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-bg);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
}
.story-title { font-size: var(--text-base); font-weight: 600; color: var(--text-primary); }
.story-line {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--text-secondary);
}
.story-acc { display: flex; flex-direction: column; gap: var(--space-1); }
.entity-list { display: flex; flex-direction: column; gap: var(--space-2); }
.entity-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
}
.entity-name { font-size: var(--text-sm); font-weight: 620; color: var(--text-primary); }
.entity-fields { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.entity-empty { font-size: var(--text-xs); color: var(--text-tertiary); }
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
