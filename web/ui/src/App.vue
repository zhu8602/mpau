<template>
  <div class="layout">
    <AppHeader />
    <main class="main">
      <RouterView />
    </main>
    <SettingsDialog />
    <QrLoginDialog />
    <TaskLogDrawer />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import AppHeader from './components/AppHeader.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import QrLoginDialog from './components/QrLoginDialog.vue'
import TaskLogDrawer from './components/tasks/TaskLogDrawer.vue'
import { usePlatformsStore } from './stores/platforms'
import { useAccountsStore } from './stores/accounts'
import { useTasksStore } from './stores/tasks'
import { useStatsStore } from './stores/stats'
import { usePolling } from './utils/polling'

const platforms = usePlatformsStore()
const accounts = useAccountsStore()
const tasks = useTasksStore()
const stats = useStatsStore()

onMounted(() => {
  platforms.load()
  accounts.refreshAll()
  stats.loadToday()
})

// 全局轮询：任务 3s / 账号 60s / 今日数据 30s
usePolling(() => tasks.refresh().catch(() => {}), 3000)
usePolling(() => accounts.refreshAll().catch(() => {}), 60000)
usePolling(() => stats.loadToday().catch(() => {}), 30000)
</script>

<style scoped>
.layout { max-width: 1760px; margin: 0 auto; padding: 0 20px 32px; }
.main { min-height: 60vh; }
</style>
