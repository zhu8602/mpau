<template>
  <div class="acc-card">
    <!-- 平台名 + 登录状态 -->
    <div class="card-head">
      <PlatformBadge :platform="platform" />
      <span class="pname">{{ platformCn(platform) }}</span>
      <span class="status" :class="{ on: accs.length }">
        <i class="dot" />{{ statusText }}
      </span>
    </div>

    <!-- 发布账号选择(多账号折叠为 +N, 不再垂直堆叠) -->
    <div class="sel-row">
      <el-select
        :model-value="store.mapping[platform] ?? []" size="small" class="acc-sel"
        multiple collapse-tags :max-collapse-tags="1"
        :placeholder="accs.length ? '选择发布账号' : '未登录'"
        :disabled="!accs.length"
        @change="(v: string[]) => onPick(v)"
      >
        <el-option v-for="a in accs" :key="a" :value="a" :label="accLabel(a)" />
      </el-select>
      <el-button
        v-if="accs.length"
        link type="primary" size="small" class="sel-all"
        :title="allSelected ? '取消选择该平台全部账号' : '选中该平台全部账号'"
        @click="onToggleAll"
      >{{ allSelected ? '取消' : '全选' }}</el-button>
    </div>

    <!-- 操作 -->
    <div class="card-foot">
      <el-button size="small" class="login-add" title="登录新账号(可多账号并存)" @click="ui.openLogin(platform)">
        ＋ 登录
      </el-button>
      <el-dropdown
        v-if="accs.length" trigger="click" size="small"
        @command="(cmd: string) => onAccCmd(cmd)"
      >
        <el-button size="small" class="manage-btn">管理<el-icon><ArrowDown /></el-icon></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="a in accs" :key="a" :command="`check:${a}`">
              ✓ 检查 {{ accLabel(a) }}
            </el-dropdown-item>
            <el-dropdown-item v-for="a in accs" :key="`out-${a}`" :command="`logout:${a}`" divided>
              ↪ 退出 {{ accLabel(a) }}
            </el-dropdown-item>
            <el-dropdown-item v-for="a in accs" :key="`log-${a}`" :command="`log:${a}`" divided>
              📋 日志 {{ accLabel(a) }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { apiCheckAccount, apiLogout } from '../../api'
import { useAccountsStore } from '../../stores/accounts'
import { useBatchStore } from '../../stores/batch'
import { useUiStore } from '../../stores/ui'
import { platformCn } from '../../stores/platforms'
import PlatformBadge from '../PlatformBadge.vue'

const props = defineProps<{ platform: string }>()

const store = useBatchStore()
const accounts = useAccountsStore()
const ui = useUiStore()

const accs = computed(() => accounts.accountsOf(props.platform))
const statusText = computed(() => {
  if (!accs.value.length) return '未登录'
  const sel = (store.mapping[props.platform] ?? []).length
  return sel ? `已登录 ${accs.value.length} · 已选 ${sel}` : `已登录 ${accs.value.length}`
})
/** 该平台全部账号是否已选中(据此切换「全选/取消」) */
const allSelected = computed(() => {
  const sel = store.mapping[props.platform] ?? []
  return accs.value.length > 0 && accs.value.every((a) => sel.includes(a))
})

function accLabel(account: string) {
  const nick = accounts.nicknameOf(props.platform, account)
  return nick ? `${account} · ${nick}` : account
}
function onPick(list: string[]) {
  store.mapping[props.platform] = list
}
/** 一键全选 / 取消该平台全部账号 */
function onToggleAll() {
  onPick(allSelected.value ? [] : [...accs.value])
}

/** 账号操作: check:账号 / logout:账号 / log:账号 */
async function onAccCmd(cmd: string) {
  const [op, account] = cmd.split(':')
  if (!account) return
  if (op === 'check') {
    try {
      const r = await apiCheckAccount(props.platform, account)
      if (r.valid) ElMessage.success(`✅ ${platformCn(props.platform)} ${account} 登录状态有效`)
      else ElMessage.warning(`⚠️ ${platformCn(props.platform)} ${account} 已失效，建议重新登录`)
    } catch { /* 拦截器已提示 */ }
  } else if (op === 'logout') {
    try {
      await ElMessageBox.confirm(
        `确定退出 ${platformCn(props.platform)} 账号「${account}」吗？将清除本地登录状态。`,
        '退出登录',
        { type: 'warning', confirmButtonText: '退出', cancelButtonText: '取消' },
      )
    } catch { return }
    try {
      await apiLogout(props.platform, account)
      await accounts.refresh(props.platform)
      ElMessage.success(`已退出 ${platformCn(props.platform)} ${account}`)
    } catch { /* 拦截器已提示 */ }
  } else if (op === 'log') {
    ui.openTaskLog(props.platform, account)
  }
}
</script>

<style scoped>
.acc-card {
  display: flex; flex-direction: column; gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--mpau-border-soft); border-radius: 10px;
  background: rgba(14, 20, 36, 0.45);
}
.card-head { display: flex; align-items: center; gap: 8px; }
.pname { font-size: 13px; font-weight: 600; }
.status {
  margin-left: auto; display: inline-flex; align-items: center; gap: 5px;
  font-size: 11.5px; color: var(--mpau-text-dim); white-space: nowrap;
}
.status .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--mpau-text-dim); }
.status.on { color: var(--mpau-ok); }
.status.on .dot { background: var(--mpau-ok); }

.acc-sel { width: 100%; }
.sel-row { display: flex; align-items: center; gap: 6px; }
.sel-all { flex: none; }

.card-foot { display: flex; justify-content: flex-end; gap: 6px; }
.login-add,
.manage-btn { flex: none; }
</style>
