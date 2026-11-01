<template>
  <div class="page lib-page">
    <PageTitle
      title="养料库"
      subtitle="DNA 养料库：把资料变成可复用的基因，断网时靠它撑住整个系统"
      icon-key="DataBoard"
    >
      <el-button :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button :loading="absorbing" @click="absorbAll">
        <el-icon><Download /></el-icon>全库吸收
      </el-button>
      <el-button @click="exportBundle">
        <el-icon><FolderOpened /></el-icon>导出养料库
      </el-button>
    </PageTitle>

    <!-- 离线横幅：断网时整个界面要立刻说清楚自己处在什么状态 -->
    <transition name="band">
      <div v-if="overview?.offline" class="offline-band">
        <el-icon><WarningFilled /></el-icon>
        <div class="band-text">
          <b>离线模式已开启</b>
          <span>语义检索与答案生成已关闭（它们要网络），系统改用养料库的本地索引直答。</span>
        </div>
        <el-button size="small" @click="toggleOffline(false)">退出离线模式</el-button>
      </div>
    </transition>

    <el-alert v-if="error" type="error" :closable="false" show-icon class="lib-alert">
      {{ error }}
    </el-alert>

    <div v-loading="loading && !overview" class="lib-body">
      <!-- ============ 一、凝胶电泳：库里有多少、什么种类 ============ -->
      <section v-if="overview" class="section">
        <div class="sec-head">
          <span class="sec-no">01</span>
          <h3 class="sec-title">凝胶电泳</h3>
          <span class="sec-note">每条泳道是一类基因 · 条带越多，这类知识越多</span>
          <span class="sec-rule" />
          <span class="sec-hint">点泳道可筛选清单</span>
        </div>

        <div class="gel-card">
          <div class="gel-left">
            <div class="gel-total">
              <span class="num">{{ overview.total }}</span>
              <span class="unit">条基因</span>
            </div>
            <p class="gel-desc">{{ gelDesc }}</p>
            <div class="gel-chips">
              <button
                type="button" class="chip chip-btn"
                :class="{ 'is-on': geneFlag === 'used' }"
                title="只看被用过的基因" @click="setFlag('used')"
              >{{ overview.health.used }} 条被用过</button>
              <span class="chip">累计引用 {{ overview.health.usage_total }} 次</span>
              <button
                type="button" class="chip chip-btn"
                :class="{ 'is-on': geneFlag === 'cold' }"
                title="只看没人用的基因 —— 该复核了" @click="setFlag('cold')"
              >冷基因 {{ overview.health.cold }}</button>
              <span class="chip">源码销毁 {{ overview.health.destroyed_sources }}</span>
              <button
                v-if="overview.health.superseded"
                type="button" class="chip chip-btn"
                :class="{ 'is-on': statusFilter === 'superseded' }"
                title="看被取代的旧版本" @click="setStatus('superseded')"
              >已被取代 {{ overview.health.superseded }}</button>
            </div>
          </div>

          <!-- 泳道：一条泳道 = 一类基因，条带一条 = 一条基因 -->
          <div class="gel-lanes">
            <button
              v-for="k in overview.kinds"
              :key="k.key"
              type="button"
              class="base-cell"
              :class="[k.key, { 'is-on': kindFilter === k.key }]"
              :title="`${k.label}：${k.desc}（点击筛选这一类）`"
              @click="filterByKind(k.key)"
            >
              <span class="lane-well" />
              <span class="lane-track" :style="laneStyle(k.count)">
                <span
                  v-for="b in bandsOf(k.count)"
                  :key="b"
                  class="base-bar lane-band"
                  :style="{ '--i': b }"
                />
              </span>
              <span class="base-num">{{ k.count }}</span>
              <span class="base-label">{{ k.label }}</span>
              <span class="base-desc">{{ k.desc }}</span>
            </button>
          </div>
        </div>
      </section>

      <!-- ============ 二、质检报告：哪些是问题 ============ -->
      <section v-if="overview" class="section">
        <div class="sec-head">
          <span class="sec-no">02</span>
          <h3 class="sec-title">质检报告</h3>
          <span class="sec-note">坏项亮出来，好项安静待着</span>
          <span class="sec-rule" />
        </div>

        <div class="health-strip">
          <div
            v-for="h in healthItems"
            :key="h.key"
            class="health-cell"
            :class="{ 'is-bad': h.count > 0, 'is-ok': h.count === 0 }"
          >
            <button
              type="button"
              class="hc-num"
              :class="{ 'is-link': !!h.action }"
              :title="h.action ? '点开这一类' : ''"
              :disabled="!h.action"
              @click="h.action && applyHealthAction(h)"
            >{{ h.count }}</button>
            <div class="hc-label">{{ h.label }}</div>
            <div class="hc-hint">{{ h.hint }}</div>
            <div v-if="h.samples && h.samples.length" class="hc-samples">
              <button
                v-for="g in h.samples.slice(0, 3)"
                :key="g.id"
                type="button"
                class="hc-sample"
                @click="openGeneById(g.id)"
              >{{ g.title }}</button>
              <button
                v-if="h.samples.length > 3"
                type="button"
                class="hc-sample hc-sample-more"
                @click="h.action && applyHealthAction(h)"
              >还有 {{ h.samples.length - 3 }} 条 →</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 三、基因清单 ============ -->
      <section v-if="overview" class="section">
        <div class="sec-head">
          <span class="sec-no">03</span>
          <h3 class="sec-title">基因清单</h3>
          <span class="sec-note">点一行看全文</span>
          <span class="sec-rule" />
          <span v-if="geneFlag" class="flag-tag">
            {{ FLAG_LABEL[geneFlag] }}
            <el-icon class="flag-x" @click="setFlag('')"><Close /></el-icon>
          </span>
        </div>

        <div class="panel">
          <div class="kind-filter">
            <el-input
              v-model="geneQuery"
              size="small"
              class="gene-search"
              placeholder="按标题找基因"
              clearable
              @keyup.enter="loadGenes(0)"
              @clear="loadGenes(0)"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-radio-group v-model="kindFilter" size="small" @change="loadGenes(0)">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="k in overview.kinds" :key="k.key" :value="k.key">
                {{ k.label }} {{ k.count }}
              </el-radio-button>
            </el-radio-group>
            <el-select v-model="statusFilter" size="small" class="status-filter" @change="loadGenes(0)">
              <el-option label="当前基因" value="active" />
              <el-option label="已被取代" value="superseded" />
              <el-option label="全部" value="all" />
            </el-select>
            <el-select v-model="geneSort" size="small" class="status-filter" @change="loadGenes(0)">
              <el-option label="按种类" value="id" />
              <el-option label="按表达度" value="usage" />
              <el-option label="按最近更新" value="updated" />
              <el-option label="按置信度" value="confidence" />
            </el-select>
          </div>

          <el-table
            :data="genes" class="ptable gene-table" v-loading="loading && !genes.length" row-key="id"
            :row-class-name="geneRowClass"
            @row-click="openGene"
          >
            <el-table-column prop="kind" label="种类" width="92">
              <template #default="{ row }">
                <span class="kind-cell">
                  <span class="kind-dot" :class="row.kind" />
                  {{ kindLabel(row.kind) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="240">
              <template #default="{ row }">
                <div class="gene-title">{{ row.title }}</div>
                <div class="gene-sum">{{ row.summary }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="source_title" label="来源" min-width="150" class-name="src-cell" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <span v-if="row.status === 'superseded'" class="gene-superseded">已被取代</span>
                <span v-else-if="row.meta && row.meta.destroyed" class="gene-destroyed">已销毁源</span>
                <span v-else class="gene-live">当前</span>
              </template>
            </el-table-column>
            <el-table-column prop="usage_count" label="表达度" width="86" sortable class-name="num-cell" />
            <el-table-column label="置信" width="76" class-name="num-cell">
              <template #default="{ row }">{{ row.confidence }}</template>
            </el-table-column>
          </el-table>
          <div class="gene-pager">
            <span class="pager-note">共 {{ geneTotal }} 条基因</span>
            <el-pagination
              v-model:current-page="genePage"
              :page-size="genePageSize"
              :total="geneTotal"
              layout="prev, pager, next"
              small
              background
              @current-change="loadGenes"
            />
          </div>
        </div>
      </section>

      <!-- ============ 四、检索与离线直答 ============ -->
      <section class="section">
        <div class="sec-head">
          <span class="sec-no">04</span>
          <h3 class="sec-title">基因检索与离线直答</h3>
          <span class="sec-note">直答 = 不调模型，把基因与原文原样端出来</span>
          <span class="sec-rule" />
        </div>

        <div class="panel">
          <div class="ask-row">
            <el-input
              v-model="query"
              placeholder="问一句：比如「投标截止时间是什么时候」「有哪些经验」"
              clearable
              @keyup.enter="doSearch"
            />
            <el-button type="primary" :loading="searching" @click="doSearch">检索基因</el-button>
            <el-button :loading="searching" @click="doAnswer">离线直答</el-button>
          </div>

          <div v-if="answer" class="answer-box">
            <div class="answer-head">
              <span class="answer-tag">直答</span>
              <span class="answer-note">未调用模型，以下均为养料库中的原始记录</span>
            </div>
            <pre class="answer-text">{{ answer.text }}</pre>
            <div v-if="answer.genes && answer.genes.length" class="answer-genes">
              <span class="ag-label">命中基因</span>
              <span v-for="g in answer.genes" :key="g.gene.id" class="ag-chip" :class="g.gene.kind">
                {{ g.gene.title }}
              </span>
            </div>
          </div>

          <div v-if="hits.length" class="gene-list">
            <div v-for="h in hits" :key="h.gene.id" class="gene-row" :class="h.gene.kind">
              <span class="gene-kind" :class="h.gene.kind">{{ kindLabel(h.gene.kind) }}</span>
              <div class="gene-main">
                <div class="gene-title">{{ h.gene.title }}</div>
                <div class="gene-sum">{{ h.gene.summary }}</div>
                <div class="gene-meta">
                  <span>来源：{{ h.gene.source_title || h.gene.source_kind || '养料库' }}</span>
                  <span>被用 {{ h.gene.usage_count }} 次</span>
                  <span>置信 {{ h.gene.confidence }}</span>
                  <span v-if="h.gene.meta?.destroyed" class="gene-destroyed">原文已销毁</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 五、吸收 / 断网可用性（操作区） ============ -->
      <section class="section">
        <div class="sec-head">
          <span class="sec-no">05</span>
          <h3 class="sec-title">吸收与断网可用性</h3>
          <span class="sec-note">怎么往里放 · 断网之后还剩什么</span>
          <span class="sec-rule" />
        </div>

        <div class="work-grid">
          <!-- 五之一、吸收 -->
          <div class="work-panel">
            <div class="card-head">
              <h3>吸收</h3>
              <span class="card-note">把资料变成基因；源码只留经验，原文销毁</span>
            </div>

            <el-tabs v-model="absorbTab" class="absorb-tabs">
              <el-tab-pane label="文本" name="text">
                <el-input
                  v-model="absorbText"
                  type="textarea"
                  :rows="5"
                  placeholder="粘一段资料（结构化、非结构化都行）。库会按「这段话的价值在哪」拆成事实/方法/经验/接口/约定。"
                />
                <div class="absorb-row">
                  <el-input v-model="absorbTitle" placeholder="标题（可留空）" style="flex:1" />
                  <el-button type="primary" :loading="absorbing" @click="absorbTextNow">吸收</el-button>
                </div>
              </el-tab-pane>

              <el-tab-pane label="源码（吸收后销毁）" name="code">
                <el-alert type="warning" :closable="false" show-icon class="code-alert">
                  源码会被静态分析，抽出方法与经验；<b>原文不入库</b>，只留一份销毁证明（指纹 + 时间 + 文件名）。
                </el-alert>
                <el-input v-model="codeFilename" placeholder="文件名，如 utils.py" style="margin-bottom:8px" />
                <el-input
                  v-model="absorbCode"
                  type="textarea"
                  :rows="5"
                  placeholder="粘源码…"
                />
                <div class="absorb-row">
                  <el-switch v-model="destroySource" active-text="蒸馏后销毁原文" />
                  <el-button type="primary" :loading="absorbing" @click="absorbCodeNow">蒸馏吸收</el-button>
                </div>

                <el-divider>或：从文件库里选一份已上传的源码</el-divider>
                <div class="src-pick">
                  <el-select
                    v-model="sourceDocId"
                    placeholder="选择文件库里的源码文件"
                    filterable
                    clearable
                    style="flex:1"
                  >
                    <el-option
                      v-for="d in sourceDocs"
                      :key="d.id"
                      :label="`${d.title}（${d.ext || '无扩展名'}）`"
                      :value="d.id"
                    />
                  </el-select>
                  <el-switch v-model="destroySourceFile" active-text="销毁源文件" />
                  <el-button type="danger" plain :loading="absorbing" @click="absorbSourceNow">
                    吸收并销毁
                  </el-button>
                </div>
                <div class="src-hint">
                  销毁顺序是固定的：先蒸馏成基因、先写销毁证明，然后才删磁盘上的源文件、清掉库里的抽取正文。
                  证明没落库就不删 —— 文件没了证据也没了，等于什么都没留下。
                </div>
              </el-tab-pane>
              <!-- 第三个 tab：把一整棵源码树交进来 -->
              <el-tab-pane label="源码树（整系统）" name="tree">
                <div class="tree-pick">
                  <button type="button" class="pick-btn" @click="pickDir">
                    <el-icon><FolderOpened /></el-icon>选整个目录
                  </button>
                  <button type="button" class="pick-btn" @click="pickZip">
                    <el-icon><Box /></el-icon>选一个 zip
                  </button>
                  <input
                    ref="dirInput" type="file" webkitdirectory multiple hidden
                    @change="onDirPicked"
                  />
                  <input
                    ref="zipInput" type="file" accept=".zip" hidden
                    @change="onZipPicked"
                  />
                  <span class="pick-hint">
                    目录保留相对路径（后端按路径建目录结构）；zip 在服务端安全解压
                  </span>
                </div>

                <div v-if="treeFiles.length" class="tree-pending">
                  <div class="tp-count">
                    <span class="tp-num">{{ treeFiles.length }}</span>
                    <span class="tp-unit">个文件</span>
                    <span class="tp-size">{{ treeSizeMb }} MB</span>
                    <span v-if="isZipPick" class="tp-zip">zip</span>
                  </div>
                  <el-input
                    v-model="treeTitle" size="small" class="tp-title"
                    placeholder="这次学习的名字"
                  />
                  <el-button type="primary" :loading="uploading" @click="startLearn">
                    <el-icon><VideoPlay /></el-icon>开始学习
                  </el-button>
                </div>

                <div v-if="uploadPhase" class="tree-progress">
                  <div class="tprog-head">
                    <span class="tprog-stage" :class="treePhaseTone">{{ treePhaseText }}</span>
                    <span class="tprog-hint">{{ treePhaseHint }}</span>
                  </div>
                  <el-progress
                    :percentage="uploadPhase === 'upload' ? uploadPercent : lastJobPercent"
                    :stroke-width="6"
                    :status="uploadPhase === 'parse' && lastJobPercent >= 100 ? 'success' : undefined"
                  />
                </div>

                <div class="tree-note" :class="{ 'is-open': treeNoteOpen }">
                  <div class="tn-head" @click="treeNoteOpen = !treeNoteOpen">
                    <el-icon><InfoFilled /></el-icon>
                    <span class="tn-lead">源码会被静态分析成基因，<b>原文不入库</b></span>
                    <el-icon class="tn-arrow"><ArrowRight /></el-icon>
                  </div>
                  <ul v-show="treeNoteOpen" class="tn-body">
                    <li>每个文件解析完先写销毁证明（sha256 + 时间 + 文件名），<b>然后</b>才删源码 —— 顺序是固定的。</li>
                    <li>证明没落库就不删：文件没了证据也没了，等于什么都没留下。</li>
                    <li>进库的只有蒸馏出的方法与经验；资料原文永远不进养料库。</li>
                  </ul>
                </div>
              </el-tab-pane>
            </el-tabs>

            <div v-if="lastAbsorb" class="absorb-result">
              <div class="ar-title">
                <el-icon><CircleCheckFilled /></el-icon>
                吸收完成：{{ lastAbsorb.genes }} 条基因
                <span v-if="lastAbsorb.destroyed" class="ar-destroy">原文已销毁</span>
              </div>
              <div v-if="lastAbsorb.summary" class="ar-line">摘要：{{ lastAbsorb.summary }}</div>
              <div v-if="lastAbsorb.attestation" class="ar-line mono">
                销毁证明：sha256={{ lastAbsorb.attestation.sha256.slice(0, 24) }}… ·
                {{ lastAbsorb.attestation.destroyed_at }}
              </div>
              <ul v-if="lastAbsorb.titles && lastAbsorb.titles.length" class="ar-list">
                <li v-for="(t, i) in lastAbsorb.titles" :key="i">{{ t }}</li>
              </ul>
            </div>
          </div>

          <!-- 五之二、断网可用性 -->
          <div class="work-panel">
            <div class="card-head">
              <h3>断网可用性</h3>
              <span class="card-note">断网之后系统还剩什么</span>
            </div>

            <div class="offline-switch">
              <span>离线模式</span>
              <el-switch v-model="offlineLocal" @change="toggleOffline" />
            </div>

            <ul class="cap-list">
              <li v-for="c in overview?.offline_ready?.checks || []" :key="c.key">
                <span class="cap-dot" :class="c.ok ? 'ok' : 'off'" />
                <span class="cap-key">{{ capLabel(c.key) }}</span>
                <span class="cap-detail">{{ c.detail }}</span>
              </li>
            </ul>

            <div class="drill">
              <div class="drill-head">
                <span>断网演练</span>
                <el-button size="small" :loading="drilling" @click="runDrill">跑一遍</el-button>
              </div>
              <div v-if="drillResult" class="drill-result">
                <div class="drill-score" :class="drillResult.ok ? 'ok' : 'bad'">
                  {{ drillResult.passed }}/{{ drillResult.total }} 题 · {{ drillResult.ms }}ms
                </div>
                <ul class="drill-list">
                  <li v-for="(r, i) in drillResult.results" :key="i">
                    <span class="cap-dot" :class="r.ok ? 'ok' : 'off'" />
                    <span class="drill-q">{{ r.question }}</span>
                    <span class="drill-ms">{{ r.ms }}ms</span>
                  </li>
                </ul>
                <div class="drill-note">{{ drillResult.note }}</div>
              </div>
              <div v-else class="drill-hint">
                演练只用养料库的本地索引跑一遍问答（含一道拒答题），全程不调模型、不调 embedding。
              </div>
            </div>
          </div>

          <!-- 05 之二、学习任务：后台在读源码，前端只管报进度 -->
          <div class="jobs-block">
            <div class="jobs-head">
              <h3>学习任务</h3>
              <span class="jobs-note">后台逐个文件读源码、抽基因；进度每 1.5 秒自己刷一次</span>
              <span class="sec-rule" />
              <el-button size="small" :loading="jobsLoading" @click="loadJobs">
                <el-icon><Refresh /></el-icon>刷新
              </el-button>
            </div>

            <div v-if="!jobs.length" class="jobs-empty">
              还没有学习任务 —— 把一整个系统的源码交进来，它会自己读、自己学
            </div>

            <ul v-else class="jobs-list">
              <li v-for="j in jobs" :key="j.id" class="job-row" :class="j.status">
                <div class="job-top">
                  <span class="job-status" :class="j.status">{{ jobStatusLabel(j.status) }}</span>
                  <span class="job-title">{{ j.title }}</span>
                  <span class="job-ops">
                    <el-button
                      v-if="j.status === 'running' || j.status === 'pending'"
                      size="small" text @click="cancelJob(j)"
                    >取消</el-button>
                    <el-button size="small" text @click="toggleJobDetail(j.id)">
                      {{ expandedJobs.includes(j.id) ? '收起' : '明细' }}
                    </el-button>
                  </span>
                </div>
                <el-progress
                  :percentage="Math.round(j.percent || 0)"
                  :stroke-width="4"
                  :show-text="false"
                  :status="j.status === 'failed' ? 'exception' : (j.status === 'done' ? 'success' : undefined)"
                />
                <div class="job-meta">
                  <span v-if="j.current" class="job-current">当前解析：{{ j.current }}</span>
                  <span>生成 <b>{{ j.created || 0 }}</b> 条基因</span>
                  <span>跳过 {{ j.skipped || 0 }}</span>
                  <span>失败 {{ j.failed || 0 }}</span>
                  <span>耗时 {{ jobElapsed(j) }}</span>
                  <span v-if="j.error" class="job-err">{{ j.error }}</span>
                </div>
                <div v-show="expandedJobs.includes(j.id)" class="job-detail">
                  <div v-for="(d, i) in j.detail || []" :key="i" class="jd-row">
                    <span class="jd-file">{{ d.file }}</span>
                    <span class="jd-lang">{{ d.language || '—' }}</span>
                    <span class="jd-lines">{{ d.lines || 0 }} 行</span>
                    <span class="jd-genes">{{ d.genes || 0 }} 基因</span>
                    <span class="jd-destroy" :class="{ on: d.destroyed }">
                      {{ d.destroyed ? '已销毁' : '未销毁' }}
                    </span>
                    <span class="jd-note">{{ d.note || d.status }}</span>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- ============ 06 自进化账本 ============ -->
      <section class="section">
        <div class="sec-head">
          <span class="sec-no">06</span>
          <h3 class="sec-title">自进化账本</h3>
          <span class="sec-note">不断喂养，知识自己会长：资料变基因，基因连成网，网上的知识被检索、被引用、被直答</span>
          <span class="sec-rule" />
        </div>

        <div class="panel">
          <div class="evo-gens">
            <div v-for="g in evolution?.generations || []" :key="g.stage" class="gen-card">
              <div class="gen-stage">{{ g.stage }}</div>
              <div class="gen-value">{{ g.value }}</div>
              <div class="gen-label">{{ g.label }}</div>
              <div class="gen-note">{{ g.note }}</div>
              <div v-if="g.stage === '二生三' && (gaps?.open_count ?? 0) > 0" class="gen-foot">
                还差 {{ gaps.open_count }} 个问题没补上
              </div>
            </div>
          </div>

          <div class="evo-totals">
            <span>基因 <b>{{ evolution?.totals?.genes_total ?? 0 }}</b></span>
            <span>在用 <b>{{ evolution?.totals?.genes_active ?? 0 }}</b></span>
            <span>被引用 <b>{{ evolution?.totals?.usage_total ?? 0 }}</b> 次</span>
            <span>资料 <b>{{ evolution?.totals?.documents ?? 0 }}</b></span>
            <span>记录 <b>{{ evolution?.totals?.records ?? 0 }}</b></span>
            <span>吸收轮次 <b>{{ evolution?.totals?.absorb_rounds ?? 0 }}</b></span>
          </div>

          <div class="evo-chart-wrap">
            <div class="evo-chart-title">
              成长曲线 · 按天新增基因
              <span v-if="evoTimeline.length" class="evo-latest">最近一天 {{ evoTimeline[evoTimeline.length - 1].day }}</span>
            </div>
            <div class="evo-chart">
              <div
                v-for="(d, i) in evoTimeline" :key="d.day" class="evo-col"
                :class="{ 'is-latest': i === evoTimeline.length - 1 }"
                :title="`${d.day}：新增 ${d.genes} 条基因`"
              >
                <span class="evo-bar" :style="{ height: evoBarH(d.genes) + '%' }" />
                <span class="evo-day">{{ String(d.day).slice(5) }}</span>
              </div>
              <div v-if="!evoTimeline.length" class="evo-empty">还没有成长记录</div>
            </div>
          </div>

          <div class="evo-gaps">
            <div class="gaps-head">
              <span class="gaps-title">还答不上来的问题</span>
              <span class="gaps-note">缺口 = 该补还没补的知识 · 被问得越多，越该先喂</span>
              <span class="sec-rule" />
              <span class="gaps-count">还差 {{ gaps?.open_count ?? 0 }} 个</span>
            </div>

            <div v-if="!gapList.length" class="gaps-empty">
              还没有缺口 —— 问它答不上来的问题，它会记在这里
            </div>

            <ul v-else class="gaps-list">
              <li v-for="g in gapList" :key="g.id" class="gap-row">
                <span class="gap-q">{{ g.question }}</span>
                <span v-if="(g.asked || 0) > 1" class="gap-asked">问了 {{ g.asked }} 次</span>
                <span class="gap-last">{{ g.last_asked_at ? fmtTime(g.last_asked_at) : '' }}</span>
                <el-button size="small" text @click="closeGap(g)">已补上</el-button>
              </li>
            </ul>
          </div>

          <div class="evo-feed">
            <div class="feed-head">
              <span class="feed-title">自动喂养</span>
              <span class="feed-note">每隔一段时间自动吸收新资料 —— 人不用管，知识自己会长</span>
            </div>
            <div class="feed-row">
              <el-switch v-model="feedEnabled" @change="saveAutoFeed" />
              <span class="feed-label">{{ feedEnabled ? '已开启' : '已关闭' }}</span>
              <el-input-number
                v-model="feedInterval" :min="5" :max="1440" :step="5" size="small"
                :disabled="!feedEnabled" @change="saveAutoFeed"
              />
              <span class="feed-unit">分钟一轮</span>
              <el-button size="small" :loading="feedRunning" @click="runAutoFeed">
                <el-icon><VideoPlay /></el-icon>立刻喂一轮
              </el-button>
            </div>
            <div class="feed-last">
              最近一次自动吸收：
              {{ evolution?.auto_feed?.last_run_at
                ? fmtTime(evolution.auto_feed.last_run_at)
                : (localFeedAt ? fmtTime(localFeedAt) + '（本机触发）' : '还没有') }}
              <span v-if="evolution?.auto_feed?.last_result" class="feed-result">
                · {{ evolution.auto_feed.last_result }}
              </span>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 基因详情抽屉：点清单里的一行 -->
    <el-drawer
      v-model="geneDrawer"
      :size="detailSize"
      direction="rtl"
      :title="detail ? `${KIND_LABEL[detail.kind] || detail.kind} · ${detail.title}` : '基因详情'"
    >
      <div v-if="detail" class="gene-detail">
        <div class="gd-meta">
          <span class="chip">被用 {{ detail.usage_count }} 次</span>
          <span class="chip">置信 {{ detail.confidence }}</span>
          <span class="chip">来源：{{ detail.source_title || detail.source_kind || '养料库' }}</span>
          <span v-if="detail.meta && detail.meta.destroyed" class="chip danger">原文已销毁</span>
          <span v-if="detail.status === 'superseded'" class="chip danger">已被取代</span>
        </div>
        <pre class="gd-content">{{ detail.content }}</pre>
        <div v-if="detail.tags && detail.tags.length" class="gd-tags">
          <span v-for="t in detail.tags" :key="t" class="chip">{{ t }}</span>
        </div>
        <div class="gd-foot">
          <span class="gd-time">创建 {{ fmtTime(detail.created_at) }}</span>
          <span class="gd-time">更新 {{ fmtTime(detail.updated_at) }}</span>
        </div>
        <div v-if="detail.source_ref && detail.source_ref.startsWith('doc-')" class="gd-actions">
          <el-button size="small" @click="gotoDocument(detail.source_ref)">
            <el-icon><Document /></el-icon>去数据中心看这份资料
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
/**
 * 养料库 —— DNA 养料库的操作台
 *
 * 这个页面回答四个问题：
 *   库里有什么（基因清单、种类分布、表达度）
 *   怎么往里放（吸收文本 / 蒸馏源码 / 全库吸收）
 *   断网了还能用吗（离线开关 + 可用性自检 + 断网演练）
 *   怎么带走（导出养料库包）
 *
 * 视觉上刻意与「养料 DNA」页同族：那是体检报告，这是操作台。
 * 五种基因用五种碱基色（A/T/G/C + 中性色）区分，跟 DNA 页的测序风格对齐。
 *
 * 整页的视觉隐喻是**凝胶电泳**：
 *   实验室里把样本放进泳道跑电泳，凝胶上留下的条带就是结果 ——
 *   条带多 = 这类东西多，条带亮 = 这类东西被用得多。
 *   所以：库概览 = 一块凝胶，五类基因 = 五条泳道，条带 = 基因；
 *   体检 = 质检报告条；清单 = 读带结果；吸收/断网 = 工作台。
 *   泳道可以点：点一下就把清单筛到那一类（filterByKind）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PageTitle from '../components/PageTitle.vue'
import { Api } from '../api'

const loading = ref(false)
const error = ref('')
const overview = ref(null)
const genes = ref([])
const hits = ref([])
const answer = ref(null)
const drillResult = ref(null)
const lastAbsorb = ref(null)
const absorbing = ref(false)
const searching = ref(false)
const drilling = ref(false)
const offlineLocal = ref(false)
const kindFilter = ref('')
const statusFilter = ref('active')
const geneQuery = ref('')
const geneFlag = ref('')
const FLAG_LABEL = {
  cold: '只看冷基因（没人用）',
  used: '只看用过的基因',
  no_source: '只看没出处的基因',
  low_conf: '只看低置信的基因',
}
const geneSort = ref('id')
const genePage = ref(1)
const genePageSize = 50
const geneTotal = ref(0)
const geneDrawer = ref(false)
const detail = ref(null)
const query = ref('')
const absorbTab = ref('text')
const absorbText = ref('')
const absorbTitle = ref('')
const absorbCode = ref('')
const codeFilename = ref('snippet.py')
const destroySource = ref(true)
const destroySourceFile = ref(false)
const sourceDocId = ref(null)
const sourceDocs = ref([])

const KIND_LABEL = {
  fact: '事实', method: '方法', experience: '经验',
  interface: '接口', policy: '约定',
}
const KIND_DESC = {
  fact: '是什么', method: '怎么做', experience: '踩过什么坑',
  interface: '怎么调', policy: '必须怎么做',
}

function kindLabel(k) {
  return KIND_LABEL[k] || k
}

/** 点碱基柱：按那一类筛基因清单（再点一次取消） */
function filterByKind(key) {
  kindFilter.value = kindFilter.value === key ? '' : key
  loadGenes()
  // 筛完把清单带到视野里 —— 否则点了柱子，变化在屏幕外，看不到效果
  nextTick(() => {
    document.querySelector('.lib-body .ptable')?.scrollIntoView({
      behavior: 'smooth', block: 'center',
    })
  })
}

function capLabel(k) {
  return {
    knowledge: '资料原文', fts: '全文检索', genes: '基因库',
    vector: '语义检索', llm: '答案生成',
  }[k] || k
}

const maxKind = computed(() => {
  const kinds = overview.value?.kinds || []
  return kinds.length ? Math.max(...kinds.map((k) => k.count), 1) : 1
})

function baseHeight(count) {
  const max = maxKind.value
  if (!max) return 4
  return Math.max(6, Math.round((count / max) * 100))
}

/**
 * 泳道里画几条带：一条带 = 一条基因。
 * 超过 24 条就不画了 —— 再多也看不清，条数由旁边的数字说话。
 */
function bandsOf(count) {
  return Math.max(0, Math.min(24, count || 0))
}

/**
 * 泳道的填充：条带本身高度固定，间距按「这一类占全库多少」摊开。
 * 这样填充高度就等于数量占比 —— 类越多，条带堆得越高（真的像在跑胶）。
 */
function laneStyle(count) {
  const avail = 164                 // 轨道可用高度（172 - 上下 padding）
  const n = Math.max(1, bandsOf(count))
  const filled = (baseHeight(count) / 100) * avail   // 填充高度 = 数量占比
  const bandH = 6
  const gap = n > 1
    ? Math.max(0, Math.min(6, (filled - n * bandH) / (n - 1)))
    : 0
  return { gap: gap.toFixed(2) + 'px' }
}

/** 行样式钩子：给行带上种类类名，左侧色条靠它上色 */
function geneRowClass({ row }) {
  const out = [`kind-${row.kind}`]
  if (row.status === 'superseded') out.push('is-superseded')
  return out.join(' ')
}

/** 概览一句话：最多的是哪一类，冷基因有多少 */
const gelDesc = computed(() => {
  const o = overview.value
  if (!o) return ''
  const kinds = o.kinds || []
  if (!kinds.length) return ''
  const top = kinds.slice().sort((a, b) => b.count - a.count)[0]
  const cold = o.health?.cold || 0
  const used = o.health?.used || 0
  const tail = cold
    ? `其中 ${cold} 条还没被用过（用过的 ${used} 条），值得回头看一眼。`
    : `${used} 条被真正用上了。`
  return `最多的是「${top.label}」（${top.count} 条 · ${top.desc}）。${tail}`
})

watch(offlineLocal, (v) => {
  if (overview.value && v !== overview.value.offline) {
    // 用户拨了开关但还没落库 —— 以服务端为准，别让界面先撒谎
    offlineLocal.value = overview.value.offline
  }
})

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, list] = await Promise.all([
      Api.dnaLibraryOverview(),
      Api.dnaLibraryGenes({
        kind: kindFilter.value, status: statusFilter.value,
        q: geneQuery.value, sort: geneSort.value, flag: geneFlag.value,
        limit: genePageSize }),
    ])
    overview.value = ov
    offlineLocal.value = !!ov.offline
    genes.value = list.items || []
    geneTotal.value = list.total || 0
  } catch (e) {
    error.value = '养料库读取失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
  await loadSourceDocs()
  // 账本与任务跟着页面一起刷新；它们读不到也不影响主流程
  await Promise.all([loadEvolution(), loadJobs(), loadGaps()])
}

// ============ 源码树（整系统） ============
const dirInput = ref(null)
const zipInput = ref(null)
const treeFiles = ref([])
const treeTitle = ref('')
const treeNoteOpen = ref(false)
const uploading = ref(false)
/** '' | 'upload'（上传中）| 'parse'（后台解析中）—— 上传完 ≠ 解析完 */
const uploadPhase = ref('')
const uploadPercent = ref(0)
const uploadBytes = ref(0)

function todayStr() {
  const d = new Date()
  const p2 = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
}

function defaultTreeTitle() {
  return `源码树 ${todayStr()}`
}

/** 上传阶段的三种说法：上传中 / 后台解析中 / 已入库 */
const treePhaseText = computed(() => {
  if (uploadPhase.value === 'upload') return '上传中'
  if (uploadPhase.value === 'parse') {
    const active = jobs.value.find((x) => x.status === 'running' || x.status === 'pending')
    if (!active && lastJobPercent.value >= 100) return '已入库'
    return '后台解析中'
  }
  return ''
})

/** 阶段的说明文字：上传完 ≠ 解析完，这两件事得分开说清楚 */
const treePhaseHint = computed(() => {
  if (uploadPhase.value === 'upload') {
    return `文件正在送到服务器${uploadBytes ? `（已传 ${(uploadBytes / 1048576).toFixed(1)} MB）` : ''}`
  }
  if (uploadPhase.value === 'parse') {
    if (treePhaseText.value === '已入库') {
      return '后台解析完成 —— 基因已入库，源码按「先写证明、再删文件」的顺序处理掉了'
    }
    return '上传完成 ≠ 解析完成 —— 后台正在逐个文件读源码、抽基因、写销毁证明'
  }
  return ''
})

const treePhaseTone = computed(() => {
  if (uploadPhase.value === 'upload') return 'upload'
  return treePhaseText.value === '已入库' ? 'done' : 'parse'
})

const treeSizeMb = computed(() =>
  (treeFiles.value.reduce((s2, f) => s2 + (f.size || 0), 0) / 1048576).toFixed(2))

const isZipPick = computed(() =>
  treeFiles.value.length === 1 && /\.zip$/i.test(treeFiles.value[0]?.name || ''))

function pickDir() {
  dirInput.value?.click()
}

function pickZip() {
  zipInput.value?.click()
}

function onDirPicked(e) {
  const list = Array.from(e.target.files || [])
  e.target.value = ''          // 允许重复选同一个目录
  treeFiles.value = list
  if (!treeTitle.value.trim()) treeTitle.value = defaultTreeTitle()
}

function onZipPicked(e) {
  const f = (e.target.files || [])[0]
  e.target.value = ''
  treeFiles.value = f ? [f] : []
  if (f && !treeTitle.value.trim()) treeTitle.value = defaultTreeTitle()
}

/** 把一整棵源码树交给后台学 */
async function startLearn() {
  if (!treeFiles.value.length) {
    ElMessage.warning('先选一份源码')
    return
  }
  const fd = new FormData()
  if (isZipPick.value) {
    fd.append('zip', treeFiles.value[0])
  } else {
    // 目录方式必须带相对路径 —— 后端靠它建目录结构
    for (const f of treeFiles.value) fd.append('files', f, f.webkitRelativePath || f.name)
  }
  fd.append('title', (treeTitle.value || '').trim() || defaultTreeTitle())
  fd.append('destroy', 'true')

  uploading.value = true
  uploadPhase.value = 'upload'
  uploadPercent.value = 0
  uploadBytes.value = 0
  try {
    const r = await Api.dnaLibraryUploadSourceTree(fd, (e) => {
      uploadBytes.value = e?.loaded || 0
      // 浏览器不一定给 total（FormData 没有 content-length）——有 total 才报百分比
      if (e?.total) uploadPercent.value = Math.min(99, Math.round((e.loaded / e.total) * 100))
    })
    uploadPhase.value = 'parse'
    uploadPercent.value = 100
    if (r?.job) {
      jobs.value = [r.job, ...jobs.value.filter((j) => j.id !== r.job.id)]
    }
    await loadJobs()
    ElMessage.success('源码已上传，后台开始解析 —— 上传完不等于解析完')
  } catch (e) {
    uploadPhase.value = ''
    ElMessage.error('上传失败：' + (e?.message || e))
  } finally {
    uploading.value = false
  }
}

// ============ 学习任务（后台进度） ============
const jobs = ref([])
const jobsLoading = ref(false)
const expandedJobs = ref([])
let jobTimer = null

const JOB_STATUS_LABEL = {
  pending: '排队中', running: '解析中', done: '已完成',
  failed: '失败', canceled: '已取消',
}

function jobStatusLabel(s) {
  return JOB_STATUS_LABEL[s] || s
}

const hasActiveJobs = computed(() =>
  jobs.value.some((j) => j.status === 'pending' || j.status === 'running'))

/** 正在跑的那个任务的百分比（上传阶段结束后显示它） */
const activeJobPercent = computed(() => {
  const j = jobs.value.find((x) => x.status === 'running' || x.status === 'pending')
  return Math.round(j?.percent || 0)
})

/** 最新一个任务的百分比 —— 刚上传的那个就是它 */
const lastJobPercent = computed(() => Math.round(jobs.value[0]?.percent || 0))

async function loadJobs() {
  try {
    jobsLoading.value = true
    const r = await Api.dnaLibraryJobs({ limit: 20 })
    jobs.value = r?.items || []
    if (hasActiveJobs.value) startJobPolling()
    else stopJobPolling()
  } catch (e) {
    // 任务列表读不到不影响页面其它部分
  } finally {
    jobsLoading.value = false
  }
}

/** 只在有任务在跑的时候轮询 —— 全结束了就停 */
function startJobPolling() {
  if (jobTimer) return
  jobTimer = setInterval(() => { loadJobs() }, 1500)
}

function stopJobPolling() {
  if (jobTimer) {
    clearInterval(jobTimer)
    jobTimer = null
  }
}

async function cancelJob(j) {
  try {
    await Api.dnaLibraryCancelJob(j.id)
    await loadJobs()
    ElMessage.success('已取消')
  } catch (e) {
    ElMessage.error('取消失败：' + (e?.message || e))
  }
}

function toggleJobDetail(id) {
  const i = expandedJobs.value.indexOf(id)
  if (i >= 0) expandedJobs.value.splice(i, 1)
  else expandedJobs.value.push(id)
}

function jobElapsed(j) {
  if (!j.started_at) return '—'
  const s2 = new Date(j.started_at).getTime()
  const e2 = j.finished_at ? new Date(j.finished_at).getTime() : Date.now()
  const ms = Math.max(0, e2 - s2)
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

// ============ 知识缺口：系统还答不上来的问题 ============
const gaps = ref(null)

/** 被问得最多的排前面 —— 那是下一轮最该喂的 */
const gapList = computed(() => {
  const list = gaps.value?.open || []
  return list.slice().sort((a, b) => (b.asked || 0) - (a.asked || 0))
})

async function loadGaps() {
  try {
    gaps.value = await Api.dnaLibraryGaps()
  } catch (e) {
    gaps.value = null
  }
}

/** 手动关掉一条缺口：知识补上了，这条就不用再提醒了 */
async function closeGap(g) {
  try {
    await Api.dnaLibraryCloseGap(g.id)
    const open = (gaps.value?.open || []).filter((x) => x.id !== g.id)
    gaps.value = {
      ...(gaps.value || {}),
      open,
      open_count: open.length,
      filled_count: (gaps.value?.filled_count || 0) + 1,
    }
    ElMessage.success('这条缺口已补上')
  } catch (e) {
    ElMessage.error('关闭缺口失败：' + (e?.message || e))
  }
}

// ============ 自进化账本 ============
const evolution = ref(null)
const feedEnabled = ref(false)
const feedInterval = ref(60)
const feedRunning = ref(false)
/** 后端目前没把 last_run_at 落库（set_auto_feed 会把内存里的改动冲掉），
 *  本机刚触发过就先记在这儿，别让界面说「还没有」 */
const localFeedAt = ref('')

async function loadEvolution() {
  try {
    evolution.value = await Api.dnaLibraryEvolution()
  } catch (e) {
    evolution.value = null
  }
}

watch(evolution, (v) => {
  if (!v?.auto_feed) return
  feedEnabled.value = !!v.auto_feed.enabled
  feedInterval.value = v.auto_feed.interval_minutes || 60
}, { immediate: true })

/** 开关或间隔一改就落库 */
async function saveAutoFeed() {
  try {
    const r = await Api.dnaLibraryAutoFeed({
      enabled: feedEnabled.value,
      interval_minutes: feedInterval.value,
    })
    if (r?.auto_feed) {
      evolution.value = { ...(evolution.value || {}), auto_feed: r.auto_feed }
    }
  } catch (e) {
    ElMessage.error('自动喂养设置保存失败：' + (e?.message || e))
  }
}

async function runAutoFeed() {
  feedRunning.value = true
  try {
    const r = await Api.dnaLibraryAutoFeedRun()
    const n = r?.result?.genes ?? r?.result?.created ?? 0
    localFeedAt.value = new Date().toISOString()
    ElMessage.success(n ? `这一轮喂出 ${n} 条基因` : '这一轮喂完了')
    await loadEvolution()
  } catch (e) {
    ElMessage.error('自动喂养失败：' + (e?.message || e))
  } finally {
    feedRunning.value = false
  }
}

/** 成长曲线的柱高：按最大的一天归一 */
/** 成长曲线只画最近 30 天 —— 再多也看不清 */
const evoTimeline = computed(() => {
  const t = evolution.value?.timeline || []
  return t.slice(-30)
})

function evoBarH(v) {
  const t = evolution.value?.timeline || []
  const max = Math.max(1, ...t.map((d) => d.genes || 0))
  return Math.max(4, Math.round(((v || 0) / max) * 100))
}

/** 可吸收的源码候选：文件库里看起来像代码的文件 */
async function loadSourceDocs() {
  try {
    const r = await Api.listDocuments({ limit: 200 })
    const items = r.items || r.documents || []
    sourceDocs.value = items.filter(
      (d) => /\.(py|js|ts|tsx|jsx|java|go|rs|rb|php|c|cc|cpp|h|hpp|sh|bash|sql|yaml|yml|json|toml|ini|conf)$/i
        .test(d.filename || d.title || '')
    )
  } catch (e) {
    sourceDocs.value = []
  }
}

/** 体检条目：把 health 的数字翻译成人能懂的话 */
const healthItems = computed(() => {
  const h = overview.value?.health || {}
  const sm = h.samples || {}
  return [
    { key: 'cold', count: h.cold || 0, label: '冷基因',
      hint: '没人用过 —— 该复核了', samples: sm.cold,
      action: { type: 'flag', value: 'cold' } },
    { key: 'used', count: h.used || 0, label: '用过的',
      hint: '被检索命中过，说明有用', samples: null,
      action: { type: 'flag', value: 'used' } },
    { key: 'no_source', count: h.no_source || 0, label: '没出处',
      hint: '说不出从哪来 —— 不可信', samples: sm.no_source,
      action: { type: 'flag', value: 'no_source' } },
    { key: 'duplicated', count: h.duplicated || 0, label: '疑似重复',
      hint: '同一件事写了两遍', samples: sm.duplicated, action: null },
    { key: 'superseded', count: h.superseded || 0, label: '已被取代',
      hint: '旧版本，留着当历史', samples: null,
      action: { type: 'status', value: 'superseded' } },
    { key: 'destroyed', count: h.destroyed_sources || 0, label: '源码已销毁',
      hint: '只留方法，不留原文', samples: null, action: null },
  ]
})

/** 点体检条目里的样本 → 打开那条基因 */
async function openGeneById(id) {
  try {
    const g = await Api.dnaLibraryGene(id)
    detail.value = g
    geneDrawer.value = true
  } catch (e) {
    ElMessage.error('读基因失败：' + (e?.message || e))
  }
}

/** 体检筛选：点概览上的数字，直接看是哪几条 */
function setFlag(flag) {
  geneFlag.value = geneFlag.value === flag ? '' : flag
  loadGenes(0)
  nextTick(() => {
    document.querySelector('.lib-body .ptable')?.scrollIntoView({
      behavior: 'smooth', block: 'center',
    })
  })
}

function setStatus(v) {
  statusFilter.value = statusFilter.value === v ? 'active' : v
  loadGenes(0)
  nextTick(() => {
    document.querySelector('.lib-body .ptable')?.scrollIntoView({
      behavior: 'smooth', block: 'center',
    })
  })
}

/** 体检面板上的数字：接到已有的筛选动作上（不新增筛选语义） */
function applyHealthAction(item) {
  if (!item?.action) return
  if (item.action.type === 'flag') setFlag(item.action.value)
  else setStatus(item.action.value)
}

async function loadGenes(page) {
  if (typeof page === 'number') genePage.value = page
  try {
    const list = await Api.dnaLibraryGenes({
      kind: kindFilter.value, status: statusFilter.value,
      q: geneQuery.value, sort: geneSort.value, flag: geneFlag.value,
      limit: genePageSize, offset: (genePage.value - 1) * genePageSize })
    genes.value = list.items || []
    geneTotal.value = list.total || 0
  } catch (e) {
    ElMessage.error('读基因清单失败：' + (e?.message || e))
  }
}

/** 点清单里的一行 → 右侧抽屉看全文 */
function openGene(row) {
  detail.value = row
  geneDrawer.value = true
}

/**
 * 复制引用 —— 养料库里的知识要能直接拿到别处去用
 *
 * 复制出来的是一段成品文字（带出处），不是「基因 12」这种编号：
 * 贴到工单、邮件、别处的文档里，读的人才知道这句话从哪来。
 */
async function copyCite(gene) {
  if (!gene) return
  try {
    const r = await Api.dnaLibraryCite({ gene_ids: [gene.id], format: 'markdown' })
    await copyText(r.text || '')
    ElMessage.success('引用已复制，贴到哪儿都能看出处')
  } catch (e) {
    ElMessage.error('复制失败：' + (e?.message || e))
  }
}

async function copyPlain(gene) {
  if (!gene) return
  try {
    await copyText(gene.content || '')
    ElMessage.success('原文已复制')
  } catch (e) {
    ElMessage.error('复制失败：' + (e?.message || e))
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch (e) {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

function gotoDocument(sourceRef) {
  const id = String(sourceRef).replace('doc-', '')
  window.location.hash = `/library?doc=${id}`
}

function fmtTime(v) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}

/** 抽屉宽度：窄屏别占满屏 */
const detailSize = computed(() =>
  (typeof window !== 'undefined' && window.innerWidth < 760 ? '92%' : '520px'))

async function absorbAll() {
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorbAll()
    ElMessage.success(`吸收完成：${r.genes} 条基因（新建 ${r.created}）`)
    lastAbsorb.value = { genes: r.genes, titles: [] }
    await loadAll()
  } catch (e) {
    ElMessage.error('全库吸收失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function absorbTextNow() {
  if (!absorbText.value.trim()) {
    ElMessage.warning('先粘点东西')
    return
  }
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorb({ text: absorbText.value, title: absorbTitle.value })
    ElMessage.success(`吸收完成：${r.genes} 条基因`)
    lastAbsorb.value = { genes: r.genes, titles: [] }
    absorbText.value = ''
    absorbTitle.value = ''
    await loadAll()
  } catch (e) {
    ElMessage.error('吸收失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function absorbCodeNow() {
  if (!absorbCode.value.trim()) {
    ElMessage.warning('先粘点源码')
    return
  }
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorbCode({
      code: absorbCode.value,
      filename: codeFilename.value || 'snippet.py',
      destroy: destroySource.value,
    })
    ElMessage.success(`蒸馏出 ${r.genes} 条基因`)
    lastAbsorb.value = {
      genes: r.genes, summary: r.summary, destroyed: r.destroyed,
      attestation: r.attestation, titles: [],
    }
    absorbCode.value = ''
    await loadAll()
  } catch (e) {
    ElMessage.error('源码蒸馏失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function absorbSourceNow() {
  if (!sourceDocId.value) {
    ElMessage.warning('先选一份源码文件')
    return
  }
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorbSource({
      document_id: sourceDocId.value,
      destroy: true,
      destroy_file: destroySourceFile.value,
    })
    ElMessage.success(
      `蒸馏出 ${r.genes} 条基因` +
      (r.file_deleted ? '，源文件已销毁' : '') +
      (r.document_cleared ? '，库里的抽取正文已清空' : '')
    )
    lastAbsorb.value = {
      genes: r.genes, summary: r.summary, destroyed: r.destroyed,
      attestation: r.attestation, titles: [],
    }
    await loadAll()
    await loadSourceDocs()
  } catch (e) {
    ElMessage.error('源码吸收失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function toggleOffline(on) {
  try {
    const r = await Api.dnaLibraryOffline({ enabled: !!on })
    overview.value = { ...(overview.value || {}), offline: r.offline }
    offlineLocal.value = !!r.offline
    ElMessage.success(r.offline ? '已进入离线模式：语义检索与生成已关闭' : '已退出离线模式')
  } catch (e) {
    offlineLocal.value = !on
    ElMessage.error('切换失败：' + (e?.message || e))
  }
}

async function runDrill() {
  drilling.value = true
  try {
    drillResult.value = await Api.dnaLibraryDrill()
  } catch (e) {
    ElMessage.error('演练失败：' + (e?.message || e))
  } finally {
    drilling.value = false
  }
}

async function doSearch() {
  if (!query.value.trim()) return
  searching.value = true
  answer.value = null
  try {
    // 检索要跟着当前的种类筛选走 ——
    // 清单筛了「经验」，检索却给出一堆事实，两套口径会让人以为筛选没生效
    const r = await Api.dnaLibrarySearch({
      q: query.value, limit: 12,
      kind: kindFilter.value || '',
    })
    hits.value = r.items || []
    if (!hits.value.length) ElMessage.info('没有命中基因')
  } catch (e) {
    ElMessage.error('检索失败：' + (e?.message || e))
  } finally {
    searching.value = false
  }
}

async function doAnswer() {
  if (!query.value.trim()) return
  searching.value = true
  hits.value = []
  try {
    answer.value = await Api.dnaLibraryAnswer({
      q: query.value, limit: 5,
      kind: kindFilter.value || '',
    })
  } catch (e) {
    ElMessage.error('直答失败：' + (e?.message || e))
  } finally {
    searching.value = false
  }
}

async function exportBundle() {
  try {
    const r = await Api.dnaLibraryBundle()
    ElMessage.success(`已导出：${r.info?.bytes ? Math.round(r.info.bytes / 1024) + ' KB' : ''}`)
  } catch (e) {
    ElMessage.error('导出失败：' + (e?.message || e))
  }
}

onMounted(loadAll)

// 离开页面就把轮询停掉，别留下野定时器
onUnmounted(() => {
  stopJobPolling()
})
</script>

<style scoped>
.lib-page { padding-bottom: 48px; }
.lib-body { min-height: 200px; }
.lib-alert { margin-bottom: 20px; }

/* ============ 分区骨架（与「养料 DNA」页同族） ============ */
.section { margin-bottom: 32px; }
.sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.sec-no {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.6px;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-100);
  border-radius: 5px;
  padding: 1px 6px;
  line-height: 16px;
}
.sec-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.2px;
}
.sec-note { font-size: 12px; color: var(--text-tertiary); }
.sec-hint { font-size: 11px; color: var(--text-disabled); }
.sec-rule {
  flex: 1;
  min-width: 24px;
  height: 1px;
  background: linear-gradient(to right, var(--border), transparent);
}

/* 统一的「纸」：轻边框 + 轻阴影 + 12px 圆角 */
.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
  padding: 18px 20px;
  min-width: 0;
}

/* ============ 离线横幅 ============ */
.offline-band {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 22px;
  border-radius: 12px;
  background: var(--warning-bg);
  border: 1px solid color-mix(in srgb, var(--warning) 32%, transparent);
  border-left: 4px solid var(--warning);
  color: var(--text-primary);
}
.offline-band > .el-icon { color: var(--warning); font-size: 19px; }
.band-text { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.band-text b { font-size: 13.5px; font-weight: 600; }
.band-text span { font-size: 12px; color: var(--text-secondary); }
.band-enter-active, .band-leave-active { transition: opacity .2s ease; }
.band-enter-from, .band-leave-to { opacity: 0; }

/* ============ 01 凝胶电泳 ============ */
.gel-card {
  display: flex;
  align-items: stretch;
  gap: 30px;
  flex-wrap: wrap;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 14px;
  box-shadow: var(--shadow-card);
  padding: 22px 24px;
}
.gel-left { flex: 1; min-width: 300px; }
.gel-total { display: flex; align-items: baseline; gap: 8px; }
.gel-total .num {
  font-size: 46px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1;
  letter-spacing: -1.5px;
}
.gel-total .unit { font-size: 13px; color: var(--text-tertiary); }
.gel-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 9px 0 14px;
  max-width: 46ch;
}
.gel-chips { display: flex; gap: 7px; flex-wrap: wrap; }
.chip {
  font-size: 11.5px;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  padding: 3px 10px;
  font-variant-numeric: tabular-nums;
}
.chip-btn {
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s var(--ease-out), color 0.15s var(--ease-out),
              border-color 0.15s var(--ease-out);
}
.chip-btn:hover { border-color: var(--primary-200); color: var(--primary); }
.chip-btn.is-on {
  background: var(--primary-bg);
  border-color: var(--primary-200);
  color: var(--primary);
  font-weight: 600;
}
.chip.danger { color: var(--danger-text); background: var(--danger-bg); border-color: transparent; }

/* ---- 凝胶与泳道 ---- */
.gel-lanes {
  flex: 1.15;
  min-width: 380px;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 4px;
  border-radius: 12px;
  padding: 14px 10px 12px;
  /* 凝胶底：浅色主题是灰胶，深色主题自动变暗 */
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--text-primary) 7%, var(--bg-sunken)),
    var(--bg-sunken)
  );
  border: 1px solid var(--border-light);
  position: relative;
}
:global(html.dark) .gel-lanes {
  background: linear-gradient(
    180deg,
    var(--bg),
    color-mix(in srgb, var(--text-primary) 5%, var(--bg-sunken))
  );
}
/* 加样孔：泳道顶端那道暗槽 */
.lane-well {
  width: 24px;
  height: 4px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--text-primary) 24%, transparent);
  margin-bottom: 6px;
}
/* 泳道：条带一条 = 一条基因 */
.lane-track {
  width: 100%;
  max-width: 46px;
  height: 172px;
  display: flex;
  flex-direction: column-reverse;
  justify-content: flex-start;
  gap: 3px;
  padding: 4px;
  border-radius: 8px;
  overflow: hidden;
  background: color-mix(in srgb, var(--text-primary) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--text-primary) 9%, transparent);
}
.lane-band {
  height: 6px;
  border-radius: 3px;
  background: var(--k);
  box-shadow: 0 0 10px color-mix(in srgb, var(--k) 55%, transparent);
  /* 越往下越淡：模拟荧光条带随距离衰减 */
  opacity: calc(1 - var(--i) * 0.032);
}

