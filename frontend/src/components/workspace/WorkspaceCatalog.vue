<template>
  <el-dialog
    v-model="open"
    class="workspace-catalog-dialog"
    title="全部功能"
    width="min(680px, calc(100vw - 32px))"
    top="8vh"
    append-to-body
    @open="query = ''"
    @opened="field?.focus()"
    @closed="onClosed"
  >
    <label class="catalog-field">
      <el-icon aria-hidden="true"><Search /></el-icon>
      <input
        ref="field"
        v-model="query"
        type="search"
        aria-label="筛选全部功能"
        placeholder="按功能名称筛选…"
        autocomplete="off"
      />
    </label>
    <div class="catalog-groups">
      <section v-for="group in filteredGroups" :key="group.title">
        <h3>{{ group.title }}</h3>
        <ul class="catalog-list">
          <li v-for="item in group.items" :key="item.path">
            <RouterLink :to="item.path" class="catalog-item" @click="open = false">
              <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
              <span class="catalog-item-text">
                <span>{{ item.label }}</span>
                <small v-if="item.description">{{ item.description }}</small>
              </span>
            </RouterLink>
          </li>
        </ul>
      </section>
      <section v-if="showGenePicker">
        <h3>工具</h3>
        <button type="button" class="catalog-item" @click="chooseGenePicker">
          <el-icon aria-hidden="true"><DataBoard /></el-icon>
          <span class="catalog-item-text">
            <span>引用养料库</span>
            <small>选择并复制资料片段</small>
          </span>
        </button>
      </section>
      <p v-if="!filteredGroups.length && !showGenePicker" class="catalog-empty" role="status">
        {{ query.trim() ? '没有匹配的功能' : '当前账号没有可访问的功能' }}
      </p>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { searchWorkspaceCommands } from '../../utils/workspaceNavigation'

const open = defineModel({ type: Boolean, required: true })
const props = defineProps({
  groups: { type: Array, required: true },
  canPickGene: Boolean,
})
const emit = defineEmits(['pick-gene'])
const field = ref(null)
const query = ref('')
let pickingGene = false

const filteredGroups = computed(() => {
  const matches = new Set(searchWorkspaceCommands(props.groups, query.value))
  return props.groups.map(group => ({
    ...group,
    items: group.items.filter(item => matches.has(item)),
  })).filter(group => group.items.length)
})
const showGenePicker = computed(() => props.canPickGene
  && '引用养料库 选择并复制资料片段'.includes(query.value.trim()))

function chooseGenePicker() {
  pickingGene = true
  open.value = false
}
function onClosed() {
  if (!pickingGene) return
  pickingGene = false
  emit('pick-gene')
}
</script>

<style scoped>
.catalog-field {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text-tertiary);
}
.catalog-field:focus-within { border-color: var(--primary); }
.catalog-field input {
  flex: 1;
  width: 100%;
  min-height: 44px;
  padding: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: var(--text-lg);
}
.catalog-field input::placeholder { color: var(--text-tertiary); }
.catalog-groups { display: grid; gap: var(--space-5); max-height: 64vh; overflow: auto; padding: 3px; }
.catalog-groups h3 {
  margin: var(--space-4) 0 var(--space-2);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  font-weight: 600;
}
.catalog-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px var(--space-2);
  list-style: none;
  margin: 0;
  padding: 0;
}
.catalog-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 52px;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius);
  background: var(--bg-subtle);
  color: var(--text-primary);
  font: inherit;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.catalog-item:hover { background: var(--primary-bg-strong); }
.catalog-item .el-icon { flex: none; color: var(--text-secondary); font-size: 17px; }
.catalog-item-text { display: grid; min-width: 0; gap: 2px; overflow-wrap: anywhere; }
.catalog-item-text small, .catalog-empty { color: var(--text-tertiary); }
@media (max-width: 768px) {
  .catalog-groups { max-height: none; overflow: visible; }
}
@media (max-width: 480px) {
  .catalog-list { grid-template-columns: minmax(0, 1fr); }
}
</style>
