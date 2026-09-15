<template>
  <el-drawer
    v-model="visible" :title="drawerTitle" size="560px" append-to-body
    @open="onOpen"
  >
    <div v-if="!task" class="empty mpau-dim">
      没有找到 {{ platformCn(ui.taskLog.platform) }} 账号「{{ ui.taskLog.account }}」的任务记录
    </div>
    <template v-else>
      <div class="head">
        <el-tag size="small" :type="statusMeta.type">{{ statusMeta.text }}</el-tag>
        <span class="mpau-dim">{{ task.kind === 'login' ? '登录' : task.kind === 'batch-upload' ? '批量发布' : '发布' }}任务
          · {{ task.label }}
        </span>
      </div>

      <div v-if="taskNeedVerify(task)" class="verify-box">
        <div class="mpau-warn">⚠️ 平台要求短信验证码，请输入后提交：</div>
        <div class="verify-row">
          <el-input v-model="verifyCode" placeholder="短信验证码" maxlength="8" class="vc" @keyup.enter="onVerify" />
          <el-button type="primary" :loading="verifying" @click="onVerify">提交验证码</el-button>
        </div>
      </div>
      <div v-else-if="taskNeedManual(task)" class="manual-box mpau-warn">
        ⚠️ 需要人工操作：请查看日志最后几行的指引（如平台弹窗、滑块验证）。
      </div>

      <div v-if="task.status === 'running' || task.status === 'queued'" class="head">
        <el-button size="small" type="danger" plain @click="onCancel">🛑 取消任务</el-button>
      </div>

      <div class="log-title mpau-dim">任务日志（{{ logLines.length }} 行）</div>
      <pre class="log-body">{{ logLines.join('\n') || '（暂无日志输出）' }}</pre>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { taskNeedManual, taskNeedVerify, useTasksStore } from '../../stores/tasks'
import { useUiStore } from '../../stores/ui'
import { platformCn } from '../../stores/platforms'
import type { Task } from '../../api/types'

const ui = useUiStore()
const tasks = useTasksStore()

const visible = computed({
  get: () => ui.taskLog.visible,
  set: (v: boolean) => { if (!v) ui.closeTaskLog() },
})

/** 该平台+账号的最新任务(sorted 按 created 降序) */
const task = computed<Task | null>(() =>
  tasks.sorted.find(
    (t) => t.platform === ui.taskLog.platform && t.account === ui.taskLog.account,
  ) ?? null,
)
const logLines = computed(() => task.value?.log ?? [])
const drawerTitle = computed(() =>
  `任务日志 · ${platformCn(ui.taskLog.platform)} · ${ui.taskLog.account}`,
)

type TagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'
const STATUS_META: Record<string, { text: string; type: TagType }> = {
  queued: { text: '排队中', type: 'info' },
  running: { text: '运行中', type: 'warning' },
  success: { text: '成功', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  canceled: { text: '已取消', type: 'info' },
  interrupted: { text: '已中断', type: 'info' },
}
const statusMeta = computed(() => STATUS_META[task.value?.status ?? ''] ?? { text: '-', type: 'info' as TagType })

const verifyCode = ref('')
const verifying = ref(false)
function onOpen() {
  verifyCode.value = ''
  void tasks.refresh().catch(() => {})
}

async function onVerify() {
  if (!task.value) return
  const code = verifyCode.value.trim()
  if (!code) { ElMessage.warning('请输入短信验证码'); return }
  verifying.value = true
  try {
    await tasks.submitVerify(task.value.platform, task.value.account, code)
    ElMessage.success('✅ 验证码已提交，等待平台校验')
    verifyCode.value = ''
    void tasks.refresh().catch(() => {})
  } catch { /* 拦截器已提示 */ } finally {
    verifying.value = false
  }
}

async function onCancel() {
  if (!task.value) return
  try {
    await ElMessageBox.confirm('确定取消该任务吗？', '取消任务', {
      type: 'warning', confirmButtonText: '取消任务', cancelButtonText: '返回',
    })
  } catch { return }
  try {
    await tasks.cancel(task.value.id)
    ElMessage.info('任务已取消')
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.empty { padding: 30px 0; text-align: center; }
.verify-box {
  margin-bottom: 12px; padding: 10px 12px; border-radius: 8px;
  background: rgba(250, 204, 21, 0.08); border: 1px solid rgba(250, 204, 21, 0.3);
}
.verify-row { display: flex; gap: 8px; margin-top: 8px; }
.vc { flex: 1; }
.manual-box {
  margin-bottom: 12px; padding: 10px 12px; border-radius: 8px;
  background: rgba(250, 204, 21, 0.08); border: 1px solid rgba(250, 204, 21, 0.3);
  font-size: 12.5px;
}
.log-title { font-size: 12px; margin: 10px 0 6px; }
.log-body {
  margin: 0; padding: 10px 12px; border-radius: 8px;
  background: rgba(14, 20, 36, 0.55); border: 1px solid var(--mpau-border-soft);
  font-size: 12px; line-height: 1.7; color: var(--mpau-text-dim);
  white-space: pre-wrap; word-break: break-all; max-height: 60vh; overflow: auto;
}
</style>
