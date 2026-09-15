<template>
  <el-dialog
    :model-value="modelValue" title="文案预览" width="560px" append-to-body
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="item" class="preview">
      <div class="head">
        <PlatformBadge :platform="item.platform" />
        <b>{{ item.platform_cn }}</b>
        <span class="mpau-dim vname">{{ fileName(item.video_path) }}</span>
      </div>

      <template v-if="candidates.length">
        <div class="cand-switch">
          <span class="mpau-dim">候选文案：</span>
          <el-radio-group v-model="idx" size="small">
            <el-radio-button v-for="(_, i) in candidates" :key="i" :value="i">候选 {{ i + 1 }}</el-radio-button>
          </el-radio-group>
        </div>
        <div v-if="cur" class="cand">
          <div class="field"><span class="k">标题</span><span class="v">{{ cur.title || '-' }}</span></div>
          <div class="field"><span class="k">描述</span><span class="v desc">{{ cur.desc || '-' }}</span></div>
          <div class="field"><span class="k">标签</span><span class="v">{{ cur.tags?.length ? cur.tags.join('，') : '-' }}</span></div>
          <div v-if="cur.short_title" class="field"><span class="k">短标题</span><span class="v">{{ cur.short_title }}</span></div>
          <div v-if="cur.issues?.length" class="issues">
            <div v-for="(is, i) in cur.issues" :key="i" :class="is.level === 'error' ? 'mpau-err' : 'mpau-warn'">
              {{ is.level === 'error' ? '⛔' : '⚠️' }} {{ is.msg }}
            </div>
          </div>
        </div>
      </template>
      <el-empty v-else description="还没有候选文案" :image-size="60" />

      <el-divider content-position="left">当前采用</el-divider>
      <div class="field"><span class="k">标题</span><span class="v">{{ item.title || '-' }}</span></div>
      <div class="field"><span class="k">描述</span><span class="v desc">{{ item.desc || '-' }}</span></div>
      <div class="field"><span class="k">标签</span><span class="v">{{ item.tags || '-' }}</span></div>
      <div v-if="goods.id || goods.link || goods.title || goods.name" class="goods-box">
        <div class="goods-head mpau-dim">商品信息（本条）</div>
        <div v-if="goods.link" class="field"><span class="k">链接</span><span class="v">{{ goods.link }}</span></div>
        <div v-if="goods.title" class="field"><span class="k">短标题</span><span class="v">{{ goods.title }}</span></div>
        <div v-if="goods.id" class="field"><span class="k">商品ID</span><span class="v">{{ goods.id }}</span></div>
        <div v-if="goods.name" class="field"><span class="k">商品名</span><span class="v">{{ goods.name }}</span></div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Item } from '../../api/types'
import { fileName } from '../../utils/format'
import PlatformBadge from '../PlatformBadge.vue'

const props = defineProps<{ modelValue: boolean; item: Item | null }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const idx = ref(0)
const candidates = computed(() => props.item?.candidates ?? [])
const cur = computed(() => candidates.value[idx.value] ?? candidates.value[0])

/** 本条目的商品信息(商品ID是条目级: 不同平台/账号各自持有) */
const goods = computed<{ link?: string; title?: string; id?: string; name?: string }>(() => {
  try { return JSON.parse(props.item?.goods_json || '{}') } catch { return {} }
})

watch(
  () => props.item?.id,
  () => { idx.value = 0 },
)
</script>

<style scoped>
.head { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.vname { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cand-switch { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 12.5px; }
.cand {
  border: 1px solid var(--mpau-border-soft); border-radius: 10px;
  padding: 10px 12px; background: rgba(99, 102, 241, 0.05);
}
.field { display: flex; gap: 10px; padding: 4px 0; font-size: 13px; }
.k { flex: none; width: 44px; color: var(--mpau-text-dim); }
.v { flex: 1; word-break: break-all; }
.desc { white-space: pre-wrap; }
.issues { margin-top: 8px; font-size: 12.5px; display: flex; flex-direction: column; gap: 3px; }
.goods-box {
  margin-top: 10px; padding: 8px 10px; border-radius: 9px;
  border: 1px solid var(--mpau-border-soft); background: rgba(148, 163, 184, 0.05);
}
.goods-head { font-size: 12px; margin-bottom: 4px; }
</style>
