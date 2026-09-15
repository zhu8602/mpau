<template>
  <el-dialog
    v-model="visible" width="440px" append-to-body :close-on-click-modal="false"
    title="扫码登录"
  >
    <div class="body">
      <!-- 平台 -->
      <div class="plat-row">
        <PlatformBadge :platform="ui.login.platform" :size="26" />
        <b>{{ platformCn(ui.login.platform) }}</b>
      </div>

      <!-- 未启动: 账号名 + 无头模式 + 开始按钮 -->
      <template v-if="!loginTaskId">
        <el-input
          v-model="account" placeholder="输入账号名或昵称，留空自动分配"
          maxlength="40" @keyup.enter="start"
        />
        <el-checkbox v-model="headless">
          无头模式<span class="mpau-dim">(服务器模式：网页显示二维码)</span>
        </el-checkbox>
        <div v-if="loginError" class="login-err mpau-err">{{ loginError }}</div>
        <el-button class="mpau-btn-grad start-btn" :loading="starting" @click="start">
          {{ starting ? '正在启动…' : '开始登录' }}
        </el-button>
      </template>

      <!-- 已启动: 步骤条 + 二维码(无头) + 完成确认 + 友好状态 + 折叠技术日志 -->
      <template v-else>
        <div class="login-for">
          正在为 <b class="acct">{{ platformCn(ui.login.platform) }} · {{ loginAccount }}</b> 登录
        </div>

        <el-steps :active="stepActive" align-center class="login-steps">
          <el-step title="启动扫码环境" />
          <el-step title="手机扫码" />
          <el-step title="确认登录" />
        </el-steps>

        <div v-if="headless" class="qr-box">
          <img v-if="qrName" :src="qrUrl" alt="登录二维码" class="qr-img" />
          <div v-else class="qr-wait mpau-dim">等待二维码生成…</div>
          <div class="qr-foot">
            <span class="qr-name mpau-dim">{{ qrName }}</span>
            <el-button size="small" text @click="pollQr">
              <el-icon><Refresh /></el-icon>&nbsp;刷新二维码
            </el-button>
          </div>
        </div>
        <div v-else class="headed mpau-info">本机浏览器已打开，请在浏览器窗口中扫码</div>

        <div class="friendly-status">
          <span class="st-dot" />{{ friendlyStatus }}
        </div>

        <el-button type="primary" class="finish-btn" :loading="finishing" @click="finish">
          {{ finishing ? '正在校验 Cookie…' : '我已完成扫码' }}
        </el-button>

        <el-collapse v-if="taskLogLines.length" class="tech-log">
          <el-collapse-item title="技术日志（排查用）" name="log">
            <pre class="log-body">{{ taskLogLines.join('\n') }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>

      <div class="note mpau-dim">关闭弹窗不会取消登录任务；登录成功后账号列表自动刷新</div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { apiFinishLogin, apiLogin, apiQrcodes } from '../api'
import { platformCn } from '../stores/platforms'
import { useAccountsStore } from '../stores/accounts'
import { useTasksStore } from '../stores/tasks'
import { useUiStore } from '../stores/ui'
import PlatformBadge from './PlatformBadge.vue'

const ui = useUiStore()
const accounts = useAccountsStore()
const tasks = useTasksStore()

const visible = computed({
  get: () => ui.login.visible,
  set: (v: boolean) => { if (!v) ui.closeLogin() },
})

const account = ref('')
const headless = ref(false)
const starting = ref(false)
const finishing = ref(false)
const loginTaskId = ref('')
const loginAccount = ref('')
const loginError = ref('')

// 弹窗打开时带入 ui.login.account 并复位状态; 关闭只复位, 不取消后端登录任务(与旧版一致)
watch(() => ui.login.visible, (v) => {
  if (v) {
    account.value = ui.login.account
    headless.value = false
    loginError.value = ''
    loginTaskId.value = ''
    loginAccount.value = ''
    qrName.value = ''
    // 若该平台已有进行中的登录任务(上次关窗未取消), 直接接管其状态
    const running = tasks.tasks.find(
      (t) => t.kind === 'login' && t.platform === ui.login.platform && t.status === 'running',
    )
    if (running) {
      loginTaskId.value = running.id
      loginAccount.value = running.account
    }
  } else {
    stopQrTimer()
  }
})

/* ---------- 开始登录 ---------- */
async function start() {
  starting.value = true
  loginError.value = ''
  try {
    const t = await apiLogin(ui.login.platform, account.value.trim(), headless.value)
    loginTaskId.value = t.id
    loginAccount.value = t.account // 留空时后端自动分配账号名
    account.value = ''
    ElMessage.success(
      `登录已启动，账号 ${t.account}`
      + (headless.value ? '，二维码稍后生成' : '，本机浏览器将弹出扫码窗口'),
    )
    if (headless.value) {
      qrName.value = ''
      startQrTimer()
    }
    await tasks.refresh().catch(() => {})
  } catch { /* 拦截器已 toast */ } finally {
    starting.value = false
  }
}

/* ---------- 二维码轮询(无头模式) ---------- */
const qrName = ref('')
const qrTs = ref(0)
const qrUrl = computed(() => `/qrcodes/${encodeURIComponent(qrName.value)}?t=${qrTs.value}`)
let qrTimer: ReturnType<typeof setInterval> | undefined

function stopQrTimer() {
  if (qrTimer !== undefined) { clearInterval(qrTimer); qrTimer = undefined }
}
function startQrTimer() {
  stopQrTimer()
  setTimeout(pollQr, 1000) // 首次稍等后端落盘
  qrTimer = setInterval(pollQr, 3000)
}
async function pollQr() {
  try {
    const qrs = await apiQrcodes()
    // 多账号并发登录: 只取当前平台+账号的二维码, 避免拿到其他登录任务的码
    const mine = qrs.filter(
      (q) => q.platform === ui.login.platform && (!loginAccount.value || q.account === loginAccount.value),
    )
    if (mine.length) {
      qrName.value = mine[0]!.name
      qrTs.value = Date.now()
    }
  } catch { /* 轮询失败静默 */ }
}
onUnmounted(stopQrTimer)

/* ---------- 监控登录任务状态(全局 3s 轮询驱动) ---------- */
const loginTask = computed(() => {
  if (loginTaskId.value) return tasks.tasks.find((t) => t.id === loginTaskId.value)
  return tasks.tasks.find(
    (t) => t.kind === 'login' && t.platform === ui.login.platform && t.status === 'running',
  )
})
/** 原始日志(收进折叠面板, 仅供排查) */
const taskLogLines = computed(() => (loginTask.value?.log ?? []).slice(-20))

/** 步骤条: 启动后=等待扫码(第2步), 点"我已完成扫码"校验中=确认登录(第3步) */
const stepActive = computed(() => (finishing.value ? 2 : 1))

/** 面向用户的友好状态文案: 由最近日志关键词映射, 不暴露原始日志 */
const friendlyStatus = computed(() => {
  const lines = taskLogLines.value
  if (!lines.length) return headless.value ? '正在准备二维码，请稍候…' : '等待扫码…'
  const last = lines[lines.length - 1] || ''
  if (/二维码|qrcode/i.test(last)) return '二维码已生成，请用手机 App 扫码'
  if (/已扫码|scan/i.test(last)) return '已检测到扫码，请在手机上确认登录'
  if (/cookie|校验|保存/i.test(last)) return '正在保存登录状态…'
  if (/成功|success/i.test(last)) return '登录成功，正在收尾…'
  if (/失败|错误|超时|fail|error|timeout/i.test(last)) return '登录遇到问题，可展开下方技术日志查看详情'
  return '登录进行中…'
})

watch(() => loginTask.value?.status, async (st) => {
  if (!st || !loginTaskId.value) return
  if (st === 'success') {
    ElMessage.success(`✅ 登录成功: ${platformCn(ui.login.platform)} ${loginAccount.value}`)
    await accounts.refresh(ui.login.platform).catch(() => {})
    loginTaskId.value = ''
    ui.closeLogin()
  } else if (st === 'failed' || st === 'canceled') {
    if (st === 'failed') loginError.value = '❌ 登录失败，请重试；仍有问题可查看技术日志'
    loginTaskId.value = ''
    stopQrTimer()
  }
})

/* ---------- 我已完成扫码 ---------- */
async function finish() {
  const acc = loginAccount.value || account.value.trim()
  if (!acc) { ElMessage.warning('未知账号'); return }
  finishing.value = true
  try {
    const d = await apiFinishLogin(ui.login.platform, acc) as { ok?: boolean; message?: string }
    if (d.ok) {
      const plat = ui.login.platform
      ElMessage.success('✅ 登录成功，Cookie 已保存')
      await accounts.refresh(plat).catch(() => {})
      // 平台真实昵称由服务端后台异步抓取(几秒级), 延迟二次刷新把它带出来
      window.setTimeout(() => { accounts.refresh(plat).catch(() => {}) }, 8000)
      await tasks.refresh().catch(() => {})
      loginTaskId.value = ''
      ui.closeLogin()
    } else {
      ElMessage.warning(`⏳ ${d.message || 'Cookie 还未生效，请确认手机端已点确认'}`)
    }
  } catch { /* 拦截器已 toast */ } finally {
    finishing.value = false
  }
}
</script>

<style scoped>
.body { display: flex; flex-direction: column; gap: 14px; }
.plat-row { display: flex; align-items: center; gap: 10px; font-size: 15px; }
.start-btn { align-self: stretch; }
.login-for { font-size: 13px; color: var(--mpau-text-dim); }
.acct { color: var(--mpau-text); }

.login-steps { margin: 2px 0; }
.login-steps :deep(.el-step__title) { font-size: 12px; }

.qr-box {
  border: 1px dashed var(--mpau-border-soft); border-radius: 12px;
  padding: 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;
}
.qr-img { width: 220px; height: 220px; border-radius: 8px; background: #fff; }
.qr-wait { padding: 60px 0; font-size: 13px; }
.qr-foot { display: flex; align-items: center; gap: 10px; }
.qr-name { font-size: 11px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.headed { font-size: 13px; }
.finish-btn { align-self: stretch; }
.login-err { font-size: 12.5px; }
.note { font-size: 11.5px; }

.friendly-status {
  display: flex; align-items: center; gap: 7px;
  font-size: 12.5px; color: var(--mpau-text);
  padding: 8px 12px; border-radius: 8px;
  background: rgba(96, 165, 250, 0.08); border: 1px solid rgba(96, 165, 250, 0.18);
}
.st-dot {
  width: 7px; height: 7px; border-radius: 50%; flex: none;
  background: var(--mpau-info);
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 1; } }

.tech-log { border: none; --el-collapse-header-height: 34px; }
.tech-log :deep(.el-collapse-item__header) {
  background: transparent; border: none; color: var(--mpau-text-dim); font-size: 12px;
}
.tech-log :deep(.el-collapse-item__wrap) { background: transparent; border: none; }
.tech-log :deep(.el-collapse-item__content) { padding-bottom: 0; }
.log-body {
  margin: 0; max-height: 140px; overflow: auto;
  padding: 8px 10px; border: 1px solid var(--mpau-border-soft); border-radius: 8px;
  background: rgba(14, 20, 36, 0.55);
  font-size: 11.5px; line-height: 1.6; color: var(--mpau-text-dim);
  white-space: pre-wrap; word-break: break-all;
}
</style>