.base-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  padding: 8px 4px 9px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.16s var(--ease-out), border-color 0.16s var(--ease-out);
}
.base-cell:hover { background: color-mix(in srgb, var(--text-primary) 5%, transparent); }
.base-cell.is-on {
  background: color-mix(in srgb, var(--k) 12%, transparent);
  border-color: color-mix(in srgb, var(--k) 40%, transparent);
}
.base-cell.fact { --k: var(--primary); }
.base-cell.method { --k: var(--accent-green); }
.base-cell.experience { --k: var(--warning); }
.base-cell.interface { --k: var(--accent-slate); }
.base-cell.policy { --k: var(--danger); }
.base-num {
  font-size: 17px;
  font-weight: 650;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.base-label { font-size: 12px; color: var(--text-secondary); }
.base-desc { font-size: 10.5px; color: var(--text-disabled); }

/* ============ 02 质检报告条 ============ */
.health-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.health-cell {
  position: relative;
  padding: 15px 18px 16px;
  border-right: 1px solid var(--border-light);
  min-width: 0;
}
.health-cell:last-child { border-right: none; }
/* 坏项：亮出来（左侧一道警示色 + 数字上色） */
.health-cell.is-bad {
  background: color-mix(in srgb, var(--warning) 7%, var(--bg-card));
}
.health-cell.is-bad::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--warning);
}
/* 好项：安静待着 */
.health-cell.is-ok { background: var(--bg-card); }
.hc-num {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
  background: none;
  border: 0;
  padding: 0;
  font-family: inherit;
  color: inherit;
  text-align: left;
}
.hc-num.is-link { cursor: pointer; }
.hc-num.is-link:hover { color: var(--primary); }
.hc-num:disabled { cursor: default; }
.health-cell.is-bad .hc-num { color: var(--warning-text); }
.health-cell.is-ok .hc-num { color: var(--text-tertiary); }
.hc-label { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-top: 3px; }
.hc-hint { font-size: 11.5px; color: var(--text-tertiary); margin-top: 2px; line-height: 1.5; }
.hc-samples { margin-top: 8px; display: flex; flex-direction: column; gap: 3px; }
.hc-sample {
  text-align: left;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11.5px;
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hc-sample:hover { color: var(--primary); text-decoration: underline; }
.hc-sample-more { color: var(--primary); }

/* ============ 03 基因清单 ============ */
.kind-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.gene-search { width: 220px; }
.status-filter { width: 128px; }
.flag-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-100);
  border-radius: 12px;
  padding: 2px 9px;
}
.flag-x { cursor: pointer; font-size: 12px; }

