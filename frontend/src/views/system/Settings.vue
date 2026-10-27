<template>
  <div class="page">
    <PageTitle
      title="系统设置"
      subtitle="这里的改动立即生效，不需要重启容器 —— 备份目录、保留份数、初始管理员口令、升级仓库"
      icon-key="Setting"
    >
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </PageTitle>

    <el-alert v-if="loadError" type="error" show-icon :closable="false" class="load-err">
      <template #title>{{ loadError }}</template>
    </el-alert>

    <!-- 配置从哪来：把优先级摆明，避免「改了没生效」的困惑 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><InfoFilled /></el-icon>配置从哪来
        </span>
      </div>
      <div class="legend">
        <div v-for="p in precedence" :key="p.source" class="legend-row">
          <el-tag size="small" :type="srcTagType(p.source)" effect="light">{{ p.label }}</el-tag>
          <span class="legend-note">{{ p.note }}</span>
        </div>
        <div class="legend-row">
          <el-tag size="small" type="info" effect="plain">优先级</el-tag>
          <span class="legend-note">
            本页设置 &gt; 环境变量 &gt; 代码默认值。同一项被多处设置时，左边的赢。
          </span>
        </div>
      </div>
      <div class="note">
        <el-icon><FolderOpened /></el-icon>
        <span>
          配置文件 <code class="mono">{{ file || '—' }}</code> —— 与 <code class="mono">kb.db</code> 分开放。
          这么设计是有原因的：<b>备份目录不能存在数据库里</b>，否则灾难恢复时会出现
          「要先知道备份在哪，而这条信息正好在你要恢复的库里」的死循环。
        </span>
      </div>
    </div>

    <!-- 按分组渲染 -->
    <div v-for="g in groups" :key="g.name" class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico">
            <component :is="groupIcon(g.name)" />
          </el-icon>{{ g.name }}
        </span>
      </div>

      <div v-for="it in g.items" :key="it.key" class="set-row" :class="{ dirty: isDirty(it) }">
        <div class="set-head">
          <div class="set-name">
            {{ it.label }}
            <el-tag size="small" :type="srcTagType(it.source)" effect="light">
              来源：{{ srcLabel(it.source) }}
            </el-tag>
            <el-tag v-if="it.source === 'env' && it.env_value" size="small" type="warning" effect="plain">
              环境变量会覆盖默认值
            </el-tag>
            <template v-if="it.kind === 'secret'">
              <el-tag v-if="it.is_set" size="small" type="success" effect="plain">已自定义</el-tag>
              <el-tag v-else-if="it.is_weak" size="small" type="danger" effect="plain">仍是默认弱口令</el-tag>
            </template>
          </div>
          <div class="set-key mono">{{ it.key }}</div>
        </div>

        <div class="set-help">{{ it.help }}</div>

        <div class="set-body">
          <!-- 整数 -->
          <el-input-number
            v-if="it.kind === 'int'"
            v-model="draft[it.key]"
            :min="it.min" :max="it.max"
            controls-position="right"
            style="width: 180px"
          />

          <!-- 路径：候选下拉 + 可手填 -->
          <template v-else-if="it.kind === 'path'">
            <div class="path-row">
              <el-select
                v-model="draft[it.key]"
                filterable allow-create default-first-option
                placeholder="选择一个候选目录，或直接输入容器内绝对路径"
                style="flex: 1; min-width: 280px"
              >
                <el-option
                  v-for="c in candidates"
                  :key="c.path"
                  :value="c.path"
                  :disabled="!!c.blocked || !c.ok"
                  :label="c.path"
                >
                  <span class="opt-path mono">{{ c.path }}</span>
                  <span class="opt-tags">
                    <el-tag v-if="c.is_current" size="small" type="info" effect="plain">当前</el-tag>
                    <el-tag v-if="c.recommended" size="small" type="success" effect="plain">推荐</el-tag>
                    <el-tag v-else-if="c.blocked" size="small" type="danger" effect="plain">不可用</el-tag>
                    <el-tag v-else-if="!c.ok" size="small" type="info" effect="plain">不存在</el-tag>
                    <el-tag v-else-if="c.same_device_as_data" size="small" type="warning" effect="plain">与数据同盘</el-tag>
                  </span>
                </el-option>
              </el-select>
              <el-button :loading="probing" @click="doProbe">
                <el-icon><Aim /></el-icon>测试
              </el-button>
            </div>

            <div v-if="probeResult" class="probe" :class="probeResult.ok ? 'ok' : 'bad'">
              <el-icon><component :is="probeResult.ok ? 'CircleCheck' : 'WarningFilled'" /></el-icon>
              <span v-if="probeResult.ok">
                可用 —— 位于挂载点 <code class="mono">{{ probeResult.mount }}</code>，
                剩余 {{ fmtBytes(probeResult.free_bytes) }}；
                {{ probeResult.separate_declared ? '已声明为独立备份盘' :
                   probeResult.same_device_as_data ? '与数据目录同盘（只防误删）' : '与数据目录不同盘' }}
              </span>
              <span v-else>{{ probeResult.error }}</span>
            </div>

            <!-- 候选目录表：让「有没有别的盘可用」一眼可见 -->
            <div class="cand-box">
              <div class="cand-title">
                <span>容器内可用作备份的目录（{{ candidates.length }}）</span>
                <span v-if="!hasAlternate" class="cand-warn">
                  <el-icon><WarningFilled /></el-icon>
                  没有与数据盘分离的盘 —— 见下方挂载指引
                </span>
              </div>
              <el-table :data="candidates" size="small" class="data-table"
                        :row-class-name="candRowClass"
                        empty-text="没有探测到可用目录">
                <el-table-column label="路径" min-width="200">
                  <template #default="{ row }">
                    <span class="mono">{{ row.path }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="190">
                  <template #default="{ row }">
                    <el-tag v-if="row.is_current" size="small" type="info" effect="plain">当前生效</el-tag>
                    <el-tag v-else-if="row.recommended" size="small" type="success" effect="plain">推荐</el-tag>
                    <el-tag v-else-if="row.blocked" size="small" type="danger" effect="plain">禁止</el-tag>
                    <el-tag v-else-if="!row.ok" size="small" type="info" effect="plain">不可用</el-tag>
                    <el-tag v-else size="small" type="warning" effect="plain">可用</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="260">
                  <template #default="{ row }">
                    <span v-if="row.blocked" class="bad-text">{{ row.blocked }}</span>
                    <span v-else-if="!row.ok" class="bad-text">{{ row.error }}</span>
                    <span v-else class="dim">
                      {{ row.note }}
                      <template v-if="row.same_device_as_data"> · 与数据同盘</template>
                      <template v-else> · 独立盘{{ row.separate_declared ? '（按部署声明）' : '' }}</template>
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="剩余" width="100">
                  <template #default="{ row }">{{ row.free_bytes ? fmtBytes(row.free_bytes) : '—' }}</template>
                </el-table-column>
                <el-table-column label="" width="70">
                  <template #default="{ row }">
                    <el-button v-if="row.ok && !row.blocked && !row.is_current" link type="primary"
                               @click="draft[it.key] = row.path">选用</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 没有独立盘时给出可复制的挂载指引：这是 Docker 层的边界，
                 应用层绕不过去，所以如实告诉用户下一步在宿主机做什么 -->
            <div v-if="!hasAlternate" class="note warn">
              <el-icon><WarningFilled /></el-icon>
              <div class="guide">
                <p>
                  当前所有候选都与数据目录在<b>同一块盘</b>上 —— 这样的备份只能防误删，
                  防不了磁盘故障。要真正分盘，需要在 <code class="mono">docker-compose.yml</code>
                  里把宿主机上另一块盘挂进容器：
                </p>
                <div v-for="(s, i) in guides" :key="i" class="guide-step">
                  <div class="guide-title">{{ i + 1 }}. {{ s.title }}</div>
                  <pre class="guide-code">{{ s.snippet }}</pre>
                </div>
              </div>
            </div>
          </template>

          <!-- 口令 -->
          <div v-else-if="it.kind === 'secret'" class="secret-row">
            <el-input
              v-model="draft[it.key]"
              type="password" show-password
              :placeholder="it.is_set ? '已自定义过；留空表示不修改' : '留空表示沿用环境变量/默认值'"
              style="max-width: 360px"
            />
            <span class="dim">至少 {{ it.min_len }} 位</span>
          </div>

          <!-- 升级仓库 / 出站代理：带占位提示 + 行内格式校验。
               这类值有明确格式，等用户点「保存」再由后端报错太晚了 ——
               当场提示一次，省掉一轮来回。 -->
          <div v-else-if="it.kind === 'repo' || it.kind === 'proxy'" class="text-row">
            <el-input
              v-model="draft[it.key]"
              :placeholder="it.placeholder || ''"
              style="max-width: 420px"
              @blur="markTouched(it.key)"
            />
            <span v-if="fieldError(it)" class="field-err">
              <el-icon><WarningFilled /></el-icon>{{ fieldError(it) }}
            </span>
            <span v-else class="dim">{{ kindHint(it) }}</span>
          </div>

          <el-input v-else v-model="draft[it.key]" style="max-width: 360px" />
        </div>

        <div class="set-foot">
          <span v-if="isDirty(it)" class="dirty-tip">
            <el-icon><EditPen /></el-icon>已修改，尚未保存
          </span>
          <span v-else-if="it.source === 'file'" class="dim">
            与 <code class="mono">{{ file }}</code> 中的值一致
          </span>
          <span v-else class="dim">沿用{{ srcLabel(it.source) }}，未做本页设置</span>
          <el-button v-if="it.source === 'file'" link type="danger"
                     @click="doReset(it)">恢复默认</el-button>
          <el-button v-else-if="isDirty(it)" link @click="revert(it)">撤销改动</el-button>
        </div>
      </div>
    </div>

    <!-- 底部操作条 -->
    <div class="save-bar">
      <div class="save-info">
        <template v-if="dirtyKeys.length">
          <el-icon><WarningFilled /></el-icon>
          待保存 {{ dirtyKeys.length }} 项：<span class="mono">{{ dirtyKeys.join('、') }}</span>
        </template>
        <template v-else>没有未保存的改动</template>
      </div>
      <div>
        <el-button :disabled="!dirtyKeys.length || saving" @click="revertAll">全部撤销</el-button>
        <el-button type="primary" :disabled="!dirtyKeys.length" :loading="saving" @click="save">
          <el-icon><Select /></el-icon>保存修改
        </el-button>
      </div>
    </div>

    <!-- 系统更新：依托 GitHub Releases 检查新版本，升级动作在宿主机执行 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Refresh /></el-icon>系统更新
        </span>
        <div class="card-actions">
          <el-button size="small" :loading="updateLoading" @click="checkUpdate(true)">
            {{ updateLoading ? '检查中…' : '检查更新' }}
          </el-button>
          <!-- 一键升级：可行性判定在后端做，这里只负责把结果讲清楚 -->
          <el-button size="small" type="primary" plain @click="openUpgrade">
            <el-icon><Upload /></el-icon>一键升级
          </el-button>
        </div>
      </div>

      <!-- 先说清「在查哪个仓库、这个值来自哪一层」：
           否则出了错也不知道该去核对哪里，配置了却没生效更是无从查起 -->
      <div class="about-rows">
        <div class="about-row">
          <span class="about-label">升级仓库</span>
          <span class="about-value">
            <span class="mono">{{ effectiveRepo || '未配置' }}</span>
            <el-tag size="small" :type="srcTagType(repoSource)" effect="light" class="upd-tag">
              来源：{{ srcLabel(repoSource) }}
            </el-tag>
          </span>
        </div>
        <div class="about-row">
          <span class="about-label">出站代理</span>
          <span class="about-value dim">
            {{ proxyItem?.value ? '已配置' : '未配置（直连）' }}
          </span>
        </div>
        <div class="about-row">
          <span class="about-label">当前版本</span>
          <span class="about-value mono">v{{ updateInfo?.current || auth.sysVersion || '—' }}</span>
        </div>
      </div>

      <!-- 未配置 / 出错：说人话，给出可操作的下一步。
           按后端返回的 status 分类，而不是去猜 error 文案。 -->
      <el-alert
        v-if="updateAlert"
        :title="updateAlert.title"
        :type="updateAlert.type"
        :closable="false" show-icon class="update-alert"
      >
        <div v-if="updateAlert.hint" class="update-hint">{{ updateAlert.hint }}</div>
      </el-alert>

      <template v-if="updateInfo && updateInfo.ok">
        <div class="about-rows">
          <div class="about-row">
            <span class="about-label">最新版本</span>
            <span class="about-value mono">
              {{ updateInfo.latest || '—' }}
              <el-tag v-if="updateInfo.has_update" type="danger" size="small" effect="dark" class="upd-tag">
                有新版本
              </el-tag>
              <el-tag v-else type="success" size="small" class="upd-tag">
                已是最新
              </el-tag>
            </span>
          </div>
          <div v-if="updateInfo.published_at" class="about-row">
            <span class="about-label">发布时间</span>
            <span class="about-value dim">{{ updateInfo.published_at.slice(0, 10) }}</span>
          </div>
        </div>

        <!-- Release Notes -->
        <div v-if="updateInfo.notes" class="update-notes">
          <div class="update-notes-title">更新内容</div>
          <MarkdownText :content="updateInfo.notes" class="update-notes-body" />
        </div>

        <!-- 升级指引：接口只负责检查，动作在宿主机 -->
        <div v-if="updateInfo.has_update" class="update-howto">
          <div class="update-howto-title">
            升级方法：在宿主机项目目录执行
            <el-button text size="small" @click="copyUpgradeCmd">
              <el-icon><CopyDocument /></el-icon>复制命令
            </el-button>
          </div>
          <code class="upd-cmd">{{ upgradeCmd }}</code>
          <div class="dim update-howto-tip">
            {{ upgradeTip }}
            <a v-if="updateInfo.html_url" :href="updateInfo.html_url" target="_blank" class="upd-link">
              在 GitHub 查看此版本 →
            </a>
          </div>
        </div>
      </template>

      <div v-else-if="!updateInfo" class="about-rows">
        <div class="about-row">
          <span class="about-label">版本说明</span>
          <span class="about-value dim">点「检查更新」对比 GitHub 上的最新 Release</span>
        </div>
      </div>
    </div>

    <!-- 一键升级弹窗：把「检查到新版」变成「真的升上去」。
         可行性判定全在后端做（有没有 git / docker / build 段），
         这里只负责把结果讲清楚，并把第 4 步之后的「服务重启」扛过去。 -->
    <el-dialog
      v-model="upgrade.visible"
      title="一键升级"
      width="min(920px, 94vw)"
      align-center
      :close-on-click-modal="false"
      append-to-body
      class="upgrade-dialog"
    >
      <div v-loading="upgrade.loading" class="upgrade-body">
        <!-- 版本对照：一句话说清「从哪到哪」 -->
        <div class="upgrade-versions">
          <div class="upgrade-ver">
            <div class="upgrade-ver-label">当前版本</div>
            <div class="upgrade-ver-value mono">
              {{ upgrade.plan?.current_display || updateInfo?.current || '—' }}
            </div>
          </div>
          <el-icon class="upgrade-arrow"><Right /></el-icon>
          <div class="upgrade-ver">
            <div class="upgrade-ver-label">目标版本</div>
            <div class="upgrade-ver-value mono">{{ upgrade.plan?.target || '—' }}</div>
          </div>
          <el-tag v-if="upgrade.plan?.mode" size="small" effect="plain" class="upgrade-mode">
            {{ upgrade.plan.mode === DEPLOY_MODE.OFFLINE ? '离线包部署' : '源码部署' }}
          </el-tag>
        </div>

        <el-alert v-if="upgrade.error" :title="upgrade.error" type="error" show-icon :closable="false" />

        <!-- 判定结果：能升就直说，不能升就把缺什么、怎么补一条条摆出来 -->
        <template v-if="upgrade.plan && !upgradeBusy">
          <el-alert
            v-if="upgrade.plan.feasible"
            :title="`可以自动升级：后端会在容器里完成 ${planSummary || '升级'}`"
            type="success" show-icon :closable="false"
          />
          <div v-else class="upgrade-blockers">
            <div class="upgrade-blockers-title">当前环境不能自动升级</div>
            <div v-for="b in upgrade.plan.blockers || []" :key="b.code" class="upgrade-blocker">
              <div class="upgrade-blocker-head">
                <el-icon><WarningFilled /></el-icon>{{ b.title }}
              </div>
              <div class="upgrade-blocker-detail">{{ b.detail }}</div>
              <div class="upgrade-blocker-fix">怎么办：{{ b.fix }}</div>
            </div>
          </div>

          <!-- 开启引导：这套部署支持自动升级，只是前置条件没齐。
               与其让人照着上面的文字自己改 YAML（多半会放弃），
               不如给一条能在服务器上直接跑的命令。

               注意：这里不按 autoSupported 过滤。「连部署形态都判不出来」
               （比如容器里没挂编排文件）恰恰是最需要这条命令的情况 ——
               开启脚本自己会去找安装目录。 -->
          <div v-if="!upgrade.plan.feasible && enableCommands.length" class="upgrade-enable">
            <div class="upgrade-enable-title">
              <el-icon><MagicStick /></el-icon>
              开启自动升级：在<b>服务器</b>上执行下面这条命令
              <el-button text size="small" @click="copyEnable">
                <el-icon><CopyDocument /></el-icon>复制命令
              </el-button>
            </div>
            <pre class="upgrade-enable-cmd mono">{{ enableCommands.join('\n') }}</pre>
            <div class="upgrade-enable-tip">
              它会替你把后端容器武装起来：装上 docker 命令、挂上 docker socket 与安装目录。
              装完回到这里点「开始升级」就能一键完成。
              <b>注意：挂 docker socket 等于把宿主机的 root 权限交给容器</b>，
              只在自己的独占服务器上这么做。
            </div>
          </div>

          <!-- Release 资产：离线升级要下载镜像包，先让人知道多大 -->
          <div v-if="releaseAssets.length" class="upgrade-assets">
            <div class="upgrade-assets-title">目标版本的可下载内容</div>
            <div v-for="a in releaseAssets" :key="a.name" class="upgrade-asset">
              <el-icon><Paperclip /></el-icon>
              <span class="upgrade-asset-name mono">{{ a.name }}</span>
              <span class="upgrade-asset-size">{{ assetSizeText(a.size) }}</span>
            </div>
          </div>

          <!-- 脏文件：升级会 checkout 覆盖工作区，这些改动会消失 -->
          <div v-if="(upgrade.plan.dirty_files || []).length" class="upgrade-dirty">
            <div class="upgrade-dirty-title">未提交的改动（升级会覆盖它们）</div>
            <code v-for="f in upgrade.plan.dirty_files" :key="f" class="upgrade-dirty-file mono">{{ f }}</code>
          </div>

          <div v-if="(upgrade.plan.warnings || []).length" class="upgrade-warnings">
            <div v-for="w in upgrade.plan.warnings" :key="w.code" class="upgrade-warning">
              <el-icon><InfoFilled /></el-icon>{{ w.title }} —— {{ w.detail }}
            </div>
          </div>
        </template>

        <!-- 发布内容 -->
        <div v-if="updateInfo?.notes && !upgradeBusy" class="upgrade-notes">
          <div class="upgrade-notes-title">更新内容</div>
          <MarkdownText :content="updateInfo.notes" class="upgrade-notes-body" />
        </div>

        <!-- 手动命令：不能自动升时，这是唯一能走通的路 -->
        <div v-if="!upgradeBusy && manualCommands.length" class="upgrade-manual">
          <div class="upgrade-manual-title">
            手动升级：在<b>宿主机</b>的项目目录里执行
            <el-button text size="small" @click="copyManual">
              <el-icon><CopyDocument /></el-icon>复制命令
            </el-button>
          </div>
          <pre class="upgrade-manual-cmd mono">{{ manualCommands.join('\n') }}</pre>
          <div class="upgrade-manual-tip">{{ upgradeTip }}</div>
        </div>

        <!-- 执行中：当前阶段 + 实时日志 -->
        <template v-if="upgradeBusy">
          <div class="upgrade-phase">
            <el-icon v-if="upgrade.phase === 'restarting'" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><Loading /></el-icon>
            <span v-if="upgrade.phase === 'restarting'">
              正在重启服务，请稍候……（最多等待 90 秒，还剩 {{ upgrade.waitLeft }} 秒）
            </span>
            <span v-else>正在执行：{{ upgrade.job?.stage_title || '准备中' }}</span>
          </div>

          <div class="upgrade-steps">
            <div
              v-for="s in jobSteps" :key="s.key"
              class="upgrade-step" :class="`is-${s.status}`"
            >
              <el-icon class="upgrade-step-ico">
                <component :is="stepIcon(s.status)" />
              </el-icon>
              <div class="upgrade-step-main">
                <div class="upgrade-step-title">{{ s.title }}</div>
                <div class="upgrade-step-cmd mono">{{ s.command }}</div>
              </div>
            </div>
          </div>

          <div class="upgrade-log" ref="logBox">
            <div v-if="!(upgrade.job?.log || '')" class="upgrade-log-empty">（等待输出…）</div>
            <pre class="upgrade-log-body mono">{{ upgrade.job?.log || '' }}</pre>
          </div>
        </template>
      </div>

      <template #footer>
        <div class="upgrade-foot">
          <el-button @click="upgrade.visible = false">
            {{ upgradeBusy ? '后台继续' : '关闭' }}
          </el-button>
          <el-button
            v-if="canStartUpgrade"
            type="primary"
            :loading="upgrade.starting"
            @click="startUpgrade"
          >
            <el-icon><Upload /></el-icon>开始升级
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 关于系统：版本标识的「正式户口」——排障时让人一眼说清跑的是哪一版 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Info /></el-icon>关于系统
        </span>
      </div>
      <div class="about-rows">
        <div class="about-row">
          <span class="about-label">版本</span>
          <span class="about-value mono">v{{ auth.sysVersion || '—' }}</span>
        </div>
        <div class="about-row">
          <span class="about-label">服务名</span>
          <span class="about-value">知识工作台 · Knowledge Workbench</span>
        </div>
        <div class="about-row">
          <span class="about-label">版本说明</span>
          <span class="about-value dim">
            升级离线包后此处的版本号会自动更新；报障时请附上版本号与「存储与备份」页的深度自检结果。
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../../api'
import { upgradeCommand, upgradeTip as upgradeTipText, DEPLOY_MODE, planSummary as planSummaryText, assetSize as assetSizeText, autoUpgradeSupported, enableCommands as enableCommandsOf } from '../../utils/update'
import { useAuthStore } from '../../stores/auth'
import PageTitle from '../../components/PageTitle.vue'
import MarkdownText from '../../components/MarkdownText.vue'

const auth = useAuthStore()

// ---- 系统更新（GitHub Releases）----
const updateLoading = ref(false)
const updateInfo = ref(null)          // null = 还没检查过

async function checkUpdate(refresh = false) {
  updateLoading.value = true
  try {
    updateInfo.value = await Api.updateCheck(refresh)
    // 检查完顺手问一次部署模式：离线包部署的机器上没有 git，
    // 页面上的「升级方法」必须给离线包的指引，给 git 命令只会
    // 得到 "git: command not found"（这正是最需要指引时的坑）
    refreshDeployMode()
  } catch { /* 拦截器已提示 */ } finally {
    updateLoading.value = false
  }
}

// 检查结果按 status 分类渲染，而不是去解析 error 文案 ——
// 后端已经把人话写好了，这里只负责挑个合适的样式 + 补一句「下一步怎么办」
const UPDATE_ALERT_META = {
  not_configured: {
    type: 'warning',
    hint: '到上面的「升级与更新」分组里填「owner/name」，保存后立即生效，不用重启容器。',
  },
  invalid_config: {
    type: 'error',
    hint: '到「升级与更新」分组里改正后重新保存。',
  },
  repo_not_found: {
    type: 'warning',
    hint: '核对仓库名是否拼写正确；私有仓库目前不支持（这里不带 GitHub Token）。',
  },
  no_release: {
    type: 'warning',
    hint: '在该 GitHub 仓库上发布一个 Release 之后再检查。',
  },
  access_denied: {
    type: 'warning',
    hint: 'GitHub 未认证限额是 60 次/小时/IP，等一会儿再试。',
  },
  timeout: {
    type: 'warning',
    hint: '容器到 api.github.com 的链路不通：检查出网，或在「升级与更新」里配置出站代理。',
  },
  network_error: {
    type: 'error',
    hint: '容器连不上 api.github.com：检查 DNS/防火墙，或在「升级与更新」里配置出站代理。',
  },
  proxy_error: {
    type: 'error',
    hint: '配置的代理连不上：核对「出站代理」里的地址与端口，或清空改成直连。',
  },
}

const updateAlert = computed(() => {
  const info = updateInfo.value
  if (!info || info.ok) return null
  const meta = UPDATE_ALERT_META[info.status] || { type: 'error', hint: '' }
  return {
    type: meta.type,
    title: info.error || '检查失败',
    hint: meta.hint,
  }
})

function copyUpgradeCmd() {
  navigator.clipboard?.writeText(upgradeCmd.value)
  ElMessage.success(`已复制：${upgradeCmd.value}`)
}

// 升级脚本是 v0.4.0 才进仓库的，旧版本的前端里没有这个文件。
// 按当前版本给不同的命令，别让用户去跑一条不存在的脚本。
//
// 第三个参数是部署模式：离线包部署的机器上根本没有 git，
// 给它 git 命令只会得到 "git: command not found"。
const deployMode = ref(DEPLOY_MODE.GIT)
const upgradeCmd = computed(() => upgradeCommand(
  updateInfo.value?.current, updateInfo.value?.latest, deployMode.value))
const upgradeTip = computed(() => upgradeTipText(updateInfo.value?.current, deployMode.value))

// ---- 一键升级弹窗 ----
//
// 为什么单独一个弹窗：升级会**重启整个服务**，那段时间里页面上任何一次
// 点击都可能落在一个正在重启的界面上。放进弹窗，状态、日志、等待都有地方安放。
//
// 可行性判定完全在后端做（只有它知道容器里有没有 git / docker、
// 编排文件带不带 build: 段），前端只负责把返回的结论讲清楚，
// 以及扛过第 4 步之后「后端没了」的那几十秒。

const POLL_MS = 1500           // 日志轮询间隔
const RESTART_WAIT_MS = 90000  // 第 4 步之后最多等多久（后端要重建容器）

const upgrade = reactive({
  visible: false,
  loading: false,     // 正在取可行性判定
  starting: false,    // 正在提交升级
  plan: null,
  job: null,
  phase: 'idle',      // idle | running | restarting | done | failed
  error: '',
  waitLeft: 0,
})

const logBox = ref(null)
let pollTimer = null

const upgradeBusy = computed(() => upgrade.phase === 'running' || upgrade.phase === 'restarting')
const manualCommands = computed(() => upgrade.plan?.manual_commands || [])
// 「在宿主机上跑这一行就能开启自动升级」——后端给的。
// 这跟手动升级命令不是一回事：手动命令是「这次怎么升」，
// 开启命令是「把自动升级这个能力装上」，装好之后每次升级都不用再跑命令。
const enableCommands = computed(() => enableCommandsOf(upgrade.plan))
// 目标版本在 Release 上的资产。离线部署要下载镜像包，
// 用户得先知道这玩意儿多大、要等多久。
const releaseAssets = computed(() => upgrade.plan?.release_assets || [])
// 这套部署形态本身支不支持自动升级。支持但前置条件没齐 → 显示「开启」引导；
// 压根不支持（比如没装任何编排文件）→ 只给手动路径。
const autoSupported = computed(() => autoUpgradeSupported(upgrade.plan))
// 计划里的步骤标题拼成一句人话：「下载镜像 → 导入镜像 → 重建容器」。
// 原来这句是写死的「拉取版本 → 切换版本 → 重建镜像 → 重启服务」，
// 离线部署会显示完全对不上的步骤。
const planSummary = computed(() => planSummaryText(upgrade.plan?.steps || []))
// 步骤：运行中用作业自己的状态（pending/running/done/failed），
// 没运行时用计划里的清单（只有标题与命令）
const jobSteps = computed(() => {
  const steps = upgrade.job?.steps || upgrade.plan?.steps || []
  return steps.map((s) => ({ ...s, status: s.status || 'pending' }))
})
const canStartUpgrade = computed(() =>
  !!upgrade.plan?.feasible && !!upgrade.plan?.target && !upgradeBusy.value && !upgrade.starting)

function stepIcon(status) {
  return { running: 'Loading', done: 'CircleCheck', failed: 'CircleClose' }[status] || 'Clock'
}

// 日志自动滚到底：正在看的人关心的是「现在写到哪了」
async function scrollLog() {
  await nextTick()
  const el = logBox.value
  if (el) el.scrollTop = el.scrollHeight
}

async function refreshDeployMode() {
  // 页面上的「升级方法」区块要知道部署模式，否则会给离线包部署的机器
  // 递一条它根本跑不了的 git 命令
  try {
    const plan = await Api.updatePlan(updateInfo.value?.latest || '')
    deployMode.value = plan?.mode === DEPLOY_MODE.OFFLINE ? DEPLOY_MODE.OFFLINE : DEPLOY_MODE.GIT
    return plan
  } catch {
    return null
  }
}

async function openUpgrade() {
  upgrade.visible = true
  upgrade.phase = 'idle'
  upgrade.error = ''
  upgrade.job = null
  upgrade.loading = true
  try {
    const plan = await Api.updatePlan(updateInfo.value?.latest || '')
    upgrade.plan = plan
    deployMode.value = plan?.mode === DEPLOY_MODE.OFFLINE ? DEPLOY_MODE.OFFLINE : DEPLOY_MODE.GIT
    // 后端把「查不到目标版本」这类错误放在 ok/error 里，HTTP 仍是 200
    if (plan && plan.ok === false && plan.error) upgrade.error = plan.error
  } catch (e) {
    upgrade.plan = null
    upgrade.error = e?.response?.data?.detail || '无法获取升级计划，请确认后端服务正常'
  } finally {
    upgrade.loading = false
  }
}

async function startUpgrade() {
  const plan = upgrade.plan
  if (!plan?.feasible || !plan.target) return
  // 二次确认：升级会重启服务，这是必须让人点头的一步
  try {
    await ElMessageBox.confirm(
      `即将把系统从 ${plan.current_display || plan.current} 升级到 ${plan.target}。\n\n`
      + '· 升级过程中服务会重启一次，期间系统不可用\n'
      + '· 「重建镜像」那一步最慢，通常要几分钟\n'
      + '· 升级失败不会自动回滚，需要照着日志手动处理\n\n'
      + '确定继续吗？',
      '确认执行一键升级',
      { type: 'warning', confirmButtonText: '开始升级', cancelButtonText: '再想想' }
    )
  } catch { return }

  upgrade.starting = true
  try {
    const res = await Api.updateApply(plan.target)
    upgrade.job = res.job
    upgrade.phase = 'running'
    ElMessage.success(res.already_running ? '已有升级作业在运行，已切到它的进度' : '升级已开始')
    scrollLog()
    pollJob()
  } catch (e) {
    upgrade.error = e?.response?.data?.detail || '无法启动升级'
    ElMessage.error(upgrade.error)
  } finally {
    upgrade.starting = false
  }
}

function pollJob() {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(pollOnce, POLL_MS)
}

async function pollOnce() {
  const jobId = upgrade.job?.job_id || ''
  try {
    const res = await Api.updateJob(jobId)
    const job = res.job
    if (job) {
      upgrade.job = job
      if (job.status === 'restarting') { enterRestartWait(); return }
      if (job.status === 'succeeded') { finishUpgrade(); return }
      if (job.status === 'failed') {
        upgrade.phase = 'failed'
        upgrade.error = job.error || '升级失败'
        return
      }
    }
    upgrade.phase = 'running'
    scrollLog()
    pollJob()
  } catch {
    // 轮询失败 = 后端正在被第 4 步重建掉。
    // 这不是错误，是「该转进等它回来的模式了」。
    enterRestartWait()
  }
}

// 进入「正在重启服务」模式：轮询会一直失败，直到新容器起来
function enterRestartWait() {
  if (upgrade.phase === 'restarting') return
  upgrade.phase = 'restarting'
  upgrade.waitLeft = Math.round(RESTART_WAIT_MS / 1000)
  waitBackend()
}

async function waitBackend() {
  const deadline = Date.now() + RESTART_WAIT_MS
  while (Date.now() < deadline) {
    try {
      await Api.upgradeHealth()
      // 后端回来了 —— 升级完成
      upgrade.phase = 'done'
      upgrade.waitLeft = 0
      ElMessage.success('服务已恢复，升级完成，正在刷新页面…')
      setTimeout(() => window.location.reload(), 2000)
      return
    } catch {
      upgrade.waitLeft = Math.max(0, Math.round((deadline - Date.now()) / 1000))
      await new Promise((r) => setTimeout(r, 2000))
    }
  }
  upgrade.phase = 'failed'
  upgrade.error = ('服务在 90 秒内没有恢复。请到服务器上执行 '
    + 'docker compose logs backend 看看到底卡在哪一步。')
}

function finishUpgrade() {
  upgrade.phase = 'done'
  ElMessage.success('升级完成，正在刷新页面…')
  setTimeout(() => window.location.reload(), 1500)
}

function copyManual() {
  // 只复制能执行的命令：注释行是给人看的，粘到终端里是噪音
  const cmds = manualCommands.value.filter((c) => !c.trim().startsWith('#'))
  navigator.clipboard?.writeText(cmds.join('\n'))
  ElMessage.success(`已复制 ${cmds.length} 条命令`)
}

function copyEnable() {
  // 开启命令里的注释行同样不该被粘走 —— 用户要粘到服务器终端里跑
  const cmds = enableCommands.value.filter((c) => !c.trim().startsWith('#'))
  navigator.clipboard?.writeText(cmds.join('\n'))
  ElMessage.success(`已复制 ${cmds.length} 条命令，粘贴到服务器终端执行`)
}

onUnmounted(() => {
  clearTimeout(pollTimer)
})

const loading = ref(false)
const saving = ref(false)
const probing = ref(false)
const loadError = ref('')
const items = ref([])
const file = ref('')
const precedence = ref([])
const targets = ref(null)
const probeResult = ref(null)
const draft = reactive({})

const candidates = computed(() => targets.value?.candidates || [])
const guides = computed(() => targets.value?.guides || [])
// 判断依据来自后端：Docker Desktop 下容器分不清宿主机磁盘，
// 所以「有没有独立盘」是「自动判断 或 部署方显式声明」的合并结论
const hasAlternate = computed(() => !!targets.value?.has_alternate_disk)

// 「升级与更新」分组里的两项：更新卡片要显示当前生效的仓库与它的来源
const repoItem = computed(() => items.value.find(i => i.key === 'update_repo') || null)
const proxyItem = computed(() => items.value.find(i => i.key === 'update_proxy') || null)
// 检查结果里的值比设置项更「新鲜」（它就是服务端此刻用的那个），
// 但检查还没做过时只有设置项可用，所以两者取其一
const effectiveRepo = computed(() => {
  if (updateInfo.value && updateInfo.value.repo) return updateInfo.value.repo
  return repoItem.value?.value || ''
})
const repoSource = computed(() => {
  if (updateInfo.value && updateInfo.value.repo_source) return updateInfo.value.repo_source
  return repoItem.value?.source || 'default'
})

const groups = computed(() => {
  const map = new Map()
  for (const it of items.value) {
    if (!map.has(it.group)) map.set(it.group, [])
    map.get(it.group).push(it)
  }
  return [...map.entries()].map(([name, list]) => ({ name, items: list }))
})

function srcLabel(s) {
  return { file: '系统设置', env: '环境变量', default: '代码默认值' }[s] || s
}
function srcTagType(s) {
  return { file: 'success', env: 'warning', default: 'info' }[s] || 'info'
}

// 每个分组给一个自己的图标：扫一眼就知道这一段管什么
const GROUP_ICONS = { '存储与备份': 'Coin', '安全': 'Lock', '升级与更新': 'Upload' }
function groupIcon(name) {
  return GROUP_ICONS[name] || 'Setting'
}

// ---- 行内格式校验（与后端 settings_store 的规则保持一致）----
// 为什么前端也要校验一遍：后端校验是最后一道防线，但那时用户已经
// 点完保存、离开了输入框。当场提示一次能省掉一轮来回。
// 前端的规则必须跟后端一致（后端是权威），所以这里只做同样形状的检查。
const REPO_RE = /^(?:https?:\/\/)?(?:github\.com\/)?([A-Za-z0-9._-]+)\/([A-Za-z0-9._-]+)$/

function validateRepo(v) {
  const t = String(v || '').trim().replace(/\/+$/, '')
  if (!t) return ''
  if (!REPO_RE.test(t)) return '格式应为「owner/name」，例如 your-org/kb-workbench'
  return ''
}
function validateProxy(v) {
  const t = String(v || '').trim()
  if (!t) return ''
  if (!/^https?:\/\//i.test(t)) return '代理地址必须以 http:// 或 https:// 开头'
  let u
  try {
    u = new URL(t)
  } catch {
    return '代理地址无法解析，请照着 http://主机:端口 的样子填'
  }
  if (!u.hostname) return '代理地址里缺少主机名，请写成 http://主机:端口'
  if (u.pathname && u.pathname !== '/') return '代理地址不需要带路径，只填 http://主机:端口'
  return ''
}
// 已经碰过的字段才提示错误：正在打字时全程飘红是很烦人的
const touched = reactive({})
function markTouched(key) { touched[key] = true }
function fieldError(it) {
  if (it.kind === 'repo') return validateRepo(draft[it.key])
  if (it.kind === 'proxy') return validateProxy(draft[it.key])
  return ''
}
function kindHint(it) {
  if (it.kind === 'repo') return '形如 owner/name；留空表示不做在线检查'
  if (it.kind === 'proxy') return '形如 http://主机:端口；留空表示直连'
  return ''
}
function fmtBytes(v) {
  if (v === null || v === undefined) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = Number(v), i = 0
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n >= 100 ? n.toFixed(0) : n.toFixed(1)} ${u[i]}`
}
function candRowClass({ row }) {
  if (row.blocked) return 'row-blocked'
  if (row.recommended) return 'row-good'
  return ''
}

// 口令项：只要输入框非空就算改动（后端不回显明文，没法比对原值）
function isDirty(it) {
  if (it.kind === 'secret') return !!draft[it.key]
  const a = draft[it.key]
  const b = it.value
  return a === undefined || a === null ? false : String(a) !== String(b)
}
const dirtyKeys = computed(() => items.value.filter(isDirty).map(i => i.key))

function fillDraft(keepDirty = false) {
  for (const it of items.value) {
    if (keepDirty && isDirty(it)) continue
    draft[it.key] = it.kind === 'secret' ? '' : it.value
  }
}
function revert(it) {
  draft[it.key] = it.kind === 'secret' ? '' : it.value
  if (it.kind === 'path') probeResult.value = null
}
function revertAll() {
  fillDraft(false)
  probeResult.value = null
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const s = await Api.settings()
    items.value = s.items || []
    file.value = s.file
    precedence.value = s.precedence || []
    fillDraft(false)
    probeResult.value = null
    // 候选目录单独容错：它挂了不该让整个页面变成空白
    try {
      targets.value = await Api.backupTargets()
    } catch (e) {
      targets.value = null
    }
  } catch (e) {
    loadError.value = e?.response?.data?.detail || '配置加载失败，请检查登录状态与后端服务'
  } finally {
    loading.value = false
  }
}

async function doProbe() {
  const p = draft.backup_dir
  if (!p) { ElMessage.warning('请先填写或选择一个目录'); return }
  probing.value = true
  try {
    probeResult.value = await Api.probePath(p)
  } catch (e) {
    probeResult.value = { ok: false, error: e?.response?.data?.detail || '测试失败' }
  } finally {
    probing.value = false
  }
}

async function save() {
  const payload = {}
  for (const it of items.value) {
    if (isDirty(it)) payload[it.key] = draft[it.key]
  }
  if (!Object.keys(payload).length) return
  // 先在本地过一遍格式：不合法的值发到后端也只是被拒，
  // 不如当场把行内错误亮出来，省一次往返
  for (const it of items.value) {
    if (!isDirty(it)) continue
    const err = fieldError(it)
    if (err) {
      touched[it.key] = true
      ElMessage.error(`「${it.label}」${err}`)
      return
    }
  }
  if (payload.backup_dir) {
    try {
      await ElMessageBox.confirm(
        `备份目录将改为：\n${payload.backup_dir}\n\n`
        + '改完之后新备份会落到新目录；已有备份不会自动搬过去，需要手动迁移或重新备份一次。',
        '确认修改备份目录', { type: 'warning', confirmButtonText: '确认修改', cancelButtonText: '再想想' }
      )
    } catch { return }
  }
  saving.value = true
  try {
    const res = await Api.saveSettings(payload)
    for (const w of res.warnings || []) ElMessage.warning(w)
    if (res.items) items.value = res.items
    fillDraft(false)
    probeResult.value = null
    ElMessage.success(`已保存：${(res.changed || []).join('、')}（立即生效，无需重启）`)
    try { targets.value = await Api.backupTargets() } catch (e) { /* 忽略 */ }
    // 仓库改了，之前那份检查结果已经对不上号了 —— 顺手重新查一次，
    // 让「保存即生效」在更新卡片上也能看见
    if ((res.changed || []).includes('update_repo')) {
      await checkUpdate(true)
    }
  } catch (e) {
    // 校验失败的具体原因由拦截器弹出，这里保持页面状态不变，便于改正后重存
  } finally {
    saving.value = false
  }
}

async function doReset(it) {
  try {
    await ElMessageBox.confirm(
      `把「${it.label}」恢复成环境变量/默认值？该设置会从配置文件中移除。`,
      '恢复默认', { type: 'warning' }
    )
  } catch { return }
  try {
    const res = await Api.resetSetting(it.key)
    if (res.items) items.value = res.items
    fillDraft(false)
    ElMessage.success('已恢复默认')
    try { targets.value = await Api.backupTargets() } catch (e) { /* 忽略 */ }
    // 仓库被恢复成环境变量/默认值后，原先那份检查结果同样作废
    if (it.key === 'update_repo') await checkUpdate(true)
  } catch (e) { /* 拦截器已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 0 0 76px; }
.load-err { margin-bottom: 14px; }

.card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.card-title {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px;
}
.card-title-text {
  display: inline-flex; align-items: center; gap: 6px;
  font-weight: 600; font-size: 15px; color: var(--el-text-color-primary);
}
.title-ico { color: var(--el-color-primary); }

.legend { display: flex; flex-direction: column; gap: 8px; }
.legend-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.legend-note { color: var(--el-text-color-regular); }

.note {
  display: flex; gap: 8px; align-items: flex-start;
  margin-top: 12px; padding: 10px 12px;
  border-radius: 8px; font-size: 13px; line-height: 1.7;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}
.note.warn {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
}
.note code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

.set-row {
  padding: 14px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}
.set-row:first-of-type { border-top: none; padding-top: 0; }
.set-row.dirty { background: var(--el-color-primary-light-9); border-radius: 8px; padding-left: 10px; padding-right: 10px; }
.set-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap;
}
.set-name {
  display: inline-flex; align-items: center; gap: 8px;
  font-weight: 600; color: var(--el-text-color-primary);
}
/* 环境变量名是内容，不是占位符。
   原来用的 placeholder 色（#b8bcc6）在白底上只有 2.23:1，
   读起来发飘 —— 用户要照着这个 key 去写 .env，看不清就容易写错。 */
.set-key { font-size: 12px; color: var(--text-tertiary); }
.set-help {
  margin: 6px 0 10px; font-size: 13px; line-height: 1.75;
  color: var(--el-text-color-regular); max-width: 900px;
}
.set-body { display: flex; flex-direction: column; gap: 10px; }
.set-foot {
  display: flex; align-items: center; gap: 10px;
  margin-top: 10px; font-size: 12px;
}
.dirty-tip { display: inline-flex; align-items: center; gap: 4px; color: var(--el-color-primary); }
.dim { color: var(--el-text-color-secondary); }
.bad-text { color: var(--el-color-danger); }

.path-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.secret-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.text-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.field-err {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 13px; color: var(--el-color-danger);
}

.probe {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; padding: 8px 10px; border-radius: 6px;
}
.probe.ok { background: var(--el-color-success-light-9); color: var(--el-color-success-dark-2); }
.probe.bad { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }

.cand-box { margin-top: 4px; }
.cand-title {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  font-size: 13px; color: var(--el-text-color-regular); margin-bottom: 8px;
}
.cand-warn { display: inline-flex; align-items: center; gap: 4px; color: var(--el-color-warning-dark-2); }
/* 备选存储路径是内容，不是占位符 —— 用户要照着它去挂盘。
   原来继承的 placeholder 色在白底上只有 2.23:1，几乎读不出来。 */
.opt-path { margin-right: 10px; color: var(--text-tertiary); }
.opt-tags { float: right; }
.data-table { width: 100%; }

.guide { flex: 1; }
.guide p { margin: 0 0 8px; }
.guide-step { margin-top: 6px; }
.guide-title { font-weight: 600; margin-bottom: 4px; }
.guide-code {
  margin: 0; padding: 8px 10px; border-radius: 6px; overflow-x: auto;
  background: var(--el-fill-color-darker);
  color: var(--el-text-color-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; line-height: 1.6;
}

.save-bar {
  position: sticky; bottom: 0; z-index: 5;
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 12px 18px; border-radius: 10px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, .06);
}
.save-info {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--el-text-color-regular);
}

/* 关于系统 */
.about-rows { display: flex; flex-direction: column; gap: 10px; }
.about-row { display: flex; gap: 16px; align-items: baseline; }
.about-label {
  flex-shrink: 0;
  width: 72px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.about-value { font-size: 14px; color: var(--el-text-color-primary); }
.about-value.mono { font-family: var(--font-mono); font-weight: 600; }
.about-value.dim { color: var(--el-text-color-secondary); font-size: 13px; }

/* 系统更新 */
.update-alert { margin-bottom: 4px; }
.update-hint { margin-top: 6px; font-size: 13px; line-height: 1.6; }
.upd-tag { margin-left: 8px; font-weight: 600; }
.update-notes {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--radius);
  background: var(--bg-subtle);
}
.update-notes-title {
  font-size: 12px; font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.update-notes-body { font-size: 13px; line-height: 1.6; }
.update-howto {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--el-color-success-light-7);
  border-radius: var(--radius);
  background: var(--el-color-success-light-9);
}
.update-howto-title {
  font-size: 13px; font-weight: 600;
  display: flex; align-items: center; gap: 6px;
}
.upd-cmd {
  display: block;
  margin-top: 8px;
  padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow-x: auto;
}
.update-howto-tip { margin-top: 6px; font-size: 12px; line-height: 1.6; }
.upd-link { margin-left: 6px; }

:deep(.row-blocked) { opacity: .75; }
:deep(.row-good) { background: var(--el-color-success-light-9); }

/* ==========================================================
   一键升级弹窗
   这一块之前**一个样式都没有**：47 个 class 全是裸 HTML，
   渲染出来就是一堵文字墙，用户反馈「一鍵升級」界面没法看。
   这里按「结论 → 障碍 → 动作 → 进度 → 日志」的顺序分层，
   让人一眼知道：能不能升、缺什么、现在该按哪个键。
   ========================================================== */
.upgrade-dialog { --el-dialog-width: min(920px, 94vw); }
.upgrade-body {  display: flex; flex-direction: column; gap: var(--space-4);
  max-height: min(66vh, 620px); overflow-y: auto;
  padding-right: 4px;
}

/* —— 版本条 —— */
.upgrade-versions {
  display: flex; align-items: center; gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.upgrade-ver { display: flex; flex-direction: column; gap: 2px; min-width: 96px; }
.upgrade-ver-label {
  font-size: var(--text-xs); color: var(--text-tertiary);
  letter-spacing: .02em;
}
.upgrade-ver-value { font-size: var(--text-lg); font-weight: 600; color: var(--text-primary); }
.upgrade-arrow { color: var(--text-disabled); flex-shrink: 0; }
.upgrade-mode {
  margin-left: auto; flex-shrink: 0;
  border-radius: var(--radius-full); font-weight: 500;
}

/* —— 障碍清单 —— */
.upgrade-blockers {
  display: flex; flex-direction: column; gap: var(--space-2);
}
.upgrade-blockers-title {
  font-size: var(--text-sm); font-weight: 600; color: var(--text-secondary);
}
.upgrade-blocker {
  padding: var(--space-3) var(--space-4);
  background: var(--warning-bg);
  border: 1px solid color-mix(in srgb, var(--warning) 26%, transparent);
  border-radius: var(--radius-md);
}
.upgrade-blocker-head {
  display: flex; align-items: center; gap: 6px;
  font-size: var(--text-sm); font-weight: 600; color: var(--warning-text);
}
.upgrade-blocker-detail {
  margin-top: 4px;
  font-size: var(--text-sm); line-height: 1.6; color: var(--text-secondary);
}
.upgrade-blocker-fix {
  margin-top: 6px;
  font-size: var(--text-sm); line-height: 1.6; color: var(--text-primary);
}

/* —— 开启引导：这是唯一「按一下就能做」的地方，要最显眼 —— */
.upgrade-enable {
  padding: var(--space-4);
  background: var(--primary-bg);
  border: 1px solid color-mix(in srgb, var(--primary) 32%, transparent);
  border-radius: var(--radius-lg);
}
.upgrade-enable-title {
  display: flex; align-items: center; gap: 6px;
  font-size: var(--text-sm); font-weight: 600; color: var(--text-primary);
}
.upgrade-enable-title .el-icon { color: var(--primary); }
.upgrade-enable-title .el-button { margin-left: auto; }
.upgrade-enable-cmd {
  margin: var(--space-3) 0 0;
  padding: var(--space-3) var(--space-4);
  background: var(--bg-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm); line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap; word-break: break-all;
}
.upgrade-enable-tip {
  margin-top: var(--space-3);
  font-size: var(--text-sm); line-height: 1.7; color: var(--text-secondary);
}
.upgrade-enable-tip b { color: var(--danger-text); font-weight: 600; }

/* —— Release 资产 —— */
.upgrade-assets {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.upgrade-assets-title {
  font-size: var(--text-sm); font-weight: 600; color: var(--text-secondary);
  margin-bottom: var(--space-2);
}
.upgrade-asset {
  display: flex; align-items: center; gap: 8px;
  font-size: var(--text-sm); color: var(--text-secondary);
  padding: 2px 0;
}
.upgrade-asset .el-icon { color: var(--text-disabled); }
.upgrade-asset-name { color: var(--text-primary); }
.upgrade-asset-size { margin-left: auto; color: var(--text-tertiary); }

/* —— 脏文件 / 警告 —— */
.upgrade-dirty {
  padding: var(--space-3) var(--space-4);
  background: var(--danger-bg);
  border: 1px solid color-mix(in srgb, var(--danger) 26%, transparent);
  border-radius: var(--radius-md);
}
.upgrade-dirty-title {
  font-size: var(--text-sm); font-weight: 600; color: var(--danger-text);
  margin-bottom: var(--space-2);
}
.upgrade-dirty-file {
  display: inline-block; margin: 0 6px 4px 0;
  padding: 2px 7px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs); color: var(--text-secondary);
}
.upgrade-warnings { display: flex; flex-direction: column; gap: 6px; }
.upgrade-warning {
  display: flex; align-items: flex-start; gap: 6px;
  padding: var(--space-2) var(--space-3);
  background: var(--info-bg); border-radius: var(--radius-sm);
  font-size: var(--text-sm); line-height: 1.6; color: var(--text-secondary);
}
.upgrade-warning .el-icon { color: var(--info-text); flex-shrink: 0; margin-top: 2px; }

/* —— 更新内容 —— */
.upgrade-notes {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.upgrade-notes-title {
  font-size: var(--text-sm); font-weight: 600; color: var(--text-secondary);
  margin-bottom: var(--space-2);
}
.upgrade-notes-body {
  font-size: var(--text-sm); line-height: 1.7; color: var(--text-secondary);
  max-height: 220px; overflow-y: auto;
}

/* —— 手动命令 —— */
.upgrade-manual {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.upgrade-manual-title {
  display: flex; align-items: center; gap: 6px;
  font-size: var(--text-sm); font-weight: 600; color: var(--text-primary);
}
.upgrade-manual-title .el-button { margin-left: auto; }
.upgrade-manual-cmd {
  margin: var(--space-3) 0 0;
  padding: var(--space-3) var(--space-4);
  background: var(--bg-sunken); border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm); line-height: 1.7; color: var(--text-primary);
  white-space: pre-wrap; word-break: break-all;
}
.upgrade-manual-tip {
  margin-top: var(--space-2);
  font-size: var(--text-sm); line-height: 1.6; color: var(--text-tertiary);
}

/* —— 执行中 —— */
.upgrade-phase {
  display: flex; align-items: center; gap: 8px;
  padding: var(--space-3) var(--space-4);
  background: var(--primary-bg);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
  border-radius: var(--radius-md);
  font-size: var(--text-sm); font-weight: 500; color: var(--text-primary);
}
.upgrade-phase .el-icon { color: var(--primary); }

.upgrade-steps {
  display: flex; flex-direction: column; gap: var(--space-1);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.upgrade-step {
  display: flex; align-items: flex-start; gap: var(--space-3);
  padding: var(--space-2) 0;
}
.upgrade-step + .upgrade-step { border-top: 1px solid var(--border-light); }
.upgrade-step-ico { margin-top: 2px; color: var(--text-disabled); flex-shrink: 0; }
.upgrade-step.is-running .upgrade-step-ico { color: var(--primary); }
.upgrade-step.is-done .upgrade-step-ico { color: var(--success-text); }
.upgrade-step.is-failed .upgrade-step-ico { color: var(--danger-text); }
.upgrade-step-main { flex: 1; min-width: 0; }
.upgrade-step-title { font-size: var(--text-sm); font-weight: 500; color: var(--text-primary); }
.upgrade-step.is-pending .upgrade-step-title { color: var(--text-tertiary); font-weight: 400; }
.upgrade-step-cmd {
  margin-top: 2px;
  font-size: var(--text-xs); color: var(--text-tertiary);
  word-break: break-all;
}

/* —— 日志 —— */
.upgrade-log {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-sunken);
}
.upgrade-log-body {
  margin: 0; padding: var(--space-3) var(--space-4);
  max-height: 240px; overflow-y: auto;
  font-size: var(--text-xs); line-height: 1.65;
  color: var(--text-secondary);
  white-space: pre-wrap; word-break: break-all;
}
.upgrade-log-empty { color: var(--text-disabled); font-style: italic; }

/* —— 底部动作区 —— */
.upgrade-foot { display: flex; align-items: center; gap: var(--space-3); }
.upgrade-foot .el-button { margin-left: 0; }
</style>
