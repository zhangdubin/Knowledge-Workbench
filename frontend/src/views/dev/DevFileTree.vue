<template>
  <ul class="tree" :style="{ paddingLeft: depth ? '14px' : '0' }">
    <li v-for="n in nodes" :key="n.path" class="tree-node">
      <!-- 目录 -->
      <template v-if="n.type === 'dir'">
        <div class="tree-row is-dir" @click="toggle(n.path)">
          <el-icon class="tree-icon"><component :is="open.has(n.path) ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
          <span class="tree-name">{{ n.name }}</span>
        </div>
        <DevFileTree
          v-if="open.has(n.path)"
          :nodes="n.children"
          :active-path="activePath"
          :depth="depth + 1"
          @pick="$emit('pick', $event)"
        />
      </template>
      <!-- 文件 -->
      <template v-else>
        <div
          class="tree-row is-file"
          :class="{ 'is-active': activePath === n.path }"
          @click="$emit('pick', n.file)"
        >
          <el-icon class="tree-icon"><Document /></el-icon>
          <span class="tree-name">{{ n.name }}</span>
          <span class="tree-size">{{ formatBytes(n.file?.size) }}</span>
        </div>
      </template>
    </li>
  </ul>
</template>

<script setup>
/**
 * 项目文件树
 *
 * 为什么要有树：一个能跑的项目动辄几十个文件，
 * 扁平的列表长到后面就找不到「入口在哪」了。
 * 目录树让人一眼看到项目的骨架 —— 这正是「项目生成」这一步要证明的事。
 *
 * 递归组件：文件名即组件名（Vue 3 script setup 支持自引用）。
 */
import { ref, watch } from 'vue'
import { formatBytes } from '../../utils/dev.js'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
  depth: { type: Number, default: 0 },
})

defineEmits(['pick'])

/** 默认全部展开：项目文件不多，深藏目录反而让人以为没生成 */
function dirPaths(nodes, acc) {
  const out = acc || new Set()
  ;(nodes || []).forEach((n) => {
    if (n.type === 'dir') {
      out.add(n.path)
      dirPaths(n.children, out)
    }
  })
  return out
}

const open = ref(dirPaths(props.nodes))

/** 新生成的目录默认展开（用户手动收起的那个不重复打开） */
watch(() => props.nodes, (nodes) => {
  const next = new Set(open.value)
  dirPaths(nodes).forEach((p) => next.add(p))
  open.value = next
})

function toggle(path) {
  const next = new Set(open.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  open.value = next
}
</script>

<style scoped>
.tree {
  list-style: none;
  margin: 0;
  padding: 0;
}
.tree-node { display: block; }
.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.tree-row:hover { background: var(--bg-subtle); }
.tree-row.is-active {
  background: var(--primary-bg);
  color: var(--primary);
}
.tree-row.is-dir { color: var(--text-primary); font-weight: 600; }
.tree-icon { flex: 0 0 auto; font-size: 12px; }
.tree-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-size { flex: 0 0 auto; color: var(--text-tertiary); }
</style>
