<template>
  <div class="page">
    <PageTitle
      title="使用指南"
      subtitle="从零到跑通：应用 → 数据模型 → 记录 → 关联 → 知识库 → AI"
      icon-key="Compass"
    />

    <!-- 心智模型 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Share /></el-icon>系统是怎么组织的
        </span>
      </div>

      <div class="flow">
        <div v-for="(s, i) in FLOW" :key="s.title" class="flow-item">
          <div class="flow-node" @click="$router.push(s.to)">
            <div class="flow-icon"><el-icon :size="22"><component :is="s.icon" /></el-icon></div>
            <div class="flow-title">{{ s.title }}</div>
            <div class="flow-desc">{{ s.desc }}</div>
          </div>
          <el-icon v-if="i < FLOW.length - 1" class="flow-arrow"><Right /></el-icon>
        </div>
      </div>

      <div class="analogy">
        <el-icon><InfoFilled /></el-icon>
        <span>
          类比 Excel：<b>应用</b> = 一个工作簿，<b>数据模型</b> = 一张工作表（表头 = 字段），
          <b>记录</b> = 表里的一行，<b>关联定义</b> = 表之间的外键关系。
          区别是这里<b>不用写代码</b>，改字段即刻生效。
        </span>
      </div>
    </div>

    <!-- 快速上手 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Promotion /></el-icon>五步跑通一个业务
        </span>
      </div>

      <div class="steps">
        <div v-for="(s, i) in STEPS" :key="s.title" class="step">
          <div class="step-no">{{ i + 1 }}</div>
          <div class="step-body">
            <div class="step-title">{{ s.title }}</div>
            <div class="step-desc" v-html="s.desc"></div>
            <div class="step-actions">
              <el-button size="small" type="primary" plain @click="$router.push(s.to)">
                <el-icon><Right /></el-icon>{{ s.action }}
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 文件格式支持 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><View /></el-icon>文件在线预览支持范围
        </span>
        <span class="card-title-hint">数据中心点击任意文件即可预览</span>
      </div>

      <div class="fmt-legend">
        <span><i class="dot ok"></i>可在线预览</span>
        <span><i class="dot part"></i>解析文本 / 表格（版式简化）</span>
        <span><i class="dot no"></i>仅支持下载</span>
      </div>

      <div class="fmt-list">
        <div v-for="f in FORMATS" :key="f.label" class="fmt-row">
          <span class="fmt-status" :class="f.level"></span>
          <span class="fmt-label">{{ f.label }}</span>
          <code class="fmt-ext">{{ f.ext }}</code>
          <span class="fmt-note">{{ f.note }}</span>
        </div>
      </div>

      <div class="analogy">
        <el-icon><InfoFilled /></el-icon>
        <span>
          PDF / 图片 / 音视频走浏览器原生渲染；Word / Excel / PPT / CSV 由后端
          <b>就地解包解析</b>，不依赖公网 Office 服务——内网部署同样可用。
          旧版 <code>.doc / .xls / .ppt</code> 二进制格式无法解析，请另存为新格式。
        </span>
      </div>
    </div>

    <!-- 数据存储与检索 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Coin /></el-icon>文件存在哪 · 怎么被搜到
        </span>
        <span class="card-title-hint">全部数据都在一个 kb.db 里</span>
      </div>

      <div class="store-grid">
        <div v-for="s in STORAGE" :key="s.title" class="store-item">
          <div class="store-icon"><el-icon><component :is="s.icon" /></el-icon></div>
          <div class="store-body">
            <div class="store-title">{{ s.title }}</div>
            <div class="store-desc" v-html="s.desc"></div>
          </div>
        </div>
      </div>

      <div class="analogy">
        <el-icon><InfoFilled /></el-icon>
        <span>
          上传的文件<b>原文直接写进数据库</b>（不是只存路径），所以
          <b>备份就是拷走 <code>data/</code> 一个目录</b>，也不会出现
          「记录还在、文件丢了」的孤儿文件。上传时系统会同时做三件事：
          抽取正文 → 建关键词索引 → 切块向量化。
        </span>
      </div>
    </div>

    <!-- 常见问题 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><QuestionFilled /></el-icon>常见问题
        </span>
      </div>

      <el-collapse v-model="openFaq" class="faq">
        <el-collapse-item v-for="(q, i) in FAQ" :key="i" :name="String(i)">
          <template #title>
            <span class="faq-q">{{ q.q }}</span>
          </template>
          <div class="faq-a" v-html="q.a"></div>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const STORAGE = [
  {
    title: '原文：document 表（BLOB）',
    icon: 'Coin',
    desc: '文件本体与文件名、大小、sha256 指纹一起存在数据库里。删除是软删除，可在<b>数据中心 → 回收站</b>恢复。',
  },
  {
    title: '关键词索引：FTS5',
    icon: 'Search',
    desc: '中文做了逐字切分，所以<b>两个字的词也能搜到</b>（「深圳」这种）。不依赖任何外部服务。',
  },
  {
    title: '语义索引：sqlite-vec',
    icon: 'MagicStick',
    desc: '上传时把正文切块并调用 embedding 接口转成向量。<b>换了意思相近的词也能找到</b>，例如搜「付款条件」命中写着「结算方式」的段落。',
  },
  {
    title: 'AI 问答：混合检索',
    icon: 'ChatDotRound',
    desc: '提问时先用关键词 + 语义两路召回，再融合排序，把最相关的文件段落喂给模型，并<b>标出每条答案来自哪份文件</b>。',
  },
]