.gene-table :deep(.el-table__cell) { padding: 11px 0; }
.gene-table :deep(.el-table__cell .cell) { padding: 0 12px; line-height: 1.5; }
.gene-table :deep(.el-table__header th.el-table__cell) {
  background: var(--bg-subtle);
  border-bottom-color: var(--border);
  font-weight: 600;
  color: var(--text-secondary);
}
/* 行左侧的种类色条 */
.gene-table :deep(tr.kind-fact) { --k2: var(--primary); }
.gene-table :deep(tr.kind-method) { --k2: var(--accent-green); }
.gene-table :deep(tr.kind-experience) { --k2: var(--warning); }
.gene-table :deep(tr.kind-interface) { --k2: var(--accent-slate); }
.gene-table :deep(tr.kind-policy) { --k2: var(--danger); }
.gene-table :deep(.el-table__body tr td:first-child) { position: relative; }
.gene-table :deep(.el-table__body tr td:first-child::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--k2, transparent);
  opacity: 0.75;
  transition: top 0.15s var(--ease-out), bottom 0.15s var(--ease-out),
              width 0.15s var(--ease-out);
}
/* hover：行底色抬一层，色条长一点，标题变主色 —— 轻轻「浮起」 */
.gene-table :deep(.el-table__body tr:hover td) { background: var(--bg-subtle); }
.gene-table :deep(.el-table__body tr:hover td:first-child::before) {
  top: 5px;
  bottom: 5px;
  width: 4px;
  opacity: 1;
}
.gene-table :deep(.el-table__body tr:hover .gene-title) { color: var(--primary); }
.gene-table :deep(.el-table__body tr.is-superseded) { opacity: 0.66; }
.gene-table :deep(.el-table__body tr.is-superseded .gene-title) {
  text-decoration: line-through;
  text-decoration-color: var(--border-strong);
}
.gene-table :deep(td.num-cell) {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.gene-table :deep(td.src-cell) { color: var(--text-tertiary); }

.kind-cell { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; }
.kind-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent-slate);
  flex-shrink: 0;
}
.kind-dot.fact { background: var(--primary); }
.kind-dot.method { background: var(--accent-green); }
.kind-dot.experience { background: var(--warning); }
.kind-dot.interface { background: var(--accent-slate); }
.kind-dot.policy { background: var(--danger); }

