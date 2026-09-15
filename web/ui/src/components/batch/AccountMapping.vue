<template>
  <div class="accmap">
    <div class="accmap-head">
      <span class="bm">📱 账号中心<span class="mpau-dim bm-sub">登录管理 + 发布账号映射，可多选账号多样发布</span></span>
      <span class="head-right">
        <span class="mpau-dim total">共 {{ accounts.totalCount }} 个已登录账号</span>
        <el-button link type="primary" size="small" class="more-toggle" @click="showMore = !showMore">
          {{ showMore ? '收起平台 ▴' : '更多平台 ▾' }}
        </el-button>
      </span>
    </div>
    <div class="acc-grid">
      <PlatformAccountCard v-for="p in visiblePlatforms" :key="p" :platform="p" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAccountsStore } from '../../stores/accounts'
import { useBatchStore } from '../../stores/batch'
import { MAPPING_MAIN, PLATFORM_META } from '../../stores/platforms'
import PlatformAccountCard from './PlatformAccountCard.vue'

const store = useBatchStore()
const accounts = useAccountsStore()

const showMore = ref(false)
const morePlatforms = computed(() => PLATFORM_META.map((p) => p.id).filter((id) => !MAPPING_MAIN.includes(id)))
const allPlatforms = computed(() => [...MAPPING_MAIN, ...morePlatforms.value])
const visiblePlatforms = computed(() => (showMore.value ? allPlatforms.value : MAPPING_MAIN))

/** 账号列表变化: 剔除已退出的账号; 默认全选该平台全部已登录账号(多账号多样发布) */
watch(
  () => accounts.byPlatform,
  () => {
    for (const p of allPlatforms.value) {
      const accs = accounts.accountsOf(p)
      const cur = store.mapping[p] ?? []
      const valid = cur.filter((a) => accs.includes(a))
      if (!(p in store.mapping)) store.mapping[p] = []
      if (!cur.length && accs.length) store.mapping[p] = [...accs]
      else if (valid.length !== cur.length) store.mapping[p] = valid
    }
  },
  { deep: true, immediate: true },
)
</script>

<style scoped>
.accmap {
  margin-top: 14px; padding: 14px 16px;
  border: 1px solid var(--mpau-border-soft); border-radius: 10px;
  background: rgba(14, 20, 36, 0.35);
}
.accmap-head {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 6px; margin-bottom: 12px;
}
.bm { font-size: 13px; font-weight: 600; color: var(--mpau-text); flex: none; }
.bm-sub { font-size: 11.5px; font-weight: 400; margin-left: 8px; }
.head-right { display: inline-flex; align-items: center; gap: 10px; }
.total { font-size: 12px; }
.more-toggle { font-size: 12.5px; }

.acc-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px;
}
@media (max-width: 760px) {
  .acc-grid { grid-template-columns: 1fr; }
}
</style>
