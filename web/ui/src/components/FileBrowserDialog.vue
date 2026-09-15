<template>
  <el-dialog
    :model-value="modelValue" width="640px" append-to-body
    :title="titleMap[mode]" @update:model-value="emit('update:modelValue', $event)" @open="onOpen"
  >
    <div class="fb">
      <div class="fb-bar">
        <el-select v-model="cwd" size="small" class="drive-sel" @change="load()">
          <el-option v-for="d in drives" :key="d.root" :value="d.root" :label="`${d.letter} 盘${d.free ? ` (剩余 ${fmtBytes(d.free)})` : ''}`" />
        </el-select>
        <el-input v-model="cwd" size="small" class="path-input" @keyup.enter="load()" />
        <el-button size="small" :disabled="!parent" @click="goUp">上级</el-button>
        <el-button size="small" @click="load()">刷新</el-button>
      </div>
      <div class="fb-list" v-loading="loading">
        <div
          v-for="e in entries" :key="e.name" class="fb-row"
          :class="{ pickable: pickable(e) }"
          @click="onRowClick(e)" @dblclick="onRowDblClick(e)"
        >
          <span class="icon">{{ e.dir ? '📁' : isVideo(e.name) ? '🎬' : '📄' }}</span>
          <span class="name">{{ e.name }}</span>
          <span class="size mpau-dim">{{ e.dir ? '' : fmtBytes(e.size ?? 0) }}</span>
        </div>
        <el-empty v-if="!loading && !entries.length" description="空目录" :image-size="60" />
      </div>
      <div class="fb-foot">
        <span class="sel mpau-dim">{{ selected || '未选择' }}</span>
        <el-button type="primary" :disabled="!canConfirm" @click="confirm">选择{{ mode === 'dir' ? '此文件夹' : '此文件' }}</el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { apiDrives, apiFiles } from '../api'
import type { Drive, FileEntry } from '../api/types'
import { fmtBytes } from '../utils/format'

const VIDEO_EXTS = ['.mp4', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.avi']

const props = withDefaults(defineProps<{
  modelValue: boolean
  /** video=选单个视频文件 dir=选文件夹 csv=选 CSV 文件 */
  mode: 'video' | 'dir' | 'csv'
  initialPath?: string
}>(), { initialPath: '' })

const emit = defineEmits<{
  'update:modelValue': [boolean]
  select: [string]
}>()

const titleMap = { video: '选择视频文件', dir: '选择文件夹', csv: '选择 CSV 文件' }

const drives = ref<Drive[]>([])
const cwd = ref('')
const parent = ref<string | null>(null)
const entries = ref<FileEntry[]>([])
const loading = ref(false)
const selected = ref('')

function isVideo(name: string) {
  return VIDEO_EXTS.some((ext) => name.toLowerCase().endsWith(ext))
}
function isCsv(name: string) {
  return name.toLowerCase().endsWith('.csv')
}
function joinPath(dir: string, name: string) {
  const sep = dir.includes('\\') ? '\\' : '/'
  return dir.endsWith('\\') || dir.endsWith('/') ? dir + name : dir + sep + name
}
/** 该条目是否可选为目标 */
function pickable(e: FileEntry) {
  if (props.mode === 'dir') return false  // 文件夹模式: 进入目录后点"选择此文件夹"
  if (e.dir) return false
  return props.mode === 'csv' ? isCsv(e.name) : isVideo(e.name)
}
const canConfirm = computed(() => (props.mode === 'dir' ? !!cwd.value : !!selected.value))

async function load() {
  if (!cwd.value) return
  loading.value = true
  selected.value = ''
  try {
    const resp = await apiFiles(cwd.value)
    cwd.value = resp.path
    parent.value = resp.parent
    entries.value = resp.entries
  } finally { loading.value = false }
}
function goUp() { if (parent.value) { cwd.value = parent.value; load() } }
function onRowClick(e: FileEntry) {
  if (pickable(e)) selected.value = joinPath(cwd.value, e.name)
}
function onRowDblClick(e: FileEntry) {
  if (e.dir) { cwd.value = joinPath(cwd.value, e.name); load() }
  else if (pickable(e)) { selected.value = joinPath(cwd.value, e.name); confirm() }
}
function confirm() {
  emit('select', props.mode === 'dir' ? cwd.value : selected.value)
  emit('update:modelValue', false)
}
async function onOpen() {
  selected.value = ''
  if (!drives.value.length) {
    try { drives.value = await apiDrives() } catch { /* 忽略 */ }
  }
  if (props.initialPath) cwd.value = props.initialPath
  if (!cwd.value) cwd.value = drives.value[0]?.root ?? 'D:\\videos'
  await load()
}
</script>

<style scoped>
.fb-bar { display: flex; gap: 8px; margin-bottom: 10px; }
.drive-sel { width: 170px; flex: none; }
.path-input { flex: 1; }
.fb-list {
  height: 320px; overflow-y: auto; border: 1px solid var(--mpau-border-soft);
  border-radius: 10px; padding: 4px;
}
.fb-row {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px;
  border-radius: 7px; font-size: 13px; cursor: default;
}
.fb-row:hover { background: rgba(99, 102, 241, 0.08); }
.fb-row.pickable { cursor: pointer; }
.fb-row .icon { width: 20px; text-align: center; }
.fb-row .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fb-row .size { font-size: 12px; }
.fb-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; gap: 10px; }
.sel { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px; }
</style>
