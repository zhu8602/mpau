<template>
  <span class="plat-badge" :style="{ background: meta.color }">{{ meta.glyph }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { platformMeta } from '../stores/platforms'

const props = defineProps<{ platform: string; size?: number }>()
const meta = computed(() => platformMeta(props.platform))
</script>

<style scoped>
.plat-badge {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 6px;
  color: #fff; font-size: 12px; font-weight: 700; flex: none;
  border: 1px solid rgba(255, 255, 255, 0.14);
}
</style>
