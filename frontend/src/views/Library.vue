<template>
  <div class="page">
    <PageTitle
      title="数据中心"
      subtitle="文件原文存于数据库 · 自动抽取正文并建立检索索引"
      icon-key="Coin"
    >
      <el-button @click="openTrash">
        <el-icon><Delete /></el-icon>回收站
        <span v-if="counts.deleted" class="badge badge-ghost" style="margin-left:6px">
          {{ counts.deleted }}
        </span>
      </el-button>
      <el-button @click="showJsonPlayground = true">
        <el-icon><MagicStick /></el-icon>JSON 试验场
      </el-button>
      <el-button type="primary" @click="fileInput?.click()">
        <el-icon><UploadFilled /></el-icon>上传文件
      </el-button>
    </PageTitle>

    <!-- 上传区 -->
    <div class="upload-card">
      <div
        class="dropzone"
        :class="{ active: dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <div class="dz-icon-wrap">
          <el-icon><UploadFilled /></el-icon>
        </div>
        <div class="dz-main">
          <div class="dz-title">拖拽文件到此处上传</div>
          <div class="dz-hint">
            或
            <button class="link-btn" @click="fileInput?.click()">浏览本地文件</button>
            · 支持任意类型 · 文件原文写入数据库 · 上传后自动抽取正文并建立检索索引
          </div>
        </div>
        <input
          ref="fileInput"
          type="file"
          multiple
          style="display:none"
          @change="onPick"
        />
      </div>

      <div v-if="uploading.length" class="upload-list">
        <div v-for="u in uploading" :key="u.uid" class="upload-item">
          <el-icon class="u-icon" :class="u.status">
            <component :is="u.status === 'success' ? 'CircleCheck' : u.status === 'exception' ? 'CircleClose' : 'Document'" />
          </el-icon>
          <span class="u-name" :title="u.name">{{ u.name }}</span>
          <el-progress
            :percentage="u.progress"
            :status="u.status"
            :stroke-width="6"
            class="u-progress"
          />
          <el-button
            v-if="u.status === 'exception'"
            size="small"
            text
            type="danger"
            @click="removeUpload(u)"
          >移除</el-button>
        </div>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="icon"><el-icon><Files /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ counts.totalFiles }}</div>
          <div class="label">文件总数</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="icon"><el-icon><Picture /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ counts.images }}</div>
          <div class="label">图片</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="icon"><el-icon><Document /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ counts.docs }}</div>
          <div class="label">文档</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="icon"><el-icon><DataBoard /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ formatSize(counts.totalSize) }}</div>
          <div class="label">总大小</div>
        </div>
      </div>
      <div class="stat-card" :class="counts.indexed ? 'success' : ''">
        <div class="icon"><el-icon><MagicStick /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ counts.indexed || 0 }}</div>
          <div class="label">已建向量索引</div>
        </div>
      </div>
    </div>

    <!-- 主内容 -->
    <el-tabs v-model="activeTab" class="main-tabs">
      <!-- ============ 附件库 ============ -->
      <el-tab-pane name="files">
        <template #label>
          <span class="tab-label">
            <el-icon><Folder /></el-icon>附件库
            <span class="badge badge-ghost">{{ filteredFiles.length }}</span>
          </span>
        </template>

        <div class="toolbar">
          <el-input
            v-model="fileKeyword"
            :placeholder="searchMode === 'keyword' ? '搜索文件名或正文...' : '用一句话描述你要找的文件...'"
            clearable
            class="tb-search"
            @keyup.enter="onSearchEnter"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>

          <el-radio-group v-model="searchMode" size="default" @change="onSearchEnter">
            <el-radio-button value="keyword">关键词</el-radio-button>
            <el-radio-button value="hybrid">混合</el-radio-button>
            <el-radio-button value="semantic">语义</el-radio-button>
          </el-radio-group>

          <el-radio-group v-model="typeFilter" size="default">
            <el-radio-button value="">全部</el-radio-button>
            <el-radio-button value="image">图片</el-radio-button>
            <el-radio-button value="doc">文档</el-radio-button>
            <el-radio-button value="other">其他</el-radio-button>
          </el-radio-group>

          <div class="spacer"></div>

          <el-radio-group v-model="viewMode" size="default">
            <el-radio-button value="list">
              <el-icon><List /></el-icon>
            </el-radio-button>
            <el-radio-button value="grid">
              <el-icon><Grid /></el-icon>
            </el-radio-button>
          </el-radio-group>

          <el-button :loading="loading" @click="loadFiles">
            <el-icon><Refresh /></el-icon>刷新
          </el-button>
        </div>

        <!-- 列表视图 -->
        <div v-if="viewMode === 'list'" class="card table-card">
          <el-table
            :data="pagedFiles"
            v-loading="loading"
            class="data-table"
            stripe
            @row-click="previewFile"
            :row-style="{ cursor: 'pointer' }"
          >
            <el-table-column label="文件" min-width="280">
              <template #default="{ row }">
                <div class="file-cell">
                  <span class="file-icon" :style="{ background: typeBg(row.content_type), color: typeColor(row.content_type) }">
                    <el-icon><component :is="typeIconOf(row)" /></el-icon>
                  </span>
                  <div class="file-info">
                    <span class="file-name">{{ row.filename }}</span>
                    <span class="file-sub">{{ row.content_type || '未知类型' }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="110">
              <template #default="{ row }">
                <span class="cell-number">{{ formatSize(row.size) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="关联记录" width="220">
              <template #default="{ row }">
                <template v-if="(row.links || []).length">
                  <a
                    v-for="l in row.links"
                    :key="l.link_id"
                    class="cell-reference"
                    style="cursor:pointer;margin-right:6px"
                    @click.stop="goRecord(l.record_id)"
                  >
                    {{ l.entity_type_icon || '' }}{{ l.record_label || '#' + l.record_id }}
                  </a>
                </template>
                <span v-else class="cell-empty">未关联</span>
              </template>
            </el-table-column>
            <el-table-column label="上传时间" width="170">
              <template #default="{ row }">
                <span class="cell-time">{{ formatTime(row.created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-tooltip content="预览" placement="top" :show-after="400">
                  <el-button size="small" link type="primary" @click.stop="previewFile(row)">
                    <el-icon><View /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip content="JSON 元数据" placement="top" :show-after="400">
                  <el-button size="small" link @click.stop="showMeta(row)">
                    <el-icon><Share /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip content="复制链接" placement="top" :show-after="400">
                  <el-button size="small" link @click.stop="copyLink(row)">
                    <el-icon><Link /></el-icon>
                  </el-button>
                </el-tooltip>
                <el-tooltip content="删除" placement="top" :show-after="400">
                  <el-button size="small" link type="danger" @click.stop="delFile(row)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="!loading && !filteredFiles.length" class="empty-state" style="border:none;background:transparent;padding:48px 24px">
            <div class="empty-icon"><el-icon><FolderOpened /></el-icon></div>
            <div class="empty-title">{{ files.length ? '没有匹配的文件' : '附件库还是空的' }}</div>
            <div class="empty-desc">
              {{ files.length ? '换个关键词或类型再试试' : '上传任意类型的文件，系统会自动生成 JSON 结构化元数据' }}
            </div>
            <div class="empty-actions">
              <el-button v-if="!files.length" type="primary" @click="fileInput?.click()">
                <el-icon><UploadFilled /></el-icon>上传第一个文件
              </el-button>
              <el-button v-else @click="fileKeyword = ''; typeFilter = ''">清空筛选</el-button>
            </div>
          </div>

          <el-pagination
            v-if="filteredFiles.length > pageSize"
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="filteredFiles.length"
            :page-sizes="[12, 24, 48]"
            layout="total, sizes, prev, pager, next"
            class="table-pager"
          />
        </div>

        <!-- 网格视图 -->
        <div v-else v-loading="loading" class="file-grid">
          <div
            v-for="f in pagedFiles"
            :key="f.id"
            class="file-tile"
            @click="previewFile(f)"
          >
            <div class="ft-thumb" :style="{ background: typeBg(f.content_type) }">
              <img v-if="(f.content_type || '').startsWith('image/')" :src="f.url" :alt="f.filename" loading="lazy" />
              <el-icon v-else :style="{ color: typeColor(f.content_type) }">
                <component :is="typeIconOf(f)" />
              </el-icon>
            </div>
            <div class="ft-body">
              <div class="ft-name" :title="f.filename">{{ f.filename }}</div>
              <div class="ft-meta">
                <span>{{ formatSize(f.size) }}</span>
                <span>·</span>
                <span>{{ formatTime(f.created_at).slice(0, 10) }}</span>
              </div>
            </div>
            <div class="ft-actions">
              <el-button size="small" link @click.stop="showMeta(f)"><el-icon><Share /></el-icon></el-button>
              <el-button size="small" link @click.stop="copyLink(f)"><el-icon><Link /></el-icon></el-button>
              <el-button size="small" link type="danger" @click.stop="delFile(f)"><el-icon><Delete /></el-icon></el-button>
            </div>
          </div>
          <div v-if="!loading && !filteredFiles.length" class="empty-state" style="grid-column:1/-1">
            <div class="empty-icon"><el-icon><FolderOpened /></el-icon></div>
            <div class="empty-title">{{ files.length ? '没有匹配的文件' : '附件库还是空的' }}</div>
            <div class="empty-desc">{{ files.length ? '换个关键词或类型再试试' : '上传任意类型的文件，系统会自动生成 JSON 元数据' }}</div>
          </div>
        </div>

        <el-pagination
          v-if="viewMode === 'grid' && filteredFiles.length > pageSize"
          v-model:current-page="page"
          :total="filteredFiles.length"
          :page-size="pageSize"
          layout="total, prev, pager, next"
          class="table-pager"
        />
      </el-tab-pane>

      <!-- ============ JSON 元数据 ============ -->
      <el-tab-pane name="json">
        <template #label>
          <span class="tab-label">
            <el-icon><MagicStick /></el-icon>JSON 元数据
          </span>
        </template>

        <div class="section-subtitle" style="margin-bottom:16px">
          每个附件的结构化元数据，点击展开即可查看 JSON 树。
          元数据是标准 JSON，可直接复制给大模型或下游工具使用。
        </div>

        <div v-if="files.length" class="json-list">
          <div
            v-for="f in files"
            :key="`json-${f.id}`"
            class="json-item"
            :class="{ open: expandedJson.has(f.id) }"
          >
            <div class="json-head" @click="toggleJson(f)">
              <span class="file-icon sm" :style="{ background: typeBg(f.content_type), color: typeColor(f.content_type) }">
                <el-icon><component :is="typeIconOf(f)" /></el-icon>
              </span>
              <span class="json-name">{{ f.filename }}</span>
              <span class="badge badge-ghost">{{ metaBadge(f) }}</span>
              <span class="json-stat">{{ formatSize(f.size) }}</span>
              <el-icon class="json-chev" :class="{ open: expandedJson.has(f.id) }">
                <ArrowRight />
              </el-icon>
            </div>
            <div v-if="expandedJson.has(f.id)" class="json-body">
              <div v-if="metaOf(f.id)?.loading" class="json-loading">
                <el-icon class="is-loading"><Loading /></el-icon>正在读取元数据…
              </div>
              <div v-else-if="metaOf(f.id)?.error" class="json-loading is-error">
                {{ metaOf(f.id).error }}
              </div>
              <JsonViewer
                v-else-if="metaOf(f.id)?.json_tree?.length"
                :tree="metaOf(f.id).json_tree"
                :copy-text="metaOf(f.id).json_text"
              />
              <div v-else class="json-loading">该文件没有元数据</div>
            </div>
          </div>
        </div>

        <div v-else class="empty-state">
          <div class="empty-icon"><el-icon><MagicStick /></el-icon></div>
          <div class="empty-title">还没有元数据</div>
          <div class="empty-desc">上传文件后，系统会自动生成结构化 JSON 元数据（文件名、大小、抽取状态、关联记录…）</div>
          <div class="empty-actions">
            <el-button type="primary" @click="fileInput?.click()">
              <el-icon><UploadFilled /></el-icon>上传文件
            </el-button>
            <el-button @click="showJsonPlayground = true">
              <el-icon><MagicStick /></el-icon>打开试验场
            </el-button>
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ 最近活动 ============ -->
      <el-tab-pane name="recent">
        <template #label>
          <span class="tab-label">
            <el-icon><Clock /></el-icon>最近活动
          </span>
        </template>

        <div class="card">
          <el-timeline v-if="recent.length">
            <el-timeline-item
              v-for="r in recent"
              :key="`${r.entity_type_key}-${r.record_id}`"
              :timestamp="formatTime(r.updated_at)"
              placement="top"
              type="primary"
              hollow
            >
              <div class="recent-row">
                <el-tag size="small" effect="plain">
                  {{ r.entity_type_icon }} {{ r.entity_type_name }}
                </el-tag>
                <a class="recent-link" @click="$router.push(`/records/${r.entity_type_id}?id=${r.record_id}`)">
                  {{ r.data?.name || r.data?.title || r.data?.code || `#${r.record_id}` }}
                </a>
              </div>
            </el-timeline-item>
          </el-timeline>
          <div v-else class="empty-state" style="border:none;background:transparent">
            <div class="empty-icon"><el-icon><Clock /></el-icon></div>
            <div class="empty-title">暂无活动记录</div>
            <div class="empty-desc">创建或编辑数据记录后，这里会显示最近的时间线</div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- JSON 元数据对话框 -->
    <el-dialog
      v-model="metaDialogOpen"
      :title="metaDialogTitle"
      width="800px"
      destroy-on-close
      class="kb-dialog"
    >
      <div v-if="metaFile">
        <div class="dialog-summary">
          <el-icon><InfoFilled /></el-icon>
          <div>
            <strong>{{ metaFile.filename }}</strong> · {{ formatSize(metaFile.size) }} ·
            该元数据由系统在上传时自动生成，可直接复制给 AI 使用。
          </div>
        </div>
        <el-tabs v-model="metaTab">
          <el-tab-pane label="树形视图" name="tree">
            <div v-if="metaOf(metaFile.id)?.loading" class="json-loading">
              <el-icon class="is-loading"><Loading /></el-icon>正在读取元数据…
            </div>
            <JsonViewer
              v-else-if="metaOf(metaFile.id)?.json_tree?.length"
              :tree="metaOf(metaFile.id).json_tree"
              :copy-text="metaOf(metaFile.id).json_text"
            />
            <div v-else class="empty">无元数据</div>
          </el-tab-pane>
          <el-tab-pane label="JSON 原文" name="text">
            <pre class="code-block">{{ metaOf(metaFile.id)?.json_text || '—' }}</pre>
          </el-tab-pane>
          <el-tab-pane label="文件属性" name="props">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="文件名">{{ metaFile.filename }}</el-descriptions-item>
              <el-descriptions-item label="大小">{{ formatSize(metaFile.size) }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ metaFile.content_type || '—' }}</el-descriptions-item>
              <el-descriptions-item label="上传时间">{{ formatTime(metaFile.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="所属记录">
                {{ metaFile.record_id ? `#${metaFile.record_id} (${metaFile.record_entity})` : '独立文件' }}
              </el-descriptions-item>
              <el-descriptions-item label="字段">{{ metaFile.field_key || '—' }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
          <el-tab-pane name="links">
            <template #label>
              <span class="tab-label">
                关联
                <span v-if="metaRelations.length" class="badge badge-primary">{{ metaRelations.length }}</span>
              </span>
            </template>
            <div class="link-head">
              <span class="lh-hint">
                通过「关联定义」建立的关系。文件可以直接与业务记录互相关联，图谱里也会连成网。
              </span>
              <el-button v-if="canManageRelation" size="small" type="primary" plain
                         @click="linkerOpen = true">
                <el-icon><Plus /></el-icon>添加关联
              </el-button>
            </div>
            <div v-if="metaRelations.length" class="link-list">
              <div v-for="r in metaRelations" :key="r.link_id" class="link-row">
                <span class="lr-rel">{{ r.relation }}</span>
                <span class="lr-dir">{{ r.direction === 'out' ? '指向' : '来自' }}</span>
                <a class="lr-other" @click="goRelated(r)">
                  <span class="lr-ico">{{ r.other_icon || '📦' }}</span>{{ r.other_label }}
                </a>
                <span class="lr-type">{{ r.other_type_name }}</span>
                <el-button v-if="canManageRelation" size="small" type="danger" text
                           @click="unlinkRelation(r.link_id)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
            <div v-else class="link-empty">还没有关联</div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="metaDialogOpen = false">关闭</el-button>
        <el-button type="primary" @click="copyLink(metaFile)">复制链接</el-button>
      </template>
    </el-dialog>

    <!-- 文件 ↔ 记录 / 文件的关联建立器 -->
    <RelationLinker
      v-model="linkerOpen"
      :defs="relationDefs"
      self-kind="document"
      :self-id="metaFile?.id"
      :self-label="metaFile?.filename"
      @linked="loadMetaRelations"
    />

    <!-- 文件预览对话框 -->
    <el-dialog
      v-model="previewOpen"
      width="920px"
      top="5vh"
      destroy-on-close
      class="kb-dialog preview-dialog"
    >
      <template #header>
        <div class="dlg-head">
          <span class="file-icon sm" :style="{ background: typeBg(previewFile_?.content_type), color: typeColor(previewFile_?.content_type) }">
            <el-icon><component :is="previewFile_ ? typeIconOf(previewFile_) : 'Document'" /></el-icon>
          </span>
          <div class="dlg-head-text">
            <div class="dlg-head-title">
              {{ previewFile_?.filename }}
              <el-tag v-if="previewMode !== 'other'" size="small" effect="plain" class="mode-tag">
                {{ modeLabel(previewMode) }}
              </el-tag>
            </div>
            <div class="dlg-head-sub">
              {{ previewFile_?.content_type || '未知类型' }} · {{ formatSize(previewFile_?.size) }} ·
              {{ formatTime(previewFile_?.created_at) }}
            </div>
          </div>
        </div>
      </template>

      <div v-if="previewFile_" class="preview-wrap">
        <!-- 图片 -->
        <div v-if="previewMode === 'image'" class="preview-image">
          <img :src="previewUrl" :alt="previewFile_.filename" />
        </div>

        <!-- PDF：后端以 inline 方式返回，可直接内联渲染 -->
        <div v-else-if="previewMode === 'pdf'" class="preview-frame">
          <iframe :src="previewUrl" width="100%" height="640" frameborder="0"></iframe>
        </div>

        <!-- 视频 -->
        <div v-else-if="previewMode === 'video'" class="preview-media">
          <video :src="previewUrl" controls></video>
        </div>

        <!-- 音频 -->
        <div v-else-if="previewMode === 'audio'" class="preview-media audio">
          <div class="audio-icon"><el-icon><Headset /></el-icon></div>
          <div class="audio-name">{{ previewFile_.filename }}</div>
          <audio :src="previewUrl" controls></audio>
        </div>

        <!-- Word -->
        <div v-else-if="previewExtract?.kind === 'docx'" class="preview-doc">
          <template v-for="(b, i) in previewExtract.blocks" :key="i">
            <div
              v-if="b.type === 'heading'"
              class="doc-heading"
              :class="`h${b.level}`"
            >{{ b.text }}</div>
            <div v-else-if="b.type === 'p'" class="doc-p">{{ b.text }}</div>
            <div v-else-if="b.type === 'table'" class="doc-table">
              <table>
                <tbody>
                  <tr v-for="(r, ri) in b.rows" :key="ri">
                    <td v-for="(c, ci) in r" :key="ci" :class="{ 'th': ri === 0 }">{{ c }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <div class="preview-foot">共 {{ previewExtract.blockCount }} 个内容块 · 服务端提取，无需联网</div>
        </div>

        <!-- Excel -->
        <div v-else-if="previewExtract?.kind === 'xlsx'" class="preview-sheet">
          <el-tabs v-model="activeSheet" class="sheet-tabs">
            <el-tab-pane
              v-for="(s, i) in previewExtract.sheets"
              :key="i"
              :label="s.name"
              :name="String(i)"
            >
              <div class="sheet-scroll">
                <table>
                  <tbody>
                    <tr v-for="(r, ri) in s.rows" :key="ri">
                      <td v-for="(c, ci) in r" :key="ci" :class="{ th: ri === 0 }">{{ c }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="preview-foot">
                第 {{ i + 1 }} / {{ previewExtract.sheetCount }} 个工作表 · {{ s.rows.length }} 行
                <span v-if="s.truncated">（已截断显示）</span>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>

        <!-- PPT -->
        <div v-else-if="previewExtract?.kind === 'pptx'" class="preview-slides">
          <div
            v-for="s in previewExtract.slides"
            :key="s.index"
            class="slide-card"
          >
            <div class="slide-no">第 {{ s.index }} 页</div>
            <div v-for="(l, i) in s.lines" :key="i" class="slide-line" :class="{ title: i === 0 }">
              {{ l }}
            </div>
          </div>
          <div class="preview-foot">共 {{ previewExtract.slideCount }} 页 · 服务端提取文本</div>
        </div>

        <!-- CSV -->
        <div v-else-if="previewExtract?.kind === 'csv'" class="preview-sheet">
          <div class="sheet-scroll">
            <table>
              <tbody>
                <tr v-for="(r, ri) in previewExtract.rows" :key="ri">
                  <td v-for="(c, ci) in r" :key="ci" :class="{ th: ri === 0 }">{{ c }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="preview-foot">共 {{ previewExtract.rows.length }} 行</div>
        </div>

        <!-- 文本 / 代码 / Markdown -->
        <div v-else-if="previewMode === 'text'" class="preview-text">
          <div v-if="previewLoading" class="preview-loading">
            <el-icon class="is-loading"><Loading /></el-icon> 读取中…
          </div>
          <pre v-else class="code-block" style="max-height:64vh">{{ previewText }}</pre>
          <div class="preview-foot">{{ previewText.length }} 字符</div>
        </div>

        <!-- 加载中 -->
        <div v-else-if="previewLoading" class="preview-loading">
          <el-icon class="is-loading"><Loading /></el-icon> 正在解析文档…
        </div>

        <!-- Office 解析但失败 / 旧格式 / 其他：降级为下载 -->
        <div v-else class="preview-other">
          <div class="empty-icon">
            <el-icon :size="30"><component :is="typeIconOf(previewFile_)" /></el-icon>
          </div>
          <div class="empty-title">
            {{ previewMode === 'legacy-office' ? '旧版 Office 格式（.doc/.xls/.ppt）无法在线解析'
              : '此类型暂不支持在线预览' }}
          </div>
          <div class="empty-desc">
            {{ previewError || '下载到本地后用相应的应用打开即可。' }}
          </div>
          <el-button type="primary" tag="a" :href="downloadUrl" download>
            <el-icon><Download /></el-icon>下载文件
          </el-button>
        </div>
      </div>

      <template #footer>
        <div class="preview-footer">
          <span v-if="(previewFile_?.links || []).length" class="preview-source">
            <el-icon><Folder /></el-icon>
            <a @click="goRecord(previewFile_.links[0].record_id)">
              查看关联记录（{{ previewFile_.links.length }}）
            </a>
          </span>
          <span v-else-if="previewFile_?.extract_status === 'ok'" class="preview-source muted">
            <el-icon><MagicStick /></el-icon>
            已抽取 {{ previewFile_.extract_chars }} 字，可被 AI 检索
          </span>
          <span v-else-if="previewFile_?.extract_status === 'skipped'" class="preview-source muted">
            <el-icon><WarningFilled /></el-icon>
            该格式无正文，AI 仅能按文件名检索
          </span>
          <div class="spacer"></div>
          <el-button
            v-if="previewFile_?.extract_status === 'ok'"
            @click="askAboutFile"
          >
            <el-icon><MagicStick /></el-icon>就这份文件提问
          </el-button>
          <el-button @click="previewOpen = false">关闭</el-button>
          <el-button @click="showMetaFromPreview">
            <el-icon><Share /></el-icon>查看元数据
          </el-button>
          <el-button type="primary" tag="a" :href="downloadUrl" download>
            <el-icon><Download /></el-icon>下载
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 就当前文件提问 -->
    <AIAssistantDialog
      v-model="askOpen"
      task="ask"
      :document-ids="askDocIds"
    />

    <!-- JSON 试验场：随手粘一段 JSON，立刻看到结构 -->
    <el-dialog
      v-model="showJsonPlayground"
      title="JSON 试验场"
      width="920px"
      destroy-on-close
      class="kb-dialog"
    >
      <div class="dialog-summary">
        <el-icon><InfoFilled /></el-icon>
        <div>
          实时解析 JSON 并展开成树。允许 <code>//</code> 注释与尾随逗号，
          语法错误会直接定位到行列。
        </div>
      </div>
      <div class="playground">
        <div class="pg-col">
          <div class="pg-label">输入 JSON</div>
          <el-input
            v-model="playgroundText"
            type="textarea"
            :rows="16"
            spellcheck="false"
            placeholder='{&#10;  "filename": "report.pdf",&#10;  "size": 245760&#10;}'
            style="font-family:var(--font-mono);font-size:13px"
          />
        </div>
        <div class="pg-col">
          <div class="pg-label">解析结果</div>
          <div class="pg-tree">
            <JsonViewer :text="playgroundText" />
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 回收站：软删除的文件可恢复，也可彻底删除 -->
    <el-dialog
      v-model="trashOpen"
      title="回收站"
      width="760px"
      destroy-on-close
      class="kb-dialog"
    >
      <div class="dialog-summary">
        <el-icon><InfoFilled /></el-icon>
        <div>
          删除的文件只是被标记隐藏，原文仍保存在数据库里。可随时恢复，
          或点「彻底删除」永久移除（不可撤销）。
        </div>
      </div>

      <div v-loading="trashLoading" style="min-height:120px">
        <el-table v-if="trashItems.length" :data="trashItems" stripe>
          <el-table-column label="文件" min-width="240">
            <template #default="{ row }">
              <div class="file-info">
                <span class="file-name">{{ row.filename }}</span>
                <span class="file-sub">{{ formatSize(row.size) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="删除时间" width="170">
            <template #default="{ row }">
              <span class="cell-number">{{ formatTime(row.updated_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" align="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="restoreFile(row)">
                恢复
              </el-button>
              <el-button size="small" type="danger" text @click="purgeFile(row)">
                彻底删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="empty-hint" style="text-align:center;padding:32px">
          回收站是空的
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  UploadFilled, Files, Picture, Document, DataBoard, Search, Folder, FolderOpened,
  List, Grid, Refresh, View, Share, Link, Delete, Clock, MagicStick, Headset,
  Download, InfoFilled, ArrowRight, Loading,
} from '@element-plus/icons-vue'
import { Api, fileUrls, previewModeOf } from '../api'
import { formatTime, formatSize } from '../utils/format'
import JsonViewer from '../components/JsonViewer.vue'
import PageTitle from '../components/PageTitle.vue'
import AIAssistantDialog from '../components/AIAssistantDialog.vue'
import RelationLinker from '../components/RelationLinker.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const router = useRouter()
const route = useRoute()

const dragging = ref(false)
const fileInput = ref(null)
const uploading = ref([])

const files = ref([])
const fileKeyword = ref('')
const typeFilter = ref('')
const viewMode = ref('list')
const loading = ref(false)
const page = ref(1)
const pageSize = ref(24)

const recent = ref([])
const counts = ref({ totalFiles: 0, images: 0, docs: 0, totalSize: 0, indexed: 0, deleted: 0 })
// 检索模式：keyword 走文件名/正文关键词，hybrid 关键词+语义融合，semantic 纯语义
const searchMode = ref('keyword')
const searchHits = ref(null)     // 混合/语义检索的命中结果（含 score / snippet）
const searchInfo = ref(null)

const activeTab = ref('files')

const metaDialogOpen = ref(false)
const metaFile = ref(null)
const metaTab = ref('tree')
const expandedJson = ref(new Set())

// 文件元数据按需拉取：键是文件 id，值是 { loading, error, json_text, json_tree }
// 不在 listDocuments 里内联 —— 一次几百条会把响应撑到近 1MB，
// 而用户实际只会展开其中一两个。
const jsonMeta = ref(new Map())

function metaOf(id) {
  return id == null ? null : jsonMeta.value.get(id) || null
}

async function ensureJsonMeta(id) {
  const cur = jsonMeta.value.get(id)
  if (cur && (cur.loading || cur.json_tree)) return
  jsonMeta.value.set(id, { loading: true, error: '', json_text: '', json_tree: [] })
  try {
    const d = await Api.documentMeta(id)
    jsonMeta.value.set(id, {
      loading: false, error: '',
      json_text: d.json_text || '',
      json_tree: d.json_tree || [],
    })
  } catch (e) {
    jsonMeta.value.set(id, {
      loading: false, error: '元数据读取失败', json_text: '', json_tree: [],
    })
  }
}

function toggleJson(f) {
  const s = expandedJson.value
  if (s.has(f.id)) {
    s.delete(f.id)
    return
  }
  s.add(f.id)
  ensureJsonMeta(f.id)
}

/** 元数据树里的节点总数（含嵌套）；还没拉到时给个中性文案 */
function jsonNodeCount(tree) {
  const count = (node) => {
    let n = 1
    if (node.children) for (const c of node.children) n += count(c)
    return n
  }
  return (tree || []).reduce((sum, n) => sum + count(n), 0)
}

function metaBadge(f) {
  const m = metaOf(f.id)
  if (!m || m.loading) return 'JSON 元数据'
  if (m.error || !m.json_tree?.length) return '无元数据'
  return `${jsonNodeCount(m.json_tree)} 节点`
}

const showJsonPlayground = ref(false)
// 默认样例直接对应「附件元数据」的结构，方便对照 JSON 元数据标签页
const playgroundText = ref(JSON.stringify({
  attachment: {
    id: 42,
    filename: 'report.pdf',
    ext: '.pdf',
    kind: 'doc',
    mime: 'application/pdf',
    size: 245760,
    storage: 'sqlite-blob',
    tags: ['季度', '归档'],
    text_length: 12840,
    extract_status: 'ok',
    embed_status: 'ok',
    links: [{ record_id: 7, field_key: 'files', record_label: 'Q4 采购项目' }],
    download_url: '/api/documents/42/download',
  },
}, null, 2))

// 预览
const previewOpen = ref(false)
const previewFile_ = ref(null)
const previewMode = ref('other')
const previewExtract = ref(null)
const previewText = ref('')
const previewError = ref('')
const previewLoading = ref(false)
const activeSheet = ref('0')

const previewUrl = computed(() => fileUrls.preview(previewFile_.value))
const downloadUrl = computed(() => fileUrls.download(previewFile_.value))

const metaDialogTitle = computed(() => metaFile.value
  ? `附件元数据 · ${metaFile.value.filename}`
  : '附件元数据')

const filteredFiles = computed(() => {
  // 混合/语义模式下，结果集直接来自后端的检索命中（可能包含正文片段）
  let result = searchHits.value || files.value

  if (searchMode.value === 'keyword' && fileKeyword.value) {
    const kw = fileKeyword.value.toLowerCase()
    result = result.filter(f =>
      (f.filename || '').toLowerCase().includes(kw) ||
      (f.title || '').toLowerCase().includes(kw)
    )
  } else if (searchMode.value !== 'keyword' && fileKeyword.value && !searchHits.value) {
    const kw = fileKeyword.value.toLowerCase()
    result = result.filter(f =>
      (f.filename || '').toLowerCase().includes(kw) ||
      (f.title || '').toLowerCase().includes(kw)
    )
  }

  const isDoc = (f) => /\.(pdf|docx?|xlsx?|pptx?|txt|md|csv)$/i.test(f.filename || '')
  if (typeFilter.value === 'image') {
    result = result.filter(f => f.kind === 'image' || (f.content_type || '').startsWith('image/'))
  } else if (typeFilter.value === 'doc') {
    result = result.filter(f => f.kind === 'doc' || isDoc(f))
  } else if (typeFilter.value === 'other') {
    result = result.filter(f =>
      f.kind !== 'image' && f.kind !== 'doc' &&
      !(f.content_type || '').startsWith('image/') && !isDoc(f)
    )
  }
  return result
})


// 客户端分页（过滤结果集分页，修复此前分页失效问题）
const pagedFiles = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredFiles.value.slice(start, start + pageSize.value)
})

// ============ 回收站 ============
const trashOpen = ref(false)
const trashItems = ref([])
const trashLoading = ref(false)

async function openTrash() {
  trashOpen.value = true
  trashLoading.value = true
  try {
    const d = await Api.listDocuments({ include_deleted: true, page: 1, page_size: 200 })
    // 只展示已软删除的
    trashItems.value = (d.items || []).filter(x => x.deleted_at)
  } catch (e) {
    trashItems.value = []
  } finally {
    trashLoading.value = false
  }
}

async function restoreFile(row) {
  try {
    await Api.restoreDocument(row.id)
    ElMessage.success('已恢复')
    trashItems.value = trashItems.value.filter(x => x.id !== row.id)
    loadFiles()
  } catch (e) {}
}

async function purgeFile(row) {
  try {
    await ElMessageBox.confirm(
      `彻底删除「${row.filename}」？文件原文与索引会被永久移除，无法恢复。`,
      '彻底删除',
      { type: 'error', confirmButtonText: '永久删除', cancelButtonText: '取消' },
    )
    await Api.deleteDocument(row.id, true)
    ElMessage.success('已永久删除')
    trashItems.value = trashItems.value.filter(x => x.id !== row.id)
    loadFiles()
  } catch (e) {}
}

// 筛选条件变化时回到第一页
watch([fileKeyword, typeFilter, searchMode], () => { page.value = 1 })

async function loadFiles() {
  loading.value = true
  searchHits.value = null
  searchInfo.value = null
  try {
    const d = await Api.listDocuments({ page: 1, page_size: 500 })
    files.value = d.items || []
    const c = d.counts || {}
    counts.value = {
      totalFiles: c.total || 0,
      images: c.image || 0,
      docs: c.doc || 0,
      totalSize: c.totalSize || 0,
      indexed: c.indexed || 0,
      deleted: c.deleted || 0,
    }
    page.value = 1
  } catch (e) {
    files.value = []
  } finally {
    loading.value = false
  }
}

// 混合 / 语义检索：走服务端 FTS5 + 向量融合
async function onSearchEnter() {
  const kw = (fileKeyword.value || '').trim()
  if (searchMode.value === 'keyword' || !kw) {
    searchHits.value = null
    searchInfo.value = null
    return
  }
  loading.value = true
  try {
    const r = await Api.searchDocuments(kw, { mode: searchMode.value, limit: 100 })
    searchHits.value = r.items || []
    searchInfo.value = r
    if (!searchHits.value.length) ElMessage.info('没有匹配的文件')
  } catch (e) {
    searchHits.value = []
  } finally {
    loading.value = false
  }
}

async function loadRecent() {
  try {
    const s = await Api.getStats()
    recent.value = s.recent || []
  } catch (e) {
    recent.value = []
  }
}

function typeColor(ct) {
  if (!ct) return 'var(--text-tertiary)'
  if (ct.startsWith('image/')) return 'var(--success)'
  if (ct.includes('pdf')) return 'var(--danger)'
  if (ct.includes('word') || ct.includes('document')) return 'var(--primary)'
  if (ct.includes('sheet') || ct.includes('excel')) return 'var(--warning)'
  if (ct.includes('zip') || ct.includes('compressed')) return 'var(--warning)'
  if (ct.includes('video')) return 'var(--primary)'
  if (ct.includes('audio')) return 'var(--primary)'
  return 'var(--text-secondary)'
}

function typeBg(ct) {
  if (!ct) return 'var(--bg-subtle)'
  if (ct.startsWith('image/')) return 'var(--success-bg)'
  if (ct.includes('pdf')) return 'var(--danger-bg)'
  if (ct.includes('word') || ct.includes('document')) return 'var(--primary-bg)'
  if (ct.includes('sheet') || ct.includes('excel')) return 'var(--warning-bg)'
  if (ct.includes('zip') || ct.includes('compressed')) return 'var(--warning-bg)'
  return 'var(--bg-subtle)'
}

function typeIcon(ct) {
  if (!ct) return 'Document'
  if (ct.startsWith('image/')) return 'Picture'
  if (ct.includes('pdf')) return 'Document'
  if (ct.includes('spreadsheet') || ct.includes('excel') || ct.includes('csv')) return 'Grid'
  if (ct.includes('presentation') || ct.includes('powerpoint')) return 'DataBoard'
  if (ct.includes('zip') || ct.includes('compressed')) return 'Box'
  if (ct.includes('video')) return 'VideoCamera'
  if (ct.includes('audio')) return 'Headset'
  return 'Document'
}

function goRecord(rid) {
  Api.getRecord(rid).then(r => {
    if (r) router.push(`/records/${r.entity_type_id}?id=${r.id}`)
  }).catch(() => {
    ElMessage.warning('记录不存在')
  })
}

function showMeta(row) {
  metaFile.value = row
  metaTab.value = 'tree'
  metaDialogOpen.value = true
  ensureJsonMeta(row.id)
  metaRelations.value = []
}

// ============ 文件关联（文件 ↔ 记录 / 文件）============

const linkerOpen = ref(false)
const metaRelations = ref([])
const relationDefs = ref([])
const canManageRelation = computed(() => auth.can('relation_manage'))

async function loadRelationDefs() {
  if (relationDefs.value.length) return
  try { relationDefs.value = await Api.listRelationDefs() } catch { /* 拦截器已提示 */ }
}

async function loadMetaRelations() {
  if (!metaFile.value?.id) return
  try { metaRelations.value = await Api.relationsForDocument(metaFile.value.id) }
  catch { metaRelations.value = [] }
}

async function unlinkRelation(linkId) {
  try {
    await Api.deleteRelationRecord(linkId)
    metaRelations.value = metaRelations.value.filter(r => r.link_id !== linkId)
    ElMessage.success('已解除关联')
  } catch { /* 拦截器已提示 */ }
}

function goRelated(r) {
  if (r.other_kind === 'document') {
    metaDialogOpen.value = false
    const f = files.value.find(x => x.id === r.other_id)
    if (f) previewFile(f)
    return
  }
  metaDialogOpen.value = false
  if (r.other_type_id) router.push({ path: `/records/${r.other_type_id}`, query: { id: r.other_id } })
}

// 切到「关联」页签时才拉数据：多数人打开这个弹窗只想看元数据
watch(metaTab, (v) => {
  if (v !== 'links') return
  loadRelationDefs()
  loadMetaRelations()
})

function showMetaFromPreview() {
  showMeta(previewFile_.value)
}

// 就当前预览的文件向 AI 提问（上下文限定为这一个文件）
const askOpen = ref(false)
const askDocIds = ref([])

function askAboutFile() {
  if (!previewFile_.value?.id) return
  askDocIds.value = [previewFile_.value.id]
  askOpen.value = true
}

async function copyLink(row) {
  if (!row?.id) return
  // 复制预览链接（inline），对方打开即可直接查看
  const rel = fileUrls.preview(row)
  const abs = rel.startsWith('http') ? rel : window.location.origin + rel
  try {
    await navigator.clipboard.writeText(abs)
    ElMessage.success('预览链接已复制')
  } catch (e) {
    ElMessage.info(abs)
  }
}

async function previewFile(row) {
  previewFile_.value = row
  previewMode.value = previewModeOf(row)
  previewExtract.value = null
  previewText.value = ''
  previewError.value = ''
  previewLoading.value = false
  activeSheet.value = '0'
  previewOpen.value = true

  const mode = previewMode.value
  // 需要服务端抽取的模式（Office / CSV / 文本）
  if (['office', 'csv', 'text'].includes(mode)) {
    previewLoading.value = true
    try {
      const data = await Api.documentContent(row.id)
      if (data && data.ok) {
        previewExtract.value = data
        if (data.kind === 'text') previewText.value = data.text || ''
      } else {
        previewError.value = data?.error || ''
        // 文本类兜底：直接抓取内联内容
        if (mode === 'text') {
          try {
            const resp = await fetch(fileUrls.preview(row))
            previewText.value = await resp.text()
          } catch (e) {
            previewText.value = ''
          }
        }
      }
    } catch (e) {
      previewError.value = '解析失败：' + (e?.message || e)
      if (mode === 'text') {
        try {
          const resp = await fetch(fileUrls.preview(row))
          previewText.value = await resp.text()
        } catch (err) { /* 忽略 */ }
      }
    } finally {
      previewLoading.value = false
    }
  }
}

// 按行（含文件名）判定图标，content_type 不可靠时用扩展名兜底
function modeLabel(mode) {
  return {
    image: '图片预览', pdf: 'PDF 内联预览', video: '视频播放', audio: '音频播放',
    office: '文档解析', csv: '表格预览', text: '文本预览', 'legacy-office': '旧版格式',
  }[mode] || ''
}

function typeIconOf(row) {
  const mode = previewModeOf(row)
  if (mode === 'image') return 'Picture'
  if (mode === 'video') return 'VideoCamera'
  if (mode === 'audio') return 'Headset'
  if (mode === 'csv') return 'Grid'
  if (mode === 'office' || mode === 'legacy-office') {
    const n = (row?.filename || '').toLowerCase()
    if (n.endsWith('.xlsx') || n.endsWith('.xls')) return 'Grid'
    if (n.endsWith('.pptx') || n.endsWith('.ppt')) return 'DataBoard'
    return 'Document'
  }
  return typeIcon(row?.content_type)
}

async function delFile(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.filename}」？可从右上角「回收站」恢复。`,
      '删除文件',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteDocument(row.id)
    ElMessage.success('已移入回收站')
    loadFiles()
  } catch (e) {
    /* 取消 */
  }
}


async function onPick(e) {
  await uploadFiles(e.target.files)
  e.target.value = ''
}

async function onDrop(e) {
  dragging.value = false
  await uploadFiles(e.dataTransfer.files)
}

async function uploadFiles(fileList) {
  const list = Array.from(fileList || [])
  if (!list.length) return

  for (const file of list) {
    const item = {
      uid: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      name: file.name, progress: 0, status: '', note: '',
    }
    uploading.value.push(item)
    try {
      // 直接上传：文件原文写入数据库，不再需要先伪造一条笔记当容器
      item.progress = 30
      const doc = await Api.uploadDocument(file, { embed: true })
      item.progress = 100
      item.status = 'success'

      // 后台索引的状态反馈（抽取 / 向量化失败不影响文件本身可用）
      if (doc.extract_status === 'skipped') {
        item.note = '该格式无正文可抽取，仅按文件名检索'
        ElMessage.warning(`${file.name} 已入库；该格式不支持正文抽取`)
      } else if (doc.embed_status === 'failed') {
        item.note = '向量化失败，仍可按关键词检索'
        ElMessage.warning(`${file.name} 已入库；向量化失败，可在 AI 设置里检查 embedding 配置`)
      } else if (doc.warning) {
        item.note = '文件较大'
        ElMessage.warning(`${file.name}：${doc.warning}`)
      }
    } catch (e) {
      item.status = 'exception'
      item.progress = 100
      ElMessage.error(`${file.name} 上传失败`)
    }
  }

  const okCount = uploading.value.filter(u => u.status === 'success').length
  if (okCount) ElMessage.success(`已上传 ${okCount} 个文件`)

  setTimeout(() => {
    uploading.value = uploading.value.filter(u => u.status === 'success')
    loadFiles()
  }, 2200)
}


function removeUpload(u) {
  uploading.value = uploading.value.filter(x => x !== u)
}

onMounted(async () => {
  await loadFiles()
  loadRecent()

  // 支持从全局搜索跳转过来直接打开某个文件的预览：#/library?doc=12
  const docId = Number(route.query.doc)
  if (docId) {
    try {
      const d = await Api.getDocument(docId)
      previewFile(d)
    } catch (e) {
      /* 文件可能已删除 */
    }
  }
})
</script>

<style scoped>
/* ============ 上传卡 ============ */
.upload-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: var(--space-4);
  margin-bottom: var(--space-5);
}
.dropzone {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  transition: all var(--duration) var(--ease-out);
  cursor: pointer;
  background: var(--bg);
}
.dropzone:hover { border-color: var(--primary-light); background: var(--primary-50); }
.dropzone.active {
  border-color: var(--primary);
  background: var(--primary-bg);
  transform: scale(1.005);
}
.dz-icon-wrap {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}
.dz-main { flex: 1; min-width: 0; }
.dz-title { font-weight: 600; font-size: var(--text-md); margin-bottom: 4px; }
.dz-hint { font-size: var(--text-sm); color: var(--text-tertiary); line-height: 1.6; }
.link-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--primary);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.link-btn:hover { color: var(--primary-dark); }

.upload-list {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.upload-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 14px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
}
.u-icon { color: var(--text-tertiary); flex-shrink: 0; }
.u-icon.success { color: var(--success); }
.u-icon.exception { color: var(--danger); }
.u-name {
  font-size: var(--text-sm);
  font-weight: 500;
  min-width: 140px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.u-progress { flex: 1; }

/* ============ Tab ============ */
.main-tabs :deep(.el-tabs__header) { margin-bottom: var(--space-4); }
.main-tabs :deep(.el-tabs__item) { font-weight: 600; }
.tab-label { display: inline-flex; align-items: center; gap: 6px; }

/* ============ 工具栏 ============ */
.tb-search { width: 280px; }

/* ============ 表格 ============ */
.table-card { padding: var(--space-2) var(--space-4) var(--space-4); }
.table-pager { margin-top: var(--space-4); justify-content: flex-end; }

.file-cell { display: flex; align-items: center; gap: var(--space-3); }
.file-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}
.file-icon.sm { width: 28px; height: 28px; font-size: 14px; }
.file-info { display: flex; flex-direction: column; min-width: 0; }
.file-name {
  font-weight: 550;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-sub { font-size: var(--text-xs); color: var(--text-tertiary); }

/* ============ 网格 ============ */
.file-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: var(--space-3);
}
.file-tile {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--duration) var(--ease-out);
  position: relative;
}
.file-tile:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow);
  border-color: var(--primary-light);
}
.ft-thumb {
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36px;
  overflow: hidden;
}
.ft-thumb img { width: 100%; height: 100%; object-fit: cover; }
.ft-body { padding: 10px 12px; }
.ft-name {
  font-size: var(--text-sm);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ft-meta {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 4px;
  display: flex;
  gap: 4px;
}
.ft-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 2px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-full);
  padding: 2px 4px;
  opacity: 0;
  transition: opacity var(--duration-fast);
}
html.dark .ft-actions { background: rgba(21, 23, 29, 0.94); border-color: var(--border); }
.file-tile:hover .ft-actions { opacity: 1; }

/* ============ JSON 元数据列表 ============ */
.json-list { display: flex; flex-direction: column; gap: var(--space-2); }
.json-item {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: all var(--duration-fast) var(--ease-out);
}
.json-item:hover { border-color: var(--primary-light); }
.json-item.open { border-color: var(--primary-light); box-shadow: var(--shadow-sm); }
.json-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 12px 16px;
  cursor: pointer;
  transition: background var(--duration-fast);
}
.json-head:hover { background: var(--primary-50); }
html.dark .json-head:hover { background: var(--bg-elevated); }
.json-name {
  font-weight: 600;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.json-stat { font-size: var(--text-sm); color: var(--text-tertiary); }
.json-chev {
  color: var(--text-tertiary);
  transition: transform var(--duration);
}
.json-chev.open { transform: rotate(90deg); }
.json-body {
  padding: var(--space-4);
  background: var(--bg-subtle);
  border-top: 1px solid var(--border-light);
}
.json-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 4px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.json-loading.is-error { color: var(--danger); }

/* ============ 最近活动 ============ */
.recent-row { display: flex; align-items: center; gap: var(--space-3); }
.recent-link { color: var(--primary); font-weight: 600; cursor: pointer; }
.recent-link:hover { text-decoration: underline; }

/* ============ 预览 ============ */
.preview-wrap { display: flex; flex-direction: column; }
.dlg-head { display: flex; align-items: center; gap: var(--space-3); }
.dlg-head-text { min-width: 0; }
.dlg-head-title { font-weight: 700; font-size: var(--text-lg); letter-spacing: -0.2px; }
.dlg-head-sub { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 2px; }

.preview-image {
  background: var(--bg-subtle);
  border-radius: var(--radius);
  padding: var(--space-3);
  display: flex;
  justify-content: center;
  max-height: 66vh;
  overflow: auto;
}
.preview-image img {
  max-width: 100%;
  max-height: 62vh;
  object-fit: contain;
  border-radius: var(--radius-sm);
}
.preview-frame {
  border-radius: var(--radius);
  overflow: hidden;
  background: #525659;
}
.preview-frame iframe { display: block; }
.preview-media { display: flex; justify-content: center; background: var(--bg-subtle); border-radius: var(--radius); padding: var(--space-4); }
.preview-media video { max-width: 100%; max-height: 62vh; border-radius: var(--radius-sm); }
.preview-media.audio { flex-direction: column; align-items: center; gap: var(--space-3); padding: 36px var(--space-4); }
.audio-icon {
  width: 64px; height: 64px;
  border-radius: var(--radius-lg);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
  font-size: 30px;
}
.audio-name { font-weight: 600; }
.preview-media audio { width: 100%; }
.preview-text { background: var(--bg-subtle); border-radius: var(--radius); padding: var(--space-3); }
.preview-loading {
  padding: 40px 24px;
  text-align: center;
  color: var(--text-tertiary);
  display: flex; align-items: center; justify-content: center; gap: 8px;
}
.preview-foot { margin-top: 10px; font-size: var(--text-xs); color: var(--text-tertiary); }
.preview-other { text-align: center; padding: 48px 20px; }

/* 预览：所属记录 / 模式标签 */
.mode-tag { margin-left: 8px; vertical-align: middle; }
.preview-footer { display: flex; align-items: center; width: 100%; gap: 8px; }
.preview-source {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--text-sm); color: var(--text-secondary);
}
.preview-source a { color: var(--primary); cursor: pointer; font-weight: 600; }
.preview-source a:hover { text-decoration: underline; }
.preview-source.muted { color: var(--text-tertiary); }
.preview-source.muted .el-icon { color: var(--text-tertiary); }

/* 预览：Word 解析 */
.preview-doc {
  max-height: 66vh; overflow-y: auto;
  padding: var(--space-5) var(--space-6);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  line-height: 1.85;
}
.doc-heading { font-weight: 700; color: var(--text-primary); margin: 18px 0 8px; }
.doc-heading.h1 { font-size: 22px; }
.doc-heading.h2 { font-size: 19px; }
.doc-heading.h3 { font-size: 17px; }
.doc-heading.h4 { font-size: 15px; }
.doc-heading:first-child { margin-top: 0; }
.doc-p { margin: 0 0 10px; color: var(--text-primary); font-size: var(--text-base); }

/* 预览：表格（Excel / CSV / Word 表格通用） */
.preview-sheet { min-height: 200px; }
.sheet-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.sheet-scroll {
  max-height: 58vh;
  overflow: auto;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
}
.doc-table { overflow-x: auto; margin: 12px 0; }
.doc-table table,
.preview-sheet table {
  border-collapse: collapse;
  width: 100%;
  font-size: var(--text-sm);
}
.doc-table td,
.preview-sheet td {
  border: 1px solid var(--border-light);
  padding: 6px 10px;
  color: var(--text-primary);
  white-space: nowrap;
  vertical-align: top;
}
.doc-table tr:first-child td,
.preview-sheet td.th {
  background: var(--bg-subtle);
  font-weight: 700;
  color: var(--text-secondary);
  position: sticky;
  top: 0;
}
.preview-sheet tr:nth-child(even) td { background: rgba(99, 102, 241, 0.035); }

/* 预览：PPT */
.preview-slides { display: flex; flex-direction: column; gap: var(--space-3); max-height: 66vh; overflow-y: auto; }
.slide-card {
  border: 1px solid var(--border-light);
  border-left: 3px solid var(--primary);
  border-radius: var(--radius-sm);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
}
.slide-no {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.slide-line { font-size: var(--text-base); color: var(--text-secondary); line-height: 1.7; }
.slide-line.title { font-size: var(--text-lg); font-weight: 700; color: var(--text-primary); margin-bottom: 4px; }

/* ============ 代码块 ============ */
.code-block {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  padding: var(--space-4);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow-y: auto;
  margin: 0;
  color: var(--text-primary);
}

/* ============ 试验场 ============ */
.playground {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.pg-label {
  font-weight: 700;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.pg-tree {
  /* 外观交给 JsonViewer 自己（自带工具栏与滚动），这里只保证高度对齐输入框 */
  min-height: 372px;
}

/* ============ 文件关联页签 ============ */
.link-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 14px; margin-bottom: 12px;
}
.lh-hint { font-size: var(--text-sm); color: var(--text-tertiary); line-height: 1.6; }
.link-list { display: flex; flex-direction: column; gap: 8px; }
.link-row {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 13px; border-radius: var(--radius);
  background: var(--bg-subtle); border: 1px solid var(--border-light);
}
.lr-rel {
  flex-shrink: 0; font-size: var(--text-xs); font-weight: 600;
  color: var(--primary); background: var(--primary-bg);
  padding: 2px 9px; border-radius: var(--radius-sm);
}
.lr-dir {
  flex-shrink: 0; font-size: var(--text-xs); color: var(--text-tertiary);
  border: 1px solid var(--border); border-radius: var(--radius-full); padding: 1px 7px;
  background: var(--bg-card);
}
.lr-other {
  flex: 1; min-width: 0; display: inline-flex; align-items: center; gap: 6px;
  color: var(--primary); cursor: pointer; font-size: var(--text-base);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.lr-other:hover { text-decoration: underline; }
.lr-ico { font-size: 13px; line-height: 1; }
.lr-type { flex-shrink: 0; font-size: var(--text-xs); color: var(--text-tertiary); }
.link-empty {
  padding: 32px; text-align: center; color: var(--text-tertiary); font-size: var(--text-sm);
  border: 1px dashed var(--border-strong); border-radius: var(--radius);
}
</style>