.gene-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.5;
  transition: color 0.15s var(--ease-out);
}
.gene-sum {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.gene-live {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--success-text);
}
.gene-live::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}
.gene-superseded {
  font-size: 11px;
  color: var(--text-tertiary);
  border: 1px dashed var(--border-strong);
  border-radius: 5px;
  padding: 1px 7px;
}
.gene-destroyed {
  font-size: 11px;
  color: var(--danger-text);
  background: var(--danger-bg);
  border-radius: 5px;
  padding: 1px 7px;
}

.gene-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.pager-note { font-size: 12px; color: var(--text-tertiary); }

/* ============ 04 检索与直答 ============ */
.ask-row { display: flex; gap: 10px; flex-wrap: wrap; }
.ask-row .el-input { flex: 1; min-width: 220px; }

.answer-box {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--bg-subtle);
  border-left: 3px solid var(--primary);
}
.answer-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.answer-tag {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: 5px;
  padding: 1px 7px;
}
.answer-note { font-size: 11.5px; color: var(--text-tertiary); }
.answer-text {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}
.answer-genes { margin-top: 11px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.ag-label { font-size: 11px; color: var(--text-tertiary); }
.ag-chip {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
}
.ag-chip.fact { border-color: var(--primary-100); }
.ag-chip.method { border-color: color-mix(in srgb, var(--accent-green) 35%, transparent); }
.ag-chip.experience { border-color: color-mix(in srgb, var(--warning) 35%, transparent); }
.ag-chip.interface { border-color: var(--border-strong); }
.ag-chip.policy { border-color: color-mix(in srgb, var(--danger) 30%, transparent); }

.gene-list { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.gene-row {
  display: flex;
  gap: 12px;
  padding: 11px 13px;
  border-radius: 10px;
  background: var(--bg-subtle);
  border-left: 3px solid var(--accent-slate);
}
.gene-row.fact { border-left-color: var(--primary); }
.gene-row.method { border-left-color: var(--accent-green); }
.gene-row.experience { border-left-color: var(--warning); }
.gene-row.interface { border-left-color: var(--accent-slate); }
.gene-row.policy { border-left-color: var(--danger); }
.gene-kind {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 5px;
  padding: 1px 7px;
  height: fit-content;
  flex-shrink: 0;
}
.gene-kind.fact { color: var(--primary); background: var(--primary-bg); border-color: var(--primary-100); }
.gene-kind.method { color: var(--success-text); background: var(--success-bg); border-color: transparent; }
.gene-kind.experience { color: var(--warning-text); background: var(--warning-bg); border-color: transparent; }
.gene-kind.interface { color: var(--accent-slate); background: var(--bg-subtle); border-color: transparent; }
.gene-kind.policy { color: var(--danger-text); background: var(--danger-bg); border-color: transparent; }
.gene-main { min-width: 0; }
.gene-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-top: 5px;
}

/* ============ 05 工作台（吸收 / 断网） ============ */
.work-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 20px;
}
.work-panel {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  padding: 18px 20px 20px;
  min-width: 0;
}
.card-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.card-head h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.card-note { font-size: 11.5px; color: var(--text-tertiary); }

