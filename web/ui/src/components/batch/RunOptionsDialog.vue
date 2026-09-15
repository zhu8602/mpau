<template>
  <el-dialog
    :model-value="modelValue" title="🚀 一键发布" width="640px" append-to-body
    @update:model-value="emit('update:modelValue', $event)" @open="onOpen"
  >
    <div class="tip mpau-dim">
      💡 一键发布 = 把「已批准」条目按顺序发出：没填定时时间的立即排队发出，填了定时时间的到点再发。条间间隔用于风控限速。
    </div>

    <div v-loading="quotaLoading" class="quota-box">
      <el-table v-if="rows.length" :data="rows" size="small" :row-class-name="rowClass">
        <el-table-column prop="cn" label="平台" min-width="110" />
        <el-table-column prop="approved" label="已批准" width="70" align="center" />
        <el-table-column label="今日已发" width="90" align="center">
          <template #default="{ row }">{{ row.published }}/{{ row.cap ?? '∞' }}</template>
        </el-table-column>
        <el-table-column prop="cap" label="上限" width="70" align="center">
          <template #default="{ row }">{{ row.cap ?? '∞' }}</template>
        </el-table-column>
        <el-table-column prop="remaining" label="剩余" width="70" align="center" />
        <el-table-column prop="will_publish" label="将发布" width="70" align="center" />
        <el-table-column label="将跳过" width="80" align="center">
          <template #default="{ row }">
            <span :class="{ 'mpau-err': row.will_skip > 0 }">{{ row.will_skip }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else-if="!quotaLoading" class="mpau-dim no-quota">暂无可发布条目（先在表格里批准文案）</div>
    </div>

    <div class="opts">
      <span class="lbl">条间间隔（分钟）</span>
      <el-input-number v-model="intervalMin" :min="1" :max="60" size="small" />
    </div>
    <div class="checks">
      <el-checkbox v-model="dryRun">试跑（填完不发布）</el-checkbox>
      <el-checkbox v-model="draft">视频号存草稿</el-checkbox>
      <el-checkbox v-model="headless">无头模式</el-checkbox>
      <el-checkbox v-model="force">忽略防重发</el-checkbox>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="store.starting" @click="onRun">🚀 立即发布</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Quota } from '../../api/types'
import { useBatchStore } from '../../stores/batch'
import { platformCn } from '../../stores/platforms'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; started: [] }>()

const store = useBatchStore()
const quota = ref<Quota | null>(null)
const quotaLoading = ref(false)
const intervalMin = ref(5)
const dryRun = ref(false)
const draft = ref(false)
const headless = ref(false)
const force = ref(false)

const rows = computed(() =>
  Object.entries(quota.value?.platforms ?? {}).map(([p, q]) => ({ platform: p, cn: platformCn(p), ...q })),
)
const totalSkip = computed(() => rows.value.reduce((a, r) => a + r.will_skip, 0))

function rowClass({ row }: { row: { will_skip: number } }) {
  return row.will_skip > 0 ? 'over-row' : ''
}

async function onOpen() {
  intervalMin.value = 5
  dryRun.value = false
  draft.value = false
  headless.value = false
  force.value = false
  quota.value = null
  quotaLoading.value = true
  try {
    quota.value = await store.quota()
  } catch {
    /* 拦截器已提示 */
  } finally {
    quotaLoading.value = false
  }
}

async function onRun() {
  if (totalSkip.value > 0) {
    try {
      await ElMessageBox.confirm(
        `⚠️ 有 ${totalSkip.value} 条将因今日平台上限被跳过（建议分批或调高上限）。仍要开始发布吗？`,
        '额度提醒',
        { type: 'warning', confirmButtonText: '仍要发布', cancelButtonText: '取消' },
      )
    } catch { return }
  }
  try {
    await store.run({
      interval_min: intervalMin.value,
      dry_run: dryRun.value,
      draft: draft.value,
      headless: headless.value,
      force: force.value,
    })
    ElMessage.success('🚀 批量发布已启动')
    emit('update:modelValue', false)
    emit('started')
  } catch {
    /* 拦截器已提示 */
  }
}
</script>

<style scoped>
.tip { font-size: 12.5px; line-height: 1.7; margin-bottom: 12px; }
.quota-box { min-height: 60px; margin-bottom: 14px; }
.no-quota { font-size: 12.5px; padding: 14px 0; text-align: center; }
.opts { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.lbl { font-size: 13px; color: var(--mpau-text-dim); }
.checks { display: flex; flex-wrap: wrap; gap: 4px 18px; }
:deep(.over-row) { color: var(--mpau-err); }
</style>
