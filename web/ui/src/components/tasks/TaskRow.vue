<template>
  <div class="task-row">
    <el-tag
      size="small" :type="statusMeta.type" :effect="statusMeta.color ? 'dark' : 'light'"
      :color="statusMeta.color" :style="statusMeta.color ? { color: '#fff', borderColor: 'transparent' } : undefined"
    >{{ statusMeta.text }}</el-tag>
    <PlatformBadge :platform="task.platform" :size="16" />
    <div class="tmeta">
      <div class="tlabel" :title="task.label">{{ task.label }}</div>
      <div class="tsub mpau-dim">
        {{ task.account }} · {{ fmtTime(task.created) }}
        <span v-if="taskNeedVerify(task)" class="mpau-warn"> · 需验证码</span>
        <span v-if="taskNeedManual(task)" class="mpau-warn"> · 需人工操作</span>
      </div>
    </div>
    <el-button link type="primary" size="small" class="log-btn" @click="emit('log', task)">
      日志
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { taskNeedManual, taskNeedVerify } from '../../stores/tasks'
import type { Task } from '../../api/types'
import { fmtTime } from '../../utils/format'
import PlatformBadge from '../PlatformBadge.vue'

const props = defineProps<{ task: Task }>()
const emit = defineEmits<{ log: [task: Task] }>()

type TagType = 'primary' | 'success' | 'warning' | 'danger' | 'info'
const STATUS_META: Record<string, { text: string; type: TagType; color?: string }> = {
  queued: { text: '排队中', type: 'info' },
  running: { text: '运行中', type: 'warning' },
  success: { text: '成功', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  canceled: { text: '已取消', type: 'info' },
  interrupted: { text: '已中断', type: 'info', color: '#8b5cf6' },
}
const statusMeta = computed(() => STATUS_META[props.task.status] ?? { text: props.task.status, type: 'info' as TagType })
</script>

<style scoped>
.task-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 8px;
  background: rgba(148, 163, 184, 0.05); border: 1px solid var(--mpau-border-soft);
}
.tmeta { flex: 1; min-width: 0; }
.tlabel {
  font-size: 12.5px; font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tsub { font-size: 11.5px; }
.log-btn { flex: none; }
</style>