.absorb-tabs :deep(.el-tabs__header) { margin-bottom: 12px; }
.absorb-tabs :deep(.el-tabs__nav-wrap::after) { background: var(--border-light); }
.absorb-tabs :deep(.el-tabs__item) { font-size: 13px; }
.absorb-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
.src-pick { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.src-hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
  line-height: 1.6;
  margin-top: 10px;
}
.code-alert { margin-bottom: 10px; }

.absorb-result {
  margin-top: 14px;
  padding: 11px 13px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
}
.ar-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--success-text);
  flex-wrap: wrap;
}
.ar-destroy {
  font-size: 11px;
  font-weight: 600;
  color: var(--danger-text);
  background: var(--danger-bg);
  border-radius: 5px;
  padding: 1px 7px;
}
.ar-line { font-size: 12px; color: var(--text-secondary); margin-top: 5px; line-height: 1.6; }
.ar-line.mono { font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); }
.ar-list { margin: 7px 0 0; padding-left: 18px; font-size: 12px; color: var(--text-secondary); }

.offline-switch {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 13px;
  border-radius: 9px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--text-primary);
}
.cap-list { list-style: none; margin: 0; padding: 0; }
.cap-list li {
  display: flex;
  align-items: baseline;
  gap: 9px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-light);
  font-size: 12.5px;
}
.cap-list li:last-child { border-bottom: none; }
.cap-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text-disabled); flex-shrink: 0;
}
.cap-dot.ok { background: var(--success); }
.cap-dot.off { background: var(--border-strong); }
.cap-key { color: var(--text-primary); font-weight: 500; flex-shrink: 0; }
.cap-detail { color: var(--text-tertiary); font-size: 11.5px; line-height: 1.55; }