const openFaq = ref('0')

const FLOW = [
  { title: '应用', desc: '业务分组容器', icon: 'Grid', to: '/apps' },
  { title: '数据模型', desc: '定义有哪些字段', icon: 'Files', to: '/types' },
  { title: '记录', desc: '按模型录入数据', icon: 'Document', to: '/types' },
  { title: '关联定义', desc: '模型间建关系', icon: 'Connection', to: '/relations' },
  { title: '知识库', desc: '沉淀为笔记与双链', icon: 'Notebook', to: '/notes' },
  { title: '图谱 / AI', desc: '关联分析与智能辅助', icon: 'DataAnalysis', to: '/knowledge/graph' },
]

const STEPS = [
  {
    title: '新建一个应用，直接选业务模板',
    desc: '进入<b>应用中心 → 新建应用</b>，挑选「项目管理 / 销售管理 / 合同管理 / 库存 / 文献 / 人事…」等模板。'
      + '系统会自动建好数据模型、字段和外键，<b>不需要手工搭表</b>。',
    action: '去新建应用',
    to: '/apps',
  },
  {
    title: '需要特殊字段，就编辑数据模型',
    desc: '在<b>数据模型</b>里打开任意模型，可增删字段、调整类型与顺序。'
      + '支持 12 种字段类型：文本、多行文本、富文本、数字、日期、日期时间、单选、多选、布尔、文件、图片、外键引用。'
      + '字段改完立即生效，列表与表单会自动重绘。',
    action: '查看数据模型',
    to: '/types',
  },
  {
    title: '定义模型之间的关联',
    desc: '在<b>关联定义</b>里选「源模型 → 目标模型」，例如「项目 → 任务」。'
      + '定义之后，打开任意项目记录点「添加关联」就能挂上具体任务。'
      + '（项目模板已自动带好这类关联，可跳过。）',
    action: '配置关联',
    to: '/relations',
  },
  {
    title: '录入记录，并上传附件',
    desc: '进入某个模型点「新建记录」。文件/图片类字段支持直接上传，'
      + '上传后可在<b>数据中心</b>点击在线预览 PDF、Word、Excel、PPT、图片与音视频。<br>'
      + '也可以直接在数据中心上传<b>独立文件</b>——不必先造一条记录当容器。',
    action: '去数据中心',
    to: '/library',
  },
  {
    title: '把业务记录沉淀进知识库',
    desc: '在记录详情里点<b>「沉淀为笔记」</b>，系统会把该记录自动渲染成一篇 Markdown 笔记并建立关联；'
      + '也可以点<b>「关联笔记」</b>挂到已有笔记上。之后在笔记详情能看到「关联的业务记录」，知识图谱里也会连成一片。',
    action: '打开知识库',
    to: '/notes',
  },
]

const FORMATS = [
  { label: 'PDF', ext: '.pdf', level: 'ok', note: '浏览器内置阅读器，内联渲染' },
  { label: '图片', ext: '.png .jpg .gif .webp .svg', level: 'ok', note: '原图缩放展示' },
  { label: '视频', ext: '.mp4 .webm .mov', level: 'ok', note: '内置播放器播放' },
  { label: '音频', ext: '.mp3 .wav .m4a', level: 'ok', note: '内置播放器播放' },
  { label: 'Word', ext: '.docx', level: 'part', note: '解析标题 / 段落 / 表格，保留层级' },
  { label: 'Excel', ext: '.xlsx', level: 'part', note: '按工作表渲染为表格，支持切换 Sheet（最多 800 行）' },
  { label: 'PowerPoint', ext: '.pptx', level: 'part', note: '按页提取文本，一页一张卡片' },
  { label: 'CSV / TSV', ext: '.csv .tsv', level: 'part', note: '解析为表格，首行为表头' },
  { label: '文本 / 代码', ext: '.txt .md .json .xml .py .js …', level: 'ok', note: '等宽字体展示，自动识别 GB18030 编码' },
  { label: '旧版 Office', ext: '.doc .xls .ppt', level: 'no', note: '二进制格式无法解析，建议另存为新格式' },
  { label: '压缩包等', ext: '.zip .rar .7z', level: 'no', note: '请下载后本地打开' },
]

