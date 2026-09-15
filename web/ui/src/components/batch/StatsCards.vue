<template>
  <div class="stats-row" :class="{ compact }">
    <div v-for="c in cards" :key="c.key" class="stat-card">
      <span class="ico" :style="{ background: c.bg, color: c.color }">{{ c.icon }}</span>
      <div class="meta">
        <div class="num" :style="{ color: c.color }">{{ store.stats[c.key] }}</div>
        <div class="label mpau-dim">{{ c.label }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useBatchStore } from '../../stores/batch'
import type { BatchStats } from '../../stores/batch'

defineProps<{ compact?: boolean }>()

const store = useBatchStore()

const cards: { key: keyof BatchStats; label: string; icon: string; color: string; bg: string }[] = [
  { key: 'scanned', label: '已扫描', icon: '📦', color: '#60a5fa', bg: 'rgba(96, 165, 250, 0.12)' },
  { key: 'pendingGen', label: '待生成文案', icon: '⏳', color: '#fb923c', bg: 'rgba(251, 146, 60, 0.12)' },
  { key: 'generated', label: '已生成', icon: '✨', color: '#34d399', bg: 'rgba(52, 211, 153, 0.12)' },
  { key: 'queued', label: '待发布', icon: '🚀', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.12)' },
  { key: 'success', label: '已成功', icon: '✅', color: '#22d3ee', bg: 'rgba(34, 211, 238, 0.12)' },
  { key: 'failed', label: '失败', icon: '❌', color: '#f87171', bg: 'rgba(248, 113, 113, 0.12)' },
]
</script>

<style scoped>
.stats-row {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-top: 14px;
}
.stat-card {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; border-radius: 10px;
  border: 1px solid var(--mpau-border-soft);
  background: rgba(14, 20, 36, 0.55);
}
.ico {
  width: 34px; height: 34px; border-radius: 9px; flex: none;
  display: inline-flex; align-items: center; justify-content: center; font-size: 16px;
}
.num { font-size: 22px; font-weight: 800; line-height: 1.1; font-variant-numeric: tabular-nums; }
.label { font-size: 12px; margin-top: 3px; }
@media (max-width: 1100px) {
  .stats-row { grid-template-columns: repeat(3, 1fr); }
}

/* 右栏紧凑模式: 2列网格 + 去顶部外边距 */
.stats-row.compact { grid-template-columns: repeat(2, 1fr); margin-top: 0; }
.stats-row.compact .stat-card { padding: 10px 12px; gap: 8px; }
.stats-row.compact .ico { width: 30px; height: 30px; font-size: 14px; }
.stats-row.compact .num { font-size: 19px; }
.stats-row.compact .label { font-size: 11.5px; margin-top: 2px; }
</style>
