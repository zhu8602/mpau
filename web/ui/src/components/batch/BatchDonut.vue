<template>
  <div class="mpau-card donut-card">
    <h3 class="mpau-card-title">📊 批次统计</h3>
    <div class="donut-body">
      <div ref="chartEl" class="chart" />
      <ul class="legend">
        <li v-for="s in series" :key="s.label">
          <span class="dot" :style="{ background: s.color }" />
          <span class="lname">{{ s.label }}</span>
          <span class="lnum">{{ s.value }}</span>
          <span class="lpct mpau-dim">{{ s.pct }}%</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useBatchStore } from '../../stores/batch'

const store = useBatchStore()
const chartEl = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const defs = [
  { key: 'success', label: '已发布', color: '#34d399' },
  { key: 'queued', label: '待发布', color: '#fbbf24' },
  { key: 'generated', label: '已生成', color: '#60a5fa' },
  { key: 'pendingGen', label: '待生成', color: '#8b93ad' },
  { key: 'failed', label: '失败', color: '#f87171' },
] as const

const total = computed(() => store.stats.scanned)
const series = computed(() =>
  defs.map((d) => {
    const value = store.stats[d.key]
    const pct = total.value ? Math.round((value / total.value) * 100) : 0
    return { ...d, value, pct }
  }),
)

function render() {
  if (!chart) return
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    title: {
      text: String(total.value),
      subtext: '总数',
      left: 'center',
      top: '34%',
      textStyle: { color: '#e5e9f5', fontSize: 22, fontWeight: 800 },
      subtextStyle: { color: '#8b93ad', fontSize: 12 },
      itemGap: 2,
    },
    series: [
      {
        type: 'pie',
        radius: ['62%', '82%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: '#0e1424', borderWidth: 2, borderRadius: 4 },
        data: series.value.map((s) => ({ name: s.label, value: s.value, itemStyle: { color: s.color } })),
      },
    ],
  })
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    render()
  }
})
watch(series, render, { deep: true })
onUnmounted(() => {
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.donut-card { padding: 14px 16px; }
.donut-body { display: flex; align-items: center; gap: 8px; }
.chart { width: 150px; height: 150px; flex: none; }
.legend { list-style: none; margin: 0; padding: 0; flex: 1; display: flex; flex-direction: column; gap: 8px; }
.legend li { display: flex; align-items: center; gap: 7px; font-size: 12.5px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.lname { color: var(--mpau-text-dim); }
.lnum { margin-left: auto; font-weight: 700; font-variant-numeric: tabular-nums; }
.lpct { width: 38px; text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; }
</style>
