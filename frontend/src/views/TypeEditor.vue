<template>
  <div class="page">
    <PageTitle
      :title="isEdit ? '编辑数据模型' : '新建数据模型'"
      subtitle="定义字段类型、自动渲染动态表单 / 列表 / 详情视图"
      icon-key="Files"
    >
      <el-button @click="goBack">
        <el-icon><ArrowLeft /></el-icon>返回列表
      </el-button>
    </PageTitle>

    <!--
      编辑器本体已经搬进弹窗组件（ModelEditorDialog.vue）。
      这个页面保留下来只为不破坏既有深链（/types/new、/types/:id/edit），
      这里用 inline 形态把同一个编辑器原样嵌进页面里 —— 两处逻辑只有一份。
    -->
    <ModelEditorDialog
      variant="inline"
      :model-id="editingId"
      :default-app="defaultApp"
      :initial-tab="initialTab"
      @saved="goBack"
      @deleted="goBack"
      @cancel="goBack"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import ModelEditorDialog from '../components/ModelEditorDialog.vue'
import PageTitle from '../components/PageTitle.vue'

const route = useRoute()
const router = useRouter()

const editingId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => !!route.params.id)
// 从列表页带过来的应用分组：/types/new?app=sales
const defaultApp = computed(() => route.query.app || '')
// ?mode=json 仍可用：直接落在 JSON 页签
const initialTab = computed(() => (route.query.mode === 'json' ? 'json' : 'visual'))

function goBack() {
  router.push('/types')
}
</script>