const FAQ = [
  {
    q: '新建应用和数据模型到底怎么用？我该先做哪个？',
    a: '顺序是 <b>应用 → 数据模型 → 记录</b>。<br>'
      + '<b>应用</b>只是分组容器，本身不存数据；<b>数据模型</b>才是定义「有哪些字段」的那张表；'
      + '有了模型才能<b>录入记录</b>。<br>'
      + '最省事的做法：在应用中心新建应用时直接选一个业务模板，模型和字段会一次性生成，'
      + '马上就能录数据；之后不满意再进「数据模型」微调字段即可。',
  },
  {
    q: '为什么我在记录里看不到「添加关联」的选项？',
    a: '关联的候选来自<b>关联定义</b>。如果某个模型没有参与任何关联定义，'
      + '下拉列表就是空的。<br>请先到「关联定义」新建一条，例如 <code>项目 → 任务</code>，'
      + '然后回到项目记录的详情页，就能选到具体任务了。',
  },
  {
    q: 'PDF 之前打不开，现在怎么就可以了？',
    a: '之前文件统一走下载接口，响应头是 <code>Content-Disposition: attachment</code>，'
      + '浏览器只会触发下载而不会渲染，所以在预览框里是空白的。<br>'
      + '现在预览走独立的 <code>/preview</code> 接口，以 <code>inline</code> 方式返回，'
      + 'PDF、图片、音视频都由浏览器直接渲染；Word/Excel/PPT 由后端解析内容后展示。',
  },
  {
    q: '业务记录和知识库笔记是两份数据吗？',
    a: '是两份，但互相关联。业务记录适合<b>结构化</b>的字段化数据（金额、日期、状态），'
      + '笔记适合<b>非结构化</b>的长文与思考。<br>'
      + '两者通过「关联知识 / 沉淀为笔记」打通：记录详情能看到关联笔记，'
      + '笔记详情能看到引用了它的业务记录，关联图谱里也会同时出现。',
  },
  {
    q: '外键引用字段显示的是 #12 这样的编号，怎么看名字？',
    a: '外键列会异步加载目标模型的显示名（优先取 <code>name</code> / <code>title</code> / <code>code</code> 字段），'
      + '列表与详情都会显示真实名称。若目标记录没有这几个字段，则回退显示编号。'
      + '建议每个模型至少保留一个 name / title 字段。',
  },
  {
    q: 'AI 辅助能用吗？',
    a: '可以。到「AI 设置」选择服务商、填入 API Key、点「测试连接」即可。'
      + '支持 OpenAI 兼容协议的任意服务（含 MiniMax / DeepSeek / 通义 / Ollama 等）。<br>'
      + '即使外部接口不可用（额度耗尽、断网），系统也会自动降级为本地规则引擎，'
      + '不会报错中断，只是效果弱一些。',
  },
  {
    q: '上传的文件到底存在哪里？',
    a: '存在<b>数据库</b>里。v0.2 起文件原文（BLOB）与元数据一起写进 <code>kb.db</code>，'
      + '不再是「磁盘放文件、数据库存路径」的两套账。<br>'
      + '好处：备份只需拷走 <code>data/</code> 目录；删除记录不会留下孤儿文件；'
      + '文件内容与检索索引天然同源，AI 能直接读到。<br>'
      + '代价：SQLite 读大文件会整块进内存，所以单文件超过 200MB 时上传结果里会附带提示（不阻止上传）。',
  },
  {
    q: '为什么搜中文两个字搜不到（或搜不到文件正文）？',
    a: '中文没有天然空格，SQLite 默认会把一整串汉字当成一个词。'
      + '本系统在建立索引时把汉字<b>逐字切开</b>，查询时再作为短语匹配，'
      + '所以「深圳」「付款」这类两字词都能命中。<br>'
      + '另外要能搜到<b>正文</b>，前提是该格式支持正文抽取（PDF / Word / Excel / PPT / CSV / 文本）。'
      + '扫描件图片型 PDF、音视频没有文字可抽，只能按文件名检索。',
  },
  {
    q: '「语义检索」和「关键词检索」有什么区别？',
    a: '关键词检索（FTS5）匹配<b>字面</b>：搜「付款条件」只会命中含这几个字的段落。<br>'
      + '语义检索（sqlite-vec）匹配<b>意思</b>：搜「付款条件」也可能命中写着「结算方式」的段落，'
      + '因为它们的向量接近。<br>'
      + '数据中心工具栏可切换「关键词 / 混合 / 语义」；混合模式会把两路结果融合排序，通常效果最好。'
      + '语义检索依赖 embedding 接口，若未配置或额度不足会自动退回关键词检索，功能不中断。',
  },
  {
    q: '向量索引显示「失败」，会影响使用吗？',
    a: '不影响。文件照样能上传、预览、下载、删除，关键词检索也正常，'
      + '只是<b>少了「按意思搜」</b>这一路。<br>'
      + '常见原因是 embedding 额度不足（MiniMax 会返回 <code>insufficient balance</code>）'
      + '或模型名不对。到「AI 设置 → 向量检索」点「测试向量化」可以看到具体报错；'
      + '修好后系统会自动熔断恢复，不需要重启。',
  },
]
</script>

