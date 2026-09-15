<template>
  <el-dialog v-model="visible" width="680px" append-to-body title="⚙️ 设置（LLM 文案引擎 + 发布风控）">
    <div v-loading="loading" class="body">
      <!-- AI 文案引擎 -->
      <div class="sec">🤖 AI 文案引擎（OpenAI 兼容接口，推荐 DeepSeek）</div>
      <div class="grid2">
        <div class="field">
          <label>接口地址 base_url</label>
          <el-input v-model="form.base_url" placeholder="https://api.deepseek.com/v1" />
        </div>
        <div class="field">
          <label>模型名</label>
          <el-input v-model="form.model" placeholder="deepseek-chat" />
        </div>
        <div class="field">
          <label>API Key <span class="mpau-dim">(仅保存在本机 data/config.json)</span></label>
          <el-input
            v-model="form.api_key" type="password" show-password
            placeholder="留空保持不变"
          />
        </div>
        <div class="field">
          <label>每平台候选数 n_candidates</label>
          <el-input-number v-model="form.n_candidates" :min="1" :max="5" class="num" />
        </div>
        <div class="field">
          <label>超时（秒）</label>
          <el-input-number v-model="form.timeout" :min="10" :max="300" class="num" />
        </div>
        <div class="field">
          <label>max_tokens</label>
          <el-input-number v-model="form.max_tokens" :min="256" :max="8192" :step="256" class="num" />
        </div>
      </div>

      <!-- 发布风控 -->
      <div class="sec">🛡️ 发布风控</div>
      <div class="grid2">
        <div class="field">
          <label>条间最小间隔（分钟，1-60）</label>
          <el-input-number v-model="form.interval_min" :min="1" :max="60" class="num" />
        </div>
        <div class="field">
          <label>每账号每日上限（条，未设平台值的兜底）</label>
          <el-input-number v-model="form.daily_cap" :min="1" :max="100" class="num" />
        </div>
        <div class="field">
          <label>跨平台并发 max_concurrent（1-8）</label>
          <el-input-number v-model="form.max_concurrent" :min="1" :max="8" class="num" />
        </div>
      </div>

      <!-- 平台每日上限 -->
      <div class="sec">📊 平台每日上限（条/天，留空用上方兜底值）</div>
      <div class="grid2">
        <div v-for="p in CAP_PLATFORMS" :key="p.id" class="field">
          <label>{{ p.cn }}</label>
          <el-input-number
            v-model="caps[p.id]" :min="1" :max="100" class="num"
            placeholder="留空用兜底值" :value-on-clear="null"
          />
        </div>
      </div>

      <div class="note mpau-dim">
        · 没有 API Key 时无法生成文案，请到 platform.deepseek.com 申请（也可换成任意 OpenAI 兼容服务）<br>
        · 校验：抖音≤55字 / 快手≤55字 / 视频号短标题≤16字 / 小红书≤20字（硬性）+ 极限词提醒<br>
        · API Key 显示为掩码时，保存不会改变已保存的真实 Key
      </div>

      <div v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'err'">
        {{ testResult.ok ? '✅' : '❌' }} {{ testResult.message || (testResult.ok ? '连接成功' : '连接失败') }}
      </div>

      <div class="foot">
        <el-button :loading="store.testing" @click="test">
          <el-icon v-if="!store.testing"><Connection /></el-icon>&nbsp;测试连接
        </el-button>
        <el-button class="mpau-btn-grad" :loading="store.saving" @click="save">
          <el-icon v-if="!store.saving"><Check /></el-icon>&nbsp;保存
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Connection } from '@element-plus/icons-vue'
import type { Settings } from '../api/types'
import { useSettingsStore } from '../stores/settings'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
const store = useSettingsStore()

const visible = computed({
  get: () => ui.settingsVisible,
  set: (v: boolean) => { ui.settingsVisible = v },
})

