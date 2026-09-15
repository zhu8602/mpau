<template>
  <header class="header">
    <div class="brand">
      <div class="logo">mp</div>
      <div>
        <div class="title">mpau · 电商多平台自动上传</div>
        <div class="subtitle">抖音 · 视频号 · 快手 · 小红书 · AI 文案 · 批量分发</div>
      </div>
    </div>
    <div class="right">
      <span class="status-pill"><i class="dot" />服务运行中 · {{ host }}</span>
      <el-button class="settings-btn" @click="openManual">
        <el-icon><Reading /></el-icon>&nbsp;使用手册
      </el-button>
      <el-button class="settings-btn" @click="ui.openSettings()">
        <el-icon><Setting /></el-icon>&nbsp;设置
      </el-button>
      <span class="clock">{{ now }}</span>
      <div class="admin">
        <el-avatar :size="30" class="avatar">A</el-avatar>
        <span>admin</span>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { Reading, Setting } from '@element-plus/icons-vue'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const host = window.location.host
function openManual() {
  window.open('/manual', '_blank')
}
const now = ref('')
function tick() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  now.value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
tick()
const timer = setInterval(tick, 1000)
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.header { display: flex; align-items: center; justify-content: space-between; padding: 14px 0 4px; }
.brand { display: flex; align-items: center; gap: 12px; }
.logo {
  width: 40px; height: 40px; border-radius: 11px; background: var(--mpau-grad);
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: 15px; color: #fff; box-shadow: 0 4px 18px rgba(99, 102, 241, 0.4);
}
.title { font-size: 16px; font-weight: 700; }
.subtitle { font-size: 12px; color: var(--mpau-text-dim); margin-top: 2px; }
.right { display: flex; align-items: center; gap: 16px; }
.status-pill {
  display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--mpau-text-dim);
  background: rgba(52, 211, 153, 0.08); border: 1px solid rgba(52, 211, 153, 0.25);
  padding: 6px 14px; border-radius: 999px;
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--mpau-ok); box-shadow: 0 0 8px var(--mpau-ok); }
.settings-btn { background: rgba(148, 163, 184, 0.08); border-color: var(--mpau-border-soft); color: var(--mpau-text); }
.clock { font-size: 13px; color: var(--mpau-text-dim); font-variant-numeric: tabular-nums; }
.admin { display: flex; align-items: center; gap: 8px; font-size: 13.5px; font-weight: 600; }
.avatar { background: var(--mpau-grad); font-size: 13px; }
</style>
