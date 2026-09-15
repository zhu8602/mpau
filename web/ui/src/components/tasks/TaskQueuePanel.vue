<template>
  <div class="mpau-card tq-card">
    <h3 class="mpau-card-title">
      🧭 任务队列
      <span class="mpau-dim cnt">· {{ tasks.tasks.length }} 个任务</span>
      <el-button link type="primary" size="small" class="refresh" @click="onRefresh">刷新</el-button>
    </h3>

    <div v-if="running.length" class="list">
      <TaskRow v-for="t in running" :key="t.id" :task="t" @log="openLog" />
    </div>
    <div v-else class="empty mpau-dim">当前没有运行中的任务</div>

    <div v-if="tasks.tasks.length" class="foot">
      <el-button size="small" @click="allVisible = true">全部任务（{{ tasks.tasks.length }}）</el-button>
    </div>

    <el-drawer v-model="allVisible" title="全部任务" size="560px" append-to-body @open="onRefresh">
      <div v-if="tasks.sorted.length" class="list all-list">
        <TaskRow v-for="t in tasks.sorted.slice(0, 50)" :key="t.id" :task="t" @log="openLog" />
      </div>
      <div v-else class="empty mpau-dim">暂无任务</div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useTasksStore } from '../../stores/tasks'
import { useUiStore } from '../../stores/ui'
import type { Task } from '../../api/types'
import TaskRow from './TaskRow.vue'

const tasks = useTasksStore()
const ui = useUiStore()

const running = computed(() => tasks.sorted.filter((t) => t.status === 'running' || t.status === 'queued').slice(0, 6))
const allVisible = ref(false)

async function onRefresh() {
  try { await tasks.refresh() } catch { /* 拦截器已提示 */ }
}

function openLog(task: Task) {
  ui.openTaskLog(task.platform, task.account)
}
</script>

<style scoped>
.tq-card { padding: 14px 16px; }
.tq-card .mpau-card-title { margin: 0 0 10px; }
.cnt { font-size: 12px; font-weight: 400; margin-left: 6px; }
.refresh { margin-left: auto; }
.list { display: flex; flex-direction: column; gap: 8px; }
.all-list { max-height: 70vh; overflow: auto; }
.empty { padding: 16px 0; text-align: center; font-size: 12.5px; }
.foot { margin-top: 10px; text-align: right; }
</style>