.drill {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
}
.drill-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}
.drill-hint { font-size: 11.5px; color: var(--text-tertiary); margin-top: 7px; line-height: 1.6; }
.drill-score { font-size: 13px; font-weight: 700; margin-top: 8px; }
.drill-score.ok { color: var(--success-text); }
.drill-score.bad { color: var(--danger-text); }
.drill-list { list-style: none; margin: 8px 0 0; padding: 0; }
.drill-list li {
  display: flex; align-items: baseline; gap: 9px;
  font-size: 12px; color: var(--text-secondary); padding: 3px 0;
}
.drill-q { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drill-ms { font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); }
.drill-note { font-size: 11.5px; color: var(--text-tertiary); margin-top: 8px; line-height: 1.6; }

/* ============ 基因抽屉 ============ */
.gene-detail { display: flex; flex-direction: column; gap: 12px; }
.gd-meta { display: flex; gap: 7px; flex-wrap: wrap; }
.gd-content {
  margin: 0;
  padding: 13px 15px;
  border-radius: 10px;
  background: var(--bg-subtle);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
  max-height: 52vh;
  overflow: auto;
}
.gd-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.gd-foot { display: flex; gap: 16px; flex-wrap: wrap; }
.gd-time { font-size: 11.5px; color: var(--text-tertiary); font-family: var(--font-mono); }

