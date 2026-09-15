<template>
  <div class="batch-page mpau-card">
    <!-- 1. 页头卡：标题 + 步骤 + 工具条 -->
    <div class="sec-card head-card">
      <div class="page-head">
        <h2 class="mpau-card-title">📦 批量发布</h2>
        <span class="steps mpau-dim">① 扫描文件夹/导入CSV/选择单条视频 → ② 填 AI 提示词(可选) → ③ AI 批量生成文案 → ④ 审核预览 → ⑤ 一键多平台发布</span>
      </div>
      <div class="toolbar">
        <el-select
          :model-value="store.batchId" class="batch-sel" placeholder="选择批次"
          @change="onBatchChange"
        >
          <el-option value="" label="＋ 新批次" />
          <el-option
            v-for="b in store.batches" :key="b.batch_id" :value="b.batch_id"
            :label="`${b.batch_id} (${b.total}条 · 成${b.success || 0}/败${b.failed || 0})`"
          />
        </el-select>
        <el-input v-model="dir" class="dir-input" placeholder="D:/videos/batch1" clearable @keyup.enter="onScan" />
        <el-button @click="dirBrowser = true">📁 选择文件夹</el-button>
        <el-button @click="videoBrowser = true">🎬 选择单条视频</el-button>
        <el-button type="primary" :loading="store.scanning" @click="onScan">🔍 扫描</el-button>
        <el-button @click="csvBrowser = true">📥 导入 CSV</el-button>
        <el-button :disabled="!store.batchId" @click="exportCsv">📤 导出清单</el-button>
      </div>
    </div>

    <!-- 2. 账号中心 -->
    <AccountMapping />

    <!-- 3. 主区：左工作流 + 右状态栏 -->
    <div class="main-rail">
      <div class="main-col">
        <!-- 文案生成卡：AI 提示词 + 操作 + 进度 -->
        <div class="sec-card gen-card">
          <h3 class="mpau-card-title gen-title">
            ✨ 文案生成
            <span class="mpau-dim gen-sub">（可选，整批共用：约束文案风格/结构/卖点，也可写平台条件指令；「人工标题」是视频专属角度）</span>
          </h3>
          <el-input
            v-model="briefText" type="textarea" :rows="3" maxlength="500" show-word-limit
            placeholder="例：生成口语化的文案，卖点：椰蓉面包层层拉丝、进口椰蓉、适合早餐下午茶；结尾加一句引导；各平台按自己的调性写"
            @input="onBriefInput"
          />
          <div class="actions">
            <el-button class="mpau-btn-grad" :loading="store.generating" @click="onGenerate">✨ 一键生成全部文案</el-button>
            <el-button class="toggle-btn" :class="{ on: withDesc }" @click="withDesc = !withDesc">生成描述</el-button>
            <el-button class="toggle-btn" :class="{ on: withTags }" @click="withTags = !withTags">生成标签</el-button>
            <el-button class="toggle-btn" :class="{ on: withGoodsTitle }" @click="withGoodsTitle = !withGoodsTitle">商品短标题</el-button>
            <el-button type="success" plain @click="onApproveAll">✅ 全部排队</el-button>
            <el-button type="primary" @click="onOpenRun">🚀 一键发布</el-button>
            <el-button :disabled="!store.batchId" @click="exportReport">📄 导出报告</el-button>
            <el-button type="danger" plain :disabled="!store.batchId" @click="onDeleteBatch">🗑 删除批次</el-button>
          </div>

          <!-- 生成进度 -->
          <div v-if="genActive" class="prog-box">
            <div class="prog-line">
              <b class="mpau-info">🤖 文案生成中：{{ store.gen.done }}/{{ store.gen.total }}</b>
              <span class="mpau-dim cur-file">{{ store.gen.current }}</span>
            </div>
            <el-progress :percentage="genPct" :stroke-width="8" />
          </div>

          <!-- 发布进度 -->
          <div v-if="store.runStatus" class="prog-box">
            <div class="prog-line">
              <b>发布进度：{{ runDone }}/{{ runSummary.total }}（{{ runPct }}%）</b>
              <el-tag
                v-for="s in runBadges" :key="s.key" size="small" class="st-badge"
                :type="s.type" :effect="s.color ? 'dark' : 'light'"
                :color="s.color" :style="s.color ? { color: '#fff', borderColor: 'transparent' } : undefined"
              >{{ s.text }} {{ s.count }}</el-tag>
              <span v-if="store.runStatus.scheduler.message" class="mpau-dim sched-msg">{{ store.runStatus.scheduler.message }}</span>
              <el-button
                v-if="store.runStatus.scheduler.alive" type="danger" size="small" plain
                @click="onStop"
              >🛑 停止</el-button>
            </div>
            <el-progress :percentage="runPct" :stroke-width="8" :status="runSummary.failed ? 'exception' : undefined" />
          </div>
        </div>

        <!-- 清单卡 -->
        <div class="sec-card table-card">
          <h3 class="mpau-card-title table-title">📋 扫描视频清单（{{ store.items.length }}）</h3>

          <div v-if="store.items.length" class="sel-bar">
            <span class="mpau-info">已选 {{ selected.length }} 条</span>
            <el-button size="small" type="primary" :disabled="!selected.length" @click="onApproveSelected">✅ 审核确定</el-button>
            <el-button size="small" :disabled="!selected.length" @click="onCancelSelected">↩ 取消所选</el-button>
          </div>

          <template v-if="store.items.length">
            <el-table
              ref="tableRef" :data="pagedItems" row-key="id" class="items-table"
              @selection-change="onSelectionChange"
            >
              <el-table-column type="selection" width="36" />
              <el-table-column label="视频文件" min-width="200">
                <template #default="{ row }">
                  <div class="vcell">
                    <span class="thumb">🎬</span>
                    <div class="vmeta">
                      <div class="vname" :title="row.video_path">{{ fileName(row.video_path) }}</div>
                      <div class="vsize mpau-dim">{{ fmtBytes(videoSize(row.video_id)) }}</div>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="平台" width="110">
                <template #default="{ row }">
                  <span class="pcell">
                    <PlatformBadge :platform="row.platform" />
                    <span>{{ row.platform_cn }}</span>
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="92">
                <template #default="{ row }">
                  <el-tag
                    size="small" :type="statusOf(row).type"
                    :effect="statusOf(row).color ? 'dark' : 'light'"
                    :color="statusOf(row).color"
                    :style="statusOf(row).color ? { color: '#fff', borderColor: 'transparent' } : undefined"
                  >{{ statusOf(row).text }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="生成标题" min-width="220">
                <template #default="{ row }">
                  <span class="tcell">
                    <span class="ttext" :title="row.title">{{ row.title || '-' }}</span>
                    <el-tooltip v-if="errIssues(row).length" placement="top" :content="errIssues(row).join('\n')">
                      <el-icon class="mpau-err warn-ico"><WarningFilled /></el-icon>
                    </el-tooltip>
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="账号" width="120">
                <template #default="{ row }">
                  <span v-if="row.account">{{ row.account }}</span>
                  <span v-else class="mpau-dim">未登录</span>
                </template>
              </el-table-column>
              <el-table-column label="更新时间" width="96">
                <template #default="{ row }">{{ fmtTime(row.updated) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="176" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="onPreview(row)">预览</el-button>
                  <el-button link type="primary" size="small" @click="onEdit(row)">编辑</el-button>
                  <el-dropdown trigger="click" @command="(cmd: string) => onRowCmd(cmd, row)">
                    <el-button link type="primary" size="small">更多<el-icon><ArrowDown /></el-icon></el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="regen">⟲ 重新生成</el-dropdown-item>
                        <el-dropdown-item v-if="canRetry(row)" command="retry">🔁 重试</el-dropdown-item>
                        <el-dropdown-item command="approve">{{ row.status === 'approved' ? '↩ 取消批准' : '✓ 批准' }}</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
              </el-table-column>
            </el-table>
            <div class="pager">
              <el-pagination
                v-model:current-page="page" layout="total, prev, pager, next"
                :total="store.items.length" :page-size="PAGE_SIZE" background
              />
            </div>
          </template>

          <template v-else-if="store.videos.length">
            <div class="video-list">
              <div v-for="v in store.videos" :key="v.id" class="vrow">
                <span class="thumb">🎬</span>
                <span class="vname" :title="v.path">{{ fileName(v.path) }}</span>
                <span class="mpau-dim">{{ fmtBytes(v.size) }}</span>
              </div>
            </div>
            <div class="hint mpau-dim">已扫描 {{ store.videos.length }} 个视频 · 填好「AI 提示词」后点 ✨ 一键生成全部文案，生成后表格按「视频 × 平台」展示全部可操作条目</div>
          </template>

          <div v-else class="empty-box">
            <div class="empty-ico">📦</div>
            <div class="mpau-dim">选一个文件夹扫描，或点「🎬 选择单条视频」：添加后为每条视频生成各平台文案</div>
          </div>
        </div>
      </div>

      <!-- 右栏：状态总览 -->
      <div class="rail">
        <StatsCards compact />
        <TaskQueuePanel />
        <BatchDonut />
        <div class="mpau-card notes-card">
          <h3 class="mpau-card-title">📖 发布说明</h3>
          <ol class="notes">
            <li>请先绑定各平台账号，确保可正常发布。</li>
            <li>建议先生成文案并预览，确认无误后再批量发布。</li>
            <li>发布任务将按队列顺序依次执行，可在任务队列查看进度。</li>
            <li>失败的任务可重试或编辑后重新发布。</li>
          </ol>
        </div>
        <WarningsCard />
      </div>
    </div>

    <!-- 弹窗 -->
    <FileBrowserDialog v-model="dirBrowser" mode="dir" :initial-path="dir" @select="onDirPick" />
    <FileBrowserDialog v-model="csvBrowser" mode="csv" :initial-path="dir" @select="onImportCsv" />
    <FileBrowserDialog v-model="videoBrowser" mode="video" :initial-path="dir" @select="onAddVideo" />
    <ItemPreviewDialog v-model="previewVisible" :item="currentItem" />
    <ItemEditDrawer v-model="editVisible" :item="currentItem" />
    <RunOptionsDialog v-model="runVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, WarningFilled } from '@element-plus/icons-vue'
import { batchReportUrl, batchVideosCsvUrl } from '../api'
import type { Item } from '../api/types'
import { useAccountsStore } from '../stores/accounts'
import { useBatchStore } from '../stores/batch'
import { debounce, fileName, fmtBytes, fmtTime } from '../utils/format'
import FileBrowserDialog from '../components/FileBrowserDialog.vue'
import PlatformBadge from '../components/PlatformBadge.vue'
import AccountMapping from '../components/batch/AccountMapping.vue'
import StatsCards from '../components/batch/StatsCards.vue'
import BatchDonut from '../components/batch/BatchDonut.vue'
import WarningsCard from '../components/batch/WarningsCard.vue'
import ItemEditDrawer from '../components/batch/ItemEditDrawer.vue'
import ItemPreviewDialog from '../components/batch/ItemPreviewDialog.vue'
import RunOptionsDialog from '../components/batch/RunOptionsDialog.vue'
import TaskQueuePanel from '../components/tasks/TaskQueuePanel.vue'

const PAGE_SIZE = 10

type TagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'
const STATUS_META: Record<string, { text: string; type: TagType; color?: string }> = {
  draft: { text: '待审阅', type: 'info' },
  approved: { text: '已批准', type: 'primary' },
  running: { text: '发布中', type: 'warning' },
  success: { text: '成功', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  skipped: { text: '跳过', type: 'info' },
  needs_manual: { text: '需人工', type: 'warning' },
  interrupted: { text: '已中断', type: 'info', color: '#8b5cf6' },
}
const STATUS_ORDER = ['draft', 'approved', 'running', 'success', 'failed', 'skipped', 'needs_manual', 'interrupted']

const store = useBatchStore()
const accounts = useAccountsStore()

// ---- 工具条 ----
const dir = ref('')
const dirBrowser = ref(false)
const csvBrowser = ref(false)
const videoBrowser = ref(false)

async function onBatchChange(v: string) {
  if (!v) { store.newBatch(); return }
  try { await store.selectBatch(v) } catch { /* 拦截器已提示 */ }
}
async function onDirPick(p: string) {
  dir.value = p
  await onScan() // 选中文件夹即扫描, 无需再点「扫描」
}
async function onScan() {
  const d = dir.value.trim()
  if (!d) { ElMessage.warning('请先选择文件夹'); return }
  try {
    const resp = await store.scan(d)
    ElMessage.success(`✅ 扫描到 ${resp.videos.length} 个视频，批次 ${resp.batch_id}`)
  } catch { /* 拦截器已提示 */ }
}
async function onAddVideo(path: string) {
  // 单条视频并入当前批次(无批次自动新建), 之后完全走批量视频的操作逻辑
  try {
    const resp = await store.addVideo(path)
    if (resp.added) {
      ElMessage.success(`✅ 已加入批次 ${resp.batch_id}：${fileName(resp.video.path)}`)
    } else {
      ElMessage.info('该视频已在当前批次，未重复添加')
    }
  } catch { /* 拦截器已提示 */ }
}
async function onImportCsv(path: string) {
  try {
    const resp = await store.importCsv(path)
    ElMessage.success(`✅ 已导入 ${resp.videos.length} 个视频，批次 ${resp.batch_id}`)
  } catch { /* 拦截器已提示 */ }
}
function exportCsv() {
  if (!store.batchId) return
  window.open(batchVideosCsvUrl(store.batchId), '_blank')
}
function exportReport() {
  if (!store.batchId) { ElMessage.warning('还没有批次'); return }
  window.open(batchReportUrl(store.batchId), '_blank')
}

// ---- AI 提示词(600ms 防抖落库) ----
const briefText = ref(store.brief)
const saveBrief = debounce((t: string) => { void store.saveBrief(t).catch(() => { /* 拦截器已提示 */ }) }, 600)
function onBriefInput() { saveBrief(briefText.value) }
watch(() => store.brief, (v) => { if (v !== briefText.value) briefText.value = v })

// ---- 操作按钮 ----
const withDesc = ref(true)
const withTags = ref(true)
const withGoodsTitle = ref(true)
const genActive = ref(false)

const genPct = computed(() => (store.gen.total ? Math.round((store.gen.done / store.gen.total) * 100) : 0))

async function onGenerate() {
  if (!store.batchId) { ElMessage.warning('请先扫描文件夹建立批次'); return }
  if (!store.videos.length) { ElMessage.warning('请先扫描文件夹或导入 CSV'); return }
  const platforms = Object.keys(store.mapping).filter((p) => store.mapping[p])
  if (!platforms.length) { ElMessage.warning('请先在账号映射里选择至少一个平台账号'); return }
  try {
    await store.generateAll(withDesc.value, withTags.value, withGoodsTitle.value)
  } catch { return }
  genActive.value = true
  void pollGen()
}

async function onApproveAll() {
  if (!store.batchId || !store.items.length) { ElMessage.warning('还没有生成文案'); return }
  try {
    await ElMessageBox.confirm('确认将全部「待审阅 / 需人工」的文案批准排队吗？', '全部排队', {
      type: 'warning', confirmButtonText: '全部排队', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    const r = await store.approve()
    ElMessage.success(`✅ 已批准 ${r.approved} 条`)
  } catch { /* 拦截器已提示 */ }
}

const runVisible = ref(false)
function onOpenRun() {
  if (!store.batchId) { ElMessage.warning('还没有批次，请先扫描+生成'); return }
  runVisible.value = true
}

async function onDeleteBatch() {
  if (!store.batchId) { ElMessage.warning('还没有批次'); return }
  try {
    await ElMessageBox.confirm(
      `确定删除批次 ${store.batchId} 吗？\n将删除该批次全部条目（含已批准/已发布记录），视频文件与账号不受影响。`,
      '删除批次',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await store.removeBatch()
    ElMessage.success('🗑 批次已删除')
  } catch { /* 拦截器已提示 */ }
}

// ---- 生成进度轮询(2s 递归) ----
let genTimer: ReturnType<typeof setTimeout> | undefined
let genPolling = false
async function pollGen() {
  if (genPolling) return
  genPolling = true
  let running = true
  while (running) {
    try { running = await store.pollGenOnce() } catch { running = false }
    if (running) await new Promise((r) => { genTimer = setTimeout(r, 2000) })
  }
  genPolling = false
  genActive.value = false
  const g = store.gen
  if (g.error) ElMessage.error(`生成失败: ${g.error}`)
  else ElMessage({ message: `✅ 生成完成：${g.done} 条文案，${g.failed} 条失败（需人工）`, type: g.failed ? 'warning' : 'success' })
}

// ---- 发布状态轮询(4s 递归) ----
let statusTimer: ReturnType<typeof setTimeout> | undefined
let statusPolling = false
const statusAlive = computed(() => !!store.runStatus?.scheduler?.alive)
const runSummary = computed(() => store.runStatus?.summary ?? {
  total: 0, draft: 0, approved: 0, running: 0, success: 0, failed: 0, skipped: 0, needs_manual: 0, interrupted: 0,
})
const runDone = computed(() => runSummary.value.success + runSummary.value.failed + runSummary.value.skipped)
const runPct = computed(() => (runSummary.value.total ? Math.round((runDone.value / runSummary.value.total) * 100) : 0))
const runBadges = computed(() =>
  STATUS_ORDER.map((k) => ({
    key: k,
    text: STATUS_META[k].text,
    type: STATUS_META[k].type,
    color: STATUS_META[k].color,
    count: (runSummary.value as Record<string, number>)[k] ?? 0,
  })),
)

async function pollStatus() {
  if (statusPolling) return
  statusPolling = true
  while (statusAlive.value) {
    try { await store.loadStatus() } catch { /* 拦截器已提示 */ }
    if (!statusAlive.value) break
    await new Promise((r) => { statusTimer = setTimeout(r, 4000) })
  }
  statusPolling = false
}
watch(statusAlive, (alive, prev) => {
  if (alive) { void pollStatus(); return }
  if (prev) {
    const s = runSummary.value
    ElMessage({
      message: s.failed ? `批次结束：失败 ${s.failed} 条` : '批次结束：全部完成',
      type: s.failed ? 'warning' : 'success',
    })
  }
})

async function onStop() {
  try {
    await store.stop()
    ElMessage.info('🛑 已请求停止（当前条完成后终止）')
  } catch { /* 拦截器已提示 */ }
}

// ---- 表格 ----
const tableRef = ref<{ clearSelection: () => void }>()
const page = ref(1)
const selected = ref<Item[]>([])
const selectedIds = computed(() => selected.value.map((i) => i.id))
const pagedItems = computed(() => store.items.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))

const videoMap = computed(() => {
  const m: Record<number, (typeof store.videos)[number]> = {}
  for (const v of store.videos) m[v.id] = v
  return m
})
function videoSize(videoId: number) { return videoMap.value[videoId]?.size ?? 0 }

function statusOf(it: Item) { return STATUS_META[it.status] ?? { text: it.status, type: 'info' as TagType } }
function canRetry(it: Item) { return it.status === 'failed' || it.status === 'skipped' }
function errIssues(it: Item): string[] {
  const out: string[] = []
  for (const c of it.candidates ?? []) {
    for (const is of c.issues ?? []) if (is.level === 'error') out.push(is.msg)
  }
  return out
}
function onSelectionChange(rows: Item[]) { selected.value = rows }
function clearSelection() { tableRef.value?.clearSelection() }

watch(() => store.batchId, () => {
  page.value = 1
  selected.value = []
  clearSelection()
})
watch(() => store.items.length, (n) => {
  const maxPage = Math.max(1, Math.ceil(n / PAGE_SIZE))
  if (page.value > maxPage) page.value = maxPage
})

// ---- 行操作 ----
const currentItem = ref<Item | null>(null)
const previewVisible = ref(false)
const editVisible = ref(false)
function onPreview(it: Item) { currentItem.value = it; previewVisible.value = true }
function onEdit(it: Item) { currentItem.value = it; editVisible.value = true }

async function onRowCmd(cmd: string, it: Item) {
  if (cmd === 'regen') {
    try {
      await store.regenerate(it.id)
      ElMessage.success('✅ 已换新文案')
    } catch { /* 拦截器已提示 */ }
  } else if (cmd === 'retry') {
    try {
      await store.retry(it.id)
      ElMessage.success('已重新加入待发布队列')
    } catch { /* 拦截器已提示 */ }
  } else if (cmd === 'approve') {
    const approved = it.status === 'approved'
    if (!approved && !it.title) { ElMessage.warning('该条标题为空，先填标题再批准'); return }
    try {
      await store.approve([it.id], !approved)
    } catch { /* 拦截器已提示 */ }
  }
}

// ---- 批量操作条 ----
async function onApproveSelected() {
  if (!selected.value.length) return
  try {
    const r = await store.approve(selectedIds.value, true)
    ElMessage.success(`✅ 审核确定：已批准 ${r.approved} 条`)
    clearSelection()
  } catch { /* 拦截器已提示 */ }
}
async function onCancelSelected() {
  if (!selected.value.length) return
  try {
    const r = await store.approve(selectedIds.value, false)
    ElMessage.info(`↩ 已取消 ${r.approved} 条`)
    clearSelection()
  } catch { /* 拦截器已提示 */ }
}

// ---- 生命周期 ----
onMounted(async () => {
  await Promise.allSettled([store.loadBatches(), accounts.refreshAll()])
  // 页面重开时恢复进行中的生成/发布轮询
  if (store.batchId) {
    try {
      if (await store.pollGenOnce()) { genActive.value = true; void pollGen() }
    } catch { /* 拦截器已提示 */ }
    if (statusAlive.value) void pollStatus()
  }
})
onUnmounted(() => {
  if (genTimer) clearTimeout(genTimer)
  if (statusTimer) clearTimeout(statusTimer)
})
</script>

<style scoped>
.batch-page { padding: 18px 20px; }

/* 分区卡片(页头/文案生成/清单共用) */
.sec-card {
  padding: 14px 16px;
  border: 1px solid var(--mpau-border-soft); border-radius: 10px;
  background: rgba(14, 20, 36, 0.35);
}

.page-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.page-head .mpau-card-title { margin: 0; font-size: 16px; }
.steps { font-size: 12px; }

.toolbar { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.batch-sel { width: 220px; flex: none; }
.dir-input { flex: 1; min-width: 240px; }

.gen-title { margin-bottom: 10px; }
.gen-sub { font-weight: 400; font-size: 12px; }

.actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.toggle-btn {
  background: rgba(148, 163, 184, 0.08); border-color: var(--mpau-border-soft); color: var(--mpau-text-dim);
}
.toggle-btn.on {
  background: rgba(99, 102, 241, 0.18); border-color: var(--mpau-primary); color: #c7d2fe;
  box-shadow: inset 0 0 0 1px var(--mpau-primary);
}

.prog-box {
  margin-top: 12px; padding: 12px 14px;
  border: 1px solid var(--mpau-border-soft); border-radius: 10px;
  background: rgba(14, 20, 36, 0.55);
}
.prog-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; font-size: 13px; }
.cur-file { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40%; }
.st-badge { flex: none; }
.sched-msg { font-size: 12.5px; }

.main-rail { display: flex; gap: 14px; margin-top: 14px; align-items: flex-start; }
.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.rail { width: 320px; flex: none; display: flex; flex-direction: column; gap: 12px; }
@media (max-width: 1400px) {
  .main-rail { flex-direction: column; }
  .rail { width: 100%; flex-direction: row; flex-wrap: wrap; }
  .rail > * { flex: 1 1 280px; }
}

.table-title { margin: 0 0 10px; }

.sel-bar {
  display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  padding: 8px 12px; border-radius: 9px; font-size: 13px;
  background: rgba(96, 165, 250, 0.08); border: 1px solid rgba(96, 165, 250, 0.22);
}

.items-table { width: 100%; }
.vcell { display: flex; align-items: center; gap: 9px; }
.thumb {
  width: 34px; height: 34px; border-radius: 8px; flex: none; font-size: 16px;
  display: inline-flex; align-items: center; justify-content: center;
  background: rgba(99, 102, 241, 0.14); border: 1px solid var(--mpau-border-soft);
}
.vmeta { min-width: 0; }
.vname { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vsize { font-size: 12px; }
.pcell { display: inline-flex; align-items: center; gap: 6px; }
.tcell { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
.ttext { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.warn-ico { flex: none; }

.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.video-list {
  border: 1px solid var(--mpau-border-soft); border-radius: 10px; overflow: hidden;
}
.vrow {
  display: flex; align-items: center; gap: 10px; padding: 8px 12px; font-size: 13px;
  border-bottom: 1px solid var(--mpau-border-soft);
}
.vrow:last-child { border-bottom: none; }
.vrow .vname { flex: 1; }
.hint { margin-top: 10px; font-size: 12.5px; line-height: 1.7; }

.empty-box { text-align: center; padding: 46px 0; }
.empty-ico { font-size: 34px; margin-bottom: 10px; }

.notes-card { padding: 14px 16px; }
.notes { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; color: var(--mpau-text-dim); line-height: 1.6; }
</style>
