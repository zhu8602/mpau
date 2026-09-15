import { defineStore } from 'pinia'
import { apiGetSettings, apiSaveSettings, apiTestSettings } from '../api'
import type { Settings } from '../api/types'

export const useSettingsStore = defineStore('settings', {
  state: () => ({ settings: null as Settings | null, saving: false, testing: false }),
  actions: {
    async load() {
      this.settings = await apiGetSettings()
    },
    async save(s: Settings) {
      this.saving = true
      try {
        await apiSaveSettings(s)
        this.settings = s
      } finally { this.saving = false }
    },
    async test() {
      this.testing = true
      try { return await apiTestSettings() } finally { this.testing = false }
    },
  },
})
