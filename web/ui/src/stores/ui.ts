import { defineStore } from 'pinia'

/** 全局 UI 状态：设置弹窗 / 扫码登录弹窗 / 任务日志抽屉(账号中心与任务队列共用) */
export const useUiStore = defineStore('ui', {
  state: () => ({
    settingsVisible: false,
    login: { visible: false, platform: 'douyin', account: '' },
    taskLog: { visible: false, platform: '', account: '' },
  }),
  actions: {
    openSettings() { this.settingsVisible = true },
    openLogin(platform: string, account = '') {
      this.login = { visible: true, platform, account }
    },
    closeLogin() { this.login.visible = false },
    openTaskLog(platform: string, account: string) {
      this.taskLog = { visible: true, platform, account }
    },
    closeTaskLog() { this.taskLog.visible = false },
  },
})
