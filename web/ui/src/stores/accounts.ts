import { defineStore } from 'pinia'
import { apiAccounts } from '../api'
import { PLATFORM_META } from './platforms'

interface PlatformAccounts { accounts: string[]; nicknames: Record<string, string> }

export const useAccountsStore = defineStore('accounts', {
  state: () => ({
    byPlatform: {} as Record<string, PlatformAccounts>,
    loading: false,
  }),
  getters: {
    /** 全平台已登录账号总数 */
    totalCount(state): number {
      return Object.values(state.byPlatform).reduce((n, p) => n + p.accounts.length, 0)
    },
    accountsOf(state) {
      return (platform: string): string[] => state.byPlatform[platform]?.accounts ?? []
    },
    nicknameOf(state) {
      return (platform: string, account: string): string =>
        state.byPlatform[platform]?.nicknames?.[account] ?? ''
    },
    hasAccount(state) {
      return (platform: string, account: string): boolean =>
        !!account && (state.byPlatform[platform]?.accounts ?? []).includes(account)
    },
  },
  actions: {
    async refresh(platform: string) {
      const resp = await apiAccounts(platform)
      this.byPlatform[platform] = { accounts: resp.accounts, nicknames: resp.nicknames || {} }
    },
    /** 全平台刷新(统计卡/账号映射用)，失败静默(账号接口不致命) */
    async refreshAll() {
      this.loading = true
      try {
        await Promise.allSettled(PLATFORM_META.map((p) => this.refresh(p.id)))
      } finally {
        this.loading = false
      }
    },
  },
})