/* ============ 源码树（整系统） ============ */
.tree-pick { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pick-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--text-primary);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 9px;
  padding: 7px 13px;
  cursor: pointer;
  transition: border-color 0.15s var(--ease-out), color 0.15s var(--ease-out);
}
.pick-btn:hover { border-color: var(--primary-200); color: var(--primary); }
.pick-hint { font-size: 11.5px; color: var(--text-tertiary); line-height: 1.5; }

.tree-pending {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border-light);
}
.tp-count { display: flex; align-items: baseline; gap: 6px; }
.tp-num {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
  line-height: 1;
}
.tp-unit { font-size: 12px; color: var(--text-tertiary); }
.tp-size {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
  padding-left: 10px;
  margin-left: 4px;
  border-left: 1px solid var(--border-light);
}
.tp-zip {
  font-size: 10.5px;
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: 4px;
  padding: 1px 6px;
}
.tp-title { flex: 1; min-width: 180px; }

.tree-progress { margin-top: 14px; }
.tprog-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 7px; }
.tprog-stage {
  font-size: 11px;
  font-weight: 700;
  border-radius: 5px;
  padding: 2px 8px;
}
.tprog-stage.upload { color: var(--primary); background: var(--primary-bg); }
.tprog-stage.parse { color: var(--warning-text); background: var(--warning-bg); }
.tprog-stage.done { color: var(--success-text); background: var(--success-bg); }
.tprog-hint { font-size: 11.5px; color: var(--text-secondary); line-height: 1.5; }

