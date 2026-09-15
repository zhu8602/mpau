import { defineStore } from 'pinia'
import { apiTodayStats } from '../api'
import type { TodayStats } from '../api/types'

export const useStatsStore = defineStore('stats', {
  state: () => ({ today: null as TodayStats | null }),
  actions: {
    async loadToday() {
      this.today = await apiTodayStats()
    },
  },
})
