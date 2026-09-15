<template>
  <div class="mpau-card warn-card">
    <h3 class="mpau-card-title">⚠️ 任务预警</h3>
    <div v-if="store.warnings.length" class="list">
      <div v-for="(w, i) in store.warnings" :key="i" class="row">
        <span class="dot" :style="{ background: colorOf(w.level) }" />
        <span class="msg">{{ w.msg }}</span>
        <span class="time mpau-dim">{{ w.time }}</span>
        <el-icon class="del" title="删除该预警" @click="store.dismissWarning(w.msg)"><Close /></el-icon>
      </div>
    </div>
    <div v-else class="empty mpau-dim">暂无预警</div>
    <div v-if="store.warnings.length" class="foot">
      <a class="more-link" @click.prevent="store.dismissAllWarnings()">清空预警</a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Close } from '@element-plus/icons-vue'
import { useBatchStore } from '../../stores/batch'

const store = useBatchStore()

function colorOf(level: string) {
  if (level === 'error') return 'var(--mpau-err)'
  if (level === 'warning') return 'var(--mpau-warn)'
  return 'var(--mpau-info)'
}
</script>

<style scoped>
.warn-card { padding: 14px 16px; }
.list { display: flex; flex-direction: column; gap: 9px; }
.row { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; line-height: 1.5; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex: none; margin-top: 5px; }
.msg { flex: 1; }
.time { flex: none; font-size: 11.5px; font-variant-numeric: tabular-nums; }
.del {
  flex: none; margin-top: 2px; cursor: pointer; font-size: 12px;
  color: var(--mpau-text-dim); border-radius: 4px; padding: 1px;
}
.del:hover { color: var(--mpau-err); background: rgba(248, 113, 113, 0.12); }
.empty { font-size: 12.5px; padding: 10px 0; text-align: center; }
.foot { margin-top: 10px; border-top: 1px solid var(--mpau-border-soft); padding-top: 8px; text-align: right; }
.more-link { font-size: 12.5px; color: var(--mpau-info); cursor: pointer; text-decoration: none; }
</style>