const CAP_PLATFORMS = [
  { id: 'douyin', cn: '抖音' },
  { id: 'kuaishou', cn: '快手' },
  { id: 'xiaohongshu', cn: '小红书' },
  { id: 'tencent', cn: '视频号' },
] as const
type CapId = (typeof CAP_PLATFORMS)[number]['id']

const form = reactive({
  base_url: '',
  model: '',
  api_key: '',
  n_candidates: 3,
  timeout: 60,
  max_tokens: 1024,
  interval_min: 5,
  daily_cap: 25,
  max_concurrent: 4,
})
const caps = reactive<Record<CapId, number | null>>({
  douyin: null, kuaishou: null, xiaohongshu: null, tencent: null,
})
const loading = ref(false)
const testResult = ref<{ ok: boolean; message?: string } | null>(null)

// 打开时: store 为空则加载, 然后填充表单
watch(visible, async (v) => {
  if (!v) return
  testResult.value = null
  if (!store.settings) {
    loading.value = true
    try { await store.load() } catch { /* 拦截器已 toast */ } finally { loading.value = false }
  }
  if (store.settings) fillForm(store.settings)
})

function fillForm(s: Settings) {
  form.base_url = s.llm.base_url ?? ''
  form.model = s.llm.model ?? ''
  form.api_key = s.llm.api_key ?? '' // 后端返回掩码值
  form.n_candidates = s.llm.n_candidates || 3
  form.timeout = s.llm.timeout || 60
  form.max_tokens = s.llm.max_tokens || 1024
  form.interval_min = s.scheduler.interval_min || 5
  form.daily_cap = s.scheduler.daily_cap || 25
  form.max_concurrent = s.scheduler.max_concurrent || 4
  const pc = s.scheduler.platform_daily_caps || {}
  for (const p of CAP_PLATFORMS) {
    const v = pc[p.id]
    caps[p.id] = typeof v === 'number' && v > 0 ? v : null
  }
}

/** 深拷贝当前表单组装保存 payload; 掩码 Key 原样回传(后端识别 * 不覆盖真 Key) */
function buildPayload(): Settings {
  const platform_daily_caps: Record<string, number | null> = {}
  for (const p of CAP_PLATFORMS) {
    const v = caps[p.id]
    if (typeof v === 'number' && v > 0) platform_daily_caps[p.id] = Math.round(v)
  }
  return {
    llm: {
      ...(store.settings?.llm ?? { temperature: 0.7 }),
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      api_key: form.api_key.trim(),
      n_candidates: form.n_candidates || 3,
      timeout: form.timeout || 60,
      max_tokens: form.max_tokens || 1024,
    },
    scheduler: {
      ...(store.settings?.scheduler ?? {}),
      interval_min: form.interval_min || 5,
      daily_cap: form.daily_cap || 25,
      max_concurrent: form.max_concurrent || 4,
      platform_daily_caps,
    },
  }
}

async function save() {
  try {
    await store.save(buildPayload())
    ElMessage.success('✅ 设置已保存')
    ui.settingsVisible = false
  } catch { /* 拦截器已 toast */ }
}

async function test() {
  testResult.value = null
  try {
    testResult.value = await store.test()
  } catch { /* 拦截器已 toast */ }
}
</script>

<style scoped>
.body { display: flex; flex-direction: column; gap: 6px; }
.sec {
  font-size: 13px; font-weight: 700; margin-top: 10px;
  color: var(--mpau-text); border-left: 3px solid var(--mpau-primary); padding-left: 8px;
}
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; margin-top: 8px; }
.field label { display: block; font-size: 12px; color: var(--mpau-text-dim); margin-bottom: 4px; }
.num { width: 100%; }
.note { font-size: 12px; line-height: 1.9; margin-top: 10px; }
.test-result {
  border-radius: 8px; padding: 8px 12px; font-size: 12.5px; margin-top: 8px;
}
.test-result.ok { color: var(--mpau-ok); background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.3); }
.test-result.err { color: var(--mpau-err); background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.3); }
.foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
</style>
