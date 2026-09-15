import { defineStore } from 'pinia'
import { apiCancelTask, apiTasks, apiVerify } from '../api'
import type { Task } from '../api/types'

/** 日志行里的验证码/人工操作标记(与后端约定) */
export const VERIFY_FLAG = '[VERIFY_REQUIRED]'
export const MANUAL_FLAG = '[MANUAL_ACTION]'

export function taskNeedVerify(t: Task): boolean {
  return t.status === 'running' && t.log.some((l) => l.includes(VERIFY_FLAG))
}
export function taskNeedManual(t: Task): boolean {
  return t.status === 'running' && t.log.some((l) => l.includes(MANUAL_FLAG))
}

export const useTasksStore = defineStore('tasks', {
  state: () => ({ tasks: [] as Task[] }),
  getters: {
    runningCount: (s) => s.tasks.filter((t) => t.status === 'running').length,
    successCount: (s) => s.tasks.filter((t) => t.status === 'success').length,
    sorted(s): Task[] {
      return [...s.tasks].sort((a, b) => (b.created || '').localeCompare(a.created || ''))
    },
  },
  actions: {
    async refresh() {
      const resp = await apiTasks()
      this.tasks = resp.tasks
    },
    async cancel(id: string) {
      await apiCancelTask(id)
      await this.refresh()
    },
    async submitVerify(platform: string, account: string, code: string) {
      await apiVerify(platform, account, code)
    },
  },
})