<style scoped>
.card-title-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 500;
}

/* ===== 心智模型流程 ===== */
.flow {
  display: flex;
  align-items: stretch;
  gap: 4px;
  flex-wrap: wrap;
}
.flow-item { display: flex; align-items: center; gap: 4px; flex: 1 1 140px; }
.flow-node {
  flex: 1;
  padding: 14px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
  cursor: pointer;
  text-align: center;
  transition: all var(--duration-fast) var(--ease-out);
}
.flow-node:hover {
  border-color: var(--primary);
  background: var(--primary-50);
  transform: translateY(-2px);
}
.flow-icon {
  width: 40px; height: 40px;
  margin: 0 auto 8px;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.flow-title { font-weight: 700; font-size: var(--text-sm); margin-bottom: 3px; }
.flow-desc { font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.5; }
.flow-arrow { color: var(--text-tertiary); flex-shrink: 0; }

.analogy {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: var(--space-4);
  padding: 12px 16px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.75;
}
.analogy .el-icon { color: var(--primary); margin-top: 3px; flex-shrink: 0; }
.analogy b { color: var(--text-primary); }
.analogy code,
.faq-a code {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--primary);
}

/* ===== 五步 ===== */
.steps { display: flex; flex-direction: column; gap: var(--space-3); }
.step {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  background: var(--bg-card);
  transition: border-color var(--duration-fast);
}
.step:hover { border-color: var(--primary-200); }
.step-no {
  width: 28px; height: 28px; flex-shrink: 0;
  border-radius: 50%;
  background: var(--primary-grad);
  color: #fff;
  font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  font-size: var(--text-xs);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.2) inset;
}
.step-body { flex: 1; min-width: 0; }
.step-title { font-weight: 650; font-size: var(--text-md); margin-bottom: 6px; letter-spacing: -0.2px; }
.step-desc {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.8;
}
.step-desc b { color: var(--text-primary); }
.step-actions { margin-top: 10px; }

/* ===== 格式支持 ===== */
.fmt-legend {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: var(--space-3);
}
.fmt-legend span { display: inline-flex; align-items: center; gap: 6px; }
.dot {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}
.dot.ok { background: var(--success); }
.dot.part { background: var(--warning); }
.dot.no { background: var(--text-tertiary); }

.fmt-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 8px;
}
.fmt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}
.fmt-status {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.fmt-status.ok { background: var(--success); }
.fmt-status.part { background: var(--warning); }
.fmt-status.no { background: var(--text-tertiary); }
.fmt-label { font-weight: 600; min-width: 84px; }
.fmt-ext {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
  min-width: 116px;
}
.fmt-note { color: var(--text-secondary); font-size: var(--text-xs); }

/* ===== 存储与检索 ===== */
.store-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--space-3);
}
.store-item {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
}
.store-icon {
  width: 34px; height: 34px; flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
  font-size: 17px;
}
.store-body { flex: 1; min-width: 0; }
.store-title {
  font-weight: 650;
  font-size: var(--text-sm);
  margin-bottom: 4px;
  letter-spacing: -0.1px;
}
.store-desc {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.75;
}
.store-desc b { color: var(--text-primary); }

/* ===== FAQ ===== */
.faq :deep(.el-collapse-item__header) { font-weight: 600; }
.faq-q { font-size: var(--text-base); }
.faq-a {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.85;
}
.faq-a b { color: var(--text-primary); }

@media (max-width: 1000px) {
  .flow-item { flex-basis: 100%; }
  .flow-arrow { display: none; }
}
</style>
