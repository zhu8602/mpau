<template>
  <el-drawer
    :model-value="modelValue" title="编辑条目" size="440px"
    @update:model-value="emit('update:modelValue', $event)" @open="fill"
  >
    <el-form v-if="item" label-position="top" class="edit-form">
      <div class="ctx mpau-dim">
        <PlatformBadge :platform="item.platform" />
        <span>{{ item.platform_cn }}</span>
        <span class="vname">· {{ fileName(item.video_path) }}</span>
      </div>
      <el-form-item label="标题">
        <el-input v-model="form.title" maxlength="100" show-word-limit placeholder="标题" />
      </el-form-item>
      <el-form-item v-if="caps.desc" label="描述">
        <el-input v-model="form.desc" type="textarea" :rows="4" maxlength="1000" placeholder="描述" />
      </el-form-item>
      <el-form-item label="标签（逗号分隔）">
        <el-input v-model="form.tags" placeholder="标签,逗号分隔" />
      </el-form-item>
      <el-form-item label="定时发布时间">
        <el-date-picker
          v-model="form.schedule" type="datetime" placeholder="留空则立即排队"
          format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DD HH:mm" class="sched"
        />
      </el-form-item>
      <template v-if="caps.goods">
        <el-divider content-position="left">商品信息（选填）</el-divider>
        <template v-if="caps.goodsKind === 'product'">
          <el-form-item label="商品链接">
            <el-input v-model="form.g_link" placeholder="商品链接" />
          </el-form-item>
          <el-form-item label="商品短标题">
            <el-input v-model="form.g_title" placeholder="商品短标题" />
          </el-form-item>
        </template>
        <el-form-item v-else-if="caps.goodsKind === 'goods_name'">
          <template #label>
            商品名称（快手挂车）
            <el-tooltip placement="top" content="快手只支持按商品名称关联。请粘贴快手小店里该商品的完整名称（需与店里一致才能搜到）。只作用于本条(当前平台+账号)。">
              <el-icon class="scope-ico"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <el-input
            v-model="form.g_name"
            type="textarea" :rows="2" maxlength="120" show-word-limit
            placeholder="粘贴快手小店里的完整商品名称，发布时按名称搜索并关联"
          />
        </el-form-item>
        <el-form-item v-else>
          <template #label>
            商品ID
            <el-tooltip placement="top" content="只作用于本条(当前平台+账号)。同一视频发到不同平台/账号时，各自填各自的商品ID，互不影响。">
              <el-icon class="scope-ico"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <el-input v-model="form.g_id" placeholder="商品ID（仅本条目生效）" />
        </el-form-item>
      </template>
      <div class="form-actions">
        <el-button @click="emit('update:modelValue', false)">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
    </el-form>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import type { Item } from '../../api/types'
import { useBatchStore } from '../../stores/batch'
import { platformCaps } from '../../stores/platforms'
import { fileName } from '../../utils/format'
import PlatformBadge from '../PlatformBadge.vue'

const props = defineProps<{ modelValue: boolean; item: Item | null }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const store = useBatchStore()
/** 按平台能力显示字段: TikTok 无描述/无商品; 抖音是商品链接, 其余电商平台是商品ID */
const caps = computed(() => platformCaps(props.item?.platform ?? ''))
const saving = ref(false)
const form = reactive({
  title: '', desc: '', tags: '', schedule: '',
  g_link: '', g_title: '', g_id: '', g_name: '',
})
/** 打开时的原始值快照: 保存时只提交真正改动过的字段 */
const origin = reactive({ ...form })

function fill() {
  const it = props.item
  if (!it) return
  form.title = it.title || ''
  form.desc = it.desc || ''
  form.tags = it.tags || ''
  form.schedule = it.schedule || ''
  let g: Record<string, string> = {}
  try { g = JSON.parse(it.goods_json || '{}') } catch { g = {} }
  form.g_link = g.link || ''
  form.g_title = g.title || ''
  form.g_id = g.id || ''
  form.g_name = g.name || ''
  Object.assign(origin, form)
}

async function save() {
  if (!props.item) return
  saving.value = true
  try {
    // 只提交改动过的字段: 避免未触碰商品时也带上 g_* 键而误触商品分支
    const payload: Record<string, unknown> = {}
    if (form.title.trim() !== origin.title) payload.title = form.title.trim()
    if (form.desc.trim() !== origin.desc) payload.desc = form.desc.trim()
    if (form.tags.trim() !== origin.tags) payload.tags = form.tags.trim()
    if (form.schedule !== origin.schedule) payload.schedule = form.schedule || ''
    if (form.g_link.trim() !== origin.g_link) payload.g_link = form.g_link.trim()
    if (form.g_title.trim() !== origin.g_title) payload.g_title = form.g_title.trim()
    if (form.g_id.trim() !== origin.g_id) payload.g_id = form.g_id.trim()
    if (form.g_name.trim() !== origin.g_name) payload.g_name = form.g_name.trim()
    if (!Object.keys(payload).length) {
      emit('update:modelValue', false)
      return
    }
    await store.updateItem(props.item.id, payload)
    const goodsTouched = 'g_link' in payload || 'g_title' in payload || 'g_id' in payload || 'g_name' in payload
    ElMessage.success(goodsTouched ? '✅ 已保存（商品ID/商品名称只作用于本条）' : '✅ 已保存')
    emit('update:modelValue', false)
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.edit-form :deep(.el-form-item__label) { color: var(--mpau-text-dim); }
.edit-form :deep(.el-form-item) { margin-bottom: 14px; }
.ctx { display: flex; align-items: center; gap: 6px; font-size: 12.5px; margin-bottom: 12px; }
.vname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sched { width: 100%; }

/* 商品ID 作用域提示图标 */
.scope-ico {
  margin-left: 4px; font-size: 13px; color: var(--mpau-text-dim);
  vertical-align: -2px; cursor: help;
}

/* 操作按钮紧跟表单末尾, 右对齐 */
.form-actions {
  display: flex; justify-content: flex-end; gap: 8px;
  margin-top: 4px; padding-top: 12px;
  border-top: 1px solid var(--mpau-border-soft);
}
</style>