.tree-note {
  margin-top: 14px;
  padding: 10px 13px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-left: 3px solid var(--accent-slate);
}
.tn-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}
.tn-head > .el-icon:first-child { color: var(--accent-slate); }
.tn-lead { flex: 1; }
.tn-lead b { color: var(--text-primary); }
.tn-arrow {
  font-size: 12px;
  color: var(--text-tertiary);
  transition: transform 0.18s var(--ease-out);
}
.tree-note.is-open .tn-arrow { transform: rotate(90deg); }
.tn-body {
  margin: 9px 0 2px;
  padding-left: 18px;
  font-size: 11.5px;
  color: var(--text-tertiary);
  line-height: 1.75;
}
.tn-body b { color: var(--text-secondary); }

/* ============ 学习任务 ============ */
.jobs-block {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--border-light);
}
.jobs-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.jobs-head h3 { font-size: 15px; font-weight: 600; color: var(--text-primary); margin: 0; }
.jobs-note { font-size: 11.5px; color: var(--text-tertiary); }
.jobs-empty {
  padding: 22px 4px;
  font-size: 12.5px;
  color: var(--text-tertiary);
  text-align: center;
}
.jobs-list { list-style: none; margin: 0; padding: 0; }
.job-row {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-light);
}
.job-row:last-child { border-bottom: none; }
.job-top { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 8px; }
.job-status {
  font-size: 11px;
  font-weight: 600;
  border-radius: 5px;
  padding: 1px 8px;
  flex-shrink: 0;
}
.job-status.pending { color: var(--text-secondary); background: var(--bg-subtle); }
.job-status.running { color: var(--primary); background: var(--primary-bg); }
.job-status.done { color: var(--success-text); background: var(--success-bg); }
.job-status.failed { color: var(--danger-text); background: var(--danger-bg); }
.job-status.canceled { color: var(--text-tertiary); background: var(--bg-subtle); }
.job-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.job-ops { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.job-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-top: 7px;
}
.job-meta b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.job-current { color: var(--primary); }
.job-err { color: var(--danger-text); }
.job-detail { margin-top: 9px; padding-top: 8px; border-top: 1px dashed var(--border-light); }
.jd-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-tertiary);
  padding: 3px 0;
}
.jd-file {
  font-family: var(--font-mono);
  color: var(--text-secondary);
  min-width: 180px;
  word-break: break-all;
}
.jd-lang { color: var(--accent-slate); min-width: 56px; }
.jd-lines, .jd-genes { font-variant-numeric: tabular-nums; min-width: 56px; }
.jd-destroy { min-width: 62px; }
.jd-destroy.on { color: var(--success-text); }
.jd-note { color: var(--text-disabled); }

/* ============ 06 自进化账本 ============ */
.evo-gens {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0;
}
.gen-card {
  padding: 4px 20px 4px 0;
  margin-right: 20px;
  border-right: 1px solid var(--border-light);
}
.gen-card:last-child { border-right: none; margin-right: 0; padding-right: 0; }
.gen-stage {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
  letter-spacing: 1px;
}
.gen-value {
  font-size: 38px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
  line-height: 1.15;
  letter-spacing: -1.5px;
  margin-top: 4px;
}
.gen-label { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-top: 2px; }
.gen-note { font-size: 11.5px; color: var(--text-tertiary); margin-top: 4px; line-height: 1.6; }

.evo-totals {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border-light);
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.evo-totals b {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  margin-left: 3px;
}

.evo-chart-wrap { margin-top: 18px; }
.evo-chart-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 10px;
}
.evo-latest { font-size: 11px; font-weight: 400; color: var(--text-tertiary); }
.evo-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 132px;
  padding: 0 2px 20px;
  border-bottom: 1px solid var(--border-light);
  position: relative;
}
.evo-col {
  flex: 1;
  min-width: 8px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  position: relative;
}
.evo-bar {
  width: 100%;
  max-width: 34px;
  border-radius: 4px 4px 0 0;
  background: var(--primary);
  opacity: 0.55;
  min-height: 3px;
  transition: opacity 0.15s var(--ease-out);
}
.evo-col:hover .evo-bar { opacity: 1; }
.evo-col.is-latest .evo-bar {
  background: var(--accent-green);
  opacity: 1;
  box-shadow: 0 0 10px color-mix(in srgb, var(--accent-green) 45%, transparent);
}
.evo-day {
  position: absolute;
  bottom: -18px;
  font-size: 10px;
  color: var(--text-disabled);
  font-family: var(--font-mono);
  white-space: nowrap;
}
.evo-col.is-latest .evo-day { color: var(--accent-green); }
.evo-empty {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 40px;
  text-align: center;
  font-size: 12px;
  color: var(--text-disabled);
}

.evo-feed {
  margin-top: 26px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}
.feed-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 11px; }
.feed-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.feed-note { font-size: 11.5px; color: var(--text-tertiary); }
.feed-row { display: flex; align-items: center; gap: 11px; flex-wrap: wrap; }
.feed-label { font-size: 12.5px; color: var(--text-secondary); }
.feed-unit { font-size: 11.5px; color: var(--text-tertiary); }
.feed-last { font-size: 11.5px; color: var(--text-tertiary); margin-top: 10px; }
.feed-result { color: var(--text-secondary); }

/* ============ 知识缺口 ============ */
.gen-foot {
  font-size: 11.5px;
  color: var(--warning-text);
  margin-top: 5px;
}
.evo-gaps {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}
.gaps-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.gaps-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.gaps-note { font-size: 11.5px; color: var(--text-tertiary); }
.gaps-count {
  font-size: 11.5px;
  color: var(--warning-text);
  background: var(--warning-bg);
  border-radius: 5px;
  padding: 1px 8px;
}
.gaps-empty {
  padding: 18px 4px;
  font-size: 12.5px;
  color: var(--text-tertiary);
  text-align: center;
}
.gaps-list { list-style: none; margin: 0; padding: 0; }
.gap-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border-light);
}
.gap-row:last-child { border-bottom: none; }
.gap-q {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
}
.gap-asked {
  font-size: 11px;
  color: var(--warning-text);
  background: var(--warning-bg);
  border-radius: 5px;
  padding: 1px 7px;
  flex-shrink: 0;
}
.gap-last {
  font-size: 11px;
  color: var(--text-disabled);
  font-family: var(--font-mono);
  flex-shrink: 0;
}

/* ============ 窄屏 ============ */
@media (max-width: 900px) {
  .gel-card { padding: 18px; gap: 20px; }
  .gel-lanes { min-width: 100%; }
}

@media (max-width: 480px) {
  .section { margin-bottom: 26px; }
  .gel-total .num { font-size: 38px; }
  .gel-lanes { grid-template-columns: repeat(5, 1fr); gap: 2px; padding: 10px 4px 8px; }
  .lane-track { height: 128px; max-width: 44px; }
  .lane-band { height: 4px; }
  .base-num { font-size: 15px; }
  .base-label { font-size: 11px; }
  .base-desc { display: none; }
  .health-strip { grid-template-columns: repeat(2, 1fr); }
  .health-cell { border-right: none; border-bottom: 1px solid var(--border-light); padding: 12px 14px; }
  .hc-num { font-size: 20px; }
  .panel { padding: 14px; }
  .kind-filter { gap: 8px; }
  .gene-search { width: 100%; }
  .status-filter { width: 118px; }
  .work-grid { grid-template-columns: 1fr; }
  .ask-row .el-input { min-width: 100%; }
  .gen-card { padding-right: 14px; margin-right: 14px; }
  .gen-value { font-size: 30px; }
  .evo-chart { height: 108px; }
  .feed-row { gap: 9px; }
  .jd-file { min-width: 120px; }
}
</style>
