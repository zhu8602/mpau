import { defineStore } from 'pinia'
import {
  apiBatchAddVideo, apiBatchApprove, apiBatchBatches, apiBatchBriefGet, apiBatchBriefSet,
  apiBatchDelete, apiBatchGenerate, apiBatchGenProgress, apiBatchImport, apiBatchItemRegenerate,
  apiBatchItemRetry, apiBatchItems, apiBatchItemUpdate, apiBatchPlan,
  apiBatchQuota, apiBatchRun, apiBatchScan, apiBatchStatus, apiBatchStop, apiBatchVideos,
} from '../api'
import type { BatchInfo, BatchStatus, GenProgress, Item, Quota, Video } from '../api/types'
import { platformCn } from './platforms'

export interface BatchStats { scanned: number; pendingGen: number; generated: number; queued: number; success: number; failed: number }
export interface Warning { level: 'error' | 'warning' | 'info'; msg: string; time: string }

const DISMISS_KEY = 'mpau_dismissed_warnings'

function loadDismissedWarnings(): string[] {
  try { return JSON.parse(localStorage.getItem(DISMISS_KEY) || '[]') as string[] } catch { return [] }
}

export const useBatchStore = defineStore('batch', {
  state: () => ({
    batches: [] as BatchInfo[],
    batchId: '',
    videos: [] as Video[],
    items: [] as Item[],
    brief: '',
    /** 账号映射: platform -> 已选账号列表(多账号多样化发布) */
    mapping: {} as Record<string, string[]>,
    /** 已删除(忽略)的预警消息, 按 msg 持久化到 localStorage */
    dismissedWarnings: loadDismissedWarnings(),
    gen: { running: false, total: 0, done: 0, failed: 0, current: '', error: '' } as GenProgress & { failed: number; error: string },
    runStatus: null as BatchStatus | null,
    scanning: false,
    planning: false,
    generating: false,
    starting: false,
  }),
  getters: {
    itemsByVideo(state): Record<number, Item[]> {
      const m: Record<number, Item[]> = {}
      for (const it of state.items) (m[it.video_id] ||= []).push(it)
      return m
    },
    /**
     * 六张统计卡(视频粒度 rollup, 对齐设计稿):
     * 失败: 任一条目 failed/needs_manual; 待发布: 任一条目 approved/running;
     * 已成功: 全部条目 success/skipped 且至少一条 success;
     * 已生成: 有 draft 条目且已有候选文案; 其余为待生成文案。
     */
    stats(): BatchStats {
      const out: BatchStats = { scanned: this.videos.length, pendingGen: 0, generated: 0, queued: 0, success: 0, failed: 0 }
      for (const v of this.videos) {
        const its = this.itemsByVideo[v.id] ?? []
        if (!its.length) { out.pendingGen++; continue }
        if (its.some((i) => i.status === 'failed' || i.status === 'needs_manual')) out.failed++
        else if (its.some((i) => i.status === 'approved' || i.status === 'running')) out.queued++
        else if (its.every((i) => i.status === 'success' || i.status === 'skipped') && its.some((i) => i.status === 'success')) out.success++
        else if (its.some((i) => i.status === 'draft' && (i.candidates?.length || i.title))) out.generated++
        else out.pendingGen++
      }
      return out
    },
    /** 任务预警(客户端派生) */
    warnings(state): Warning[] {
      const list: Warning[] = []
      const now = new Date().toTimeString().slice(0, 8)
      for (const [p, acc] of Object.entries(state.mapping)) {
        if (!acc || !acc.length) list.push({ level: 'error', msg: `${platformCn(p)} 账号未登录，无法发布`, time: now })
      }
      const genFailed = state.items.filter((i) => i.status === 'needs_manual').length
      if (genFailed) list.push({ level: 'warning', msg: `${genFailed} 个视频生成失败，请检查后重试`, time: now })
      // 批内标题重复(按平台分组检测)
      const seen = new Map<string, number>()
      for (const i of state.items) {
        const t = (i.title || '').trim()
        if (!t) continue
        const key = `${i.platform}::${t}`
        seen.set(key, (seen.get(key) ?? 0) + 1)
      }
      const dupPlatforms = new Set<string>()
      for (const [key, n] of seen) if (n > 1) dupPlatforms.add(key.split('::')[0])
      for (const p of dupPlatforms) list.push({ level: 'warning', msg: `${platformCn(p)} 存在标题重复，建议优化`, time: now })
      const failed = state.items.filter((i) => i.status === 'failed').length
      if (failed) list.push({ level: 'error', msg: `${failed} 条发布失败，可在表格中重试`, time: now })
      return list.filter((w) => !state.dismissedWarnings.includes(w.msg))
    },
    approvedCount(state): number {
      return state.items.filter((i) => i.status === 'approved').length
    },
  },
  actions: {
    async loadBatches() {
      const resp = await apiBatchBatches()
      this.batches = resp.batches
      if (!this.batchId && resp.batches.length) {
        await this.selectBatch(resp.batches[0].batch_id)
      }
    },
    async selectBatch(id: string) {
      this.batchId = id
      this.runStatus = null
      await Promise.allSettled([this.loadVideos(), this.loadItems(), this.loadBrief(), this.loadStatus()])
    },
    /** 切到"新批次": 清空当前选择, 扫描/导入时由后端创建 */
    newBatch() {
      this.batchId = ''
      this.videos = []
      this.items = []
      this.brief = ''
      this.runStatus = null
    },
    /** 删除(忽略)单条预警, 按 msg 持久化; 同一情况再次出现时仍会重新出现(msg 变化) */
    dismissWarning(msg: string) {
      if (!this.dismissedWarnings.includes(msg)) {
        this.dismissedWarnings.push(msg)
        this.persistDismissedWarnings()
      }
    },
    /** 清空当前全部预警 */
    dismissAllWarnings() {
      for (const w of this.warnings) {
        if (!this.dismissedWarnings.includes(w.msg)) this.dismissedWarnings.push(w.msg)
      }
      this.persistDismissedWarnings()
    },
    persistDismissedWarnings() {
      if (this.dismissedWarnings.length > 100) {
        this.dismissedWarnings.splice(0, this.dismissedWarnings.length - 100)
      }
      try { localStorage.setItem(DISMISS_KEY, JSON.stringify(this.dismissedWarnings)) } catch { /* 隐私模式等场景忽略 */ }
    },
    async loadVideos() {
      if (!this.batchId) { this.videos = []; return }
      this.videos = (await apiBatchVideos(this.batchId)).videos
    },
    async loadItems() {
      if (!this.batchId) { this.items = []; return }
      this.items = (await apiBatchItems(this.batchId)).items
    },
    async loadBrief() {
      if (!this.batchId) { this.brief = ''; return }
      this.brief = (await apiBatchBriefGet(this.batchId)).brief
    },
    async saveBrief(text: string) {
      this.brief = text
      if (!this.batchId) return  // 先写后扫: 扫描时携带
      await apiBatchBriefSet(this.batchId, text)
    },
    async scan(dir: string) {
      this.scanning = true
      try {
        const resp = await apiBatchScan(dir, this.batchId || undefined)
        if (!this.batchId && this.brief) await apiBatchBriefSet(resp.batch_id, this.brief)
        this.batchId = resp.batch_id
        await Promise.allSettled([this.loadBatches(), this.loadVideos(), this.loadItems()])
        return resp
      } finally { this.scanning = false }
    },
    async importCsv(csv: string) {
      this.scanning = true
      try {
        const resp = await apiBatchImport(csv, this.batchId || undefined)
        if (!this.batchId && this.brief) await apiBatchBriefSet(resp.batch_id, this.brief)
        this.batchId = resp.batch_id
        await Promise.allSettled([this.loadBatches(), this.loadVideos(), this.loadItems()])
        return resp
      } finally { this.scanning = false }
    },
    /** 选择单条视频: 无批次自动新建, 已在本批次则 added=false(不重复登记)。 */
    async addVideo(path: string) {
      this.scanning = true
      try {
        const resp = await apiBatchAddVideo(path, this.batchId || undefined)
        if (!this.batchId && this.brief) await apiBatchBriefSet(resp.batch_id, this.brief)
        this.batchId = resp.batch_id
        await Promise.allSettled([this.loadBatches(), this.loadVideos(), this.loadItems()])
        return resp
      } finally { this.scanning = false }
    },
    async plan(platforms: string[]) {
      this.planning = true
      try {
        const accounts: Record<string, string[]> = {}
        for (const p of platforms) accounts[p] = this.mapping[p] ?? []
        const r = await apiBatchPlan({ batch_id: this.batchId, platforms, accounts })
        await this.loadItems()
        return r
      } finally { this.planning = false }
    },
    /** 一键生成: 无条目时先按映射平台 plan, 再 generate, 并启动 2s 进度轮询 */
    async generateAll(withDesc: boolean, withTags: boolean, withGoodsTitle = false) {
      if (!this.items.length) {
        const platforms = Object.keys(this.mapping).filter((p) => (this.mapping[p] ?? []).length)
        await this.plan(platforms.length ? platforms : Object.keys(this.mapping))
      }
      this.generating = true
      try {
        await apiBatchGenerate({
          batch_id: this.batchId, with_desc: withDesc, with_tags: withTags,
          with_goods_title: withGoodsTitle, brief: this.brief,
        })
      } finally { this.generating = false }
    },
    async pollGenOnce(): Promise<boolean> {
      /** 返回是否仍在运行 */
      if (!this.batchId) return false
      const info = await apiBatchGenProgress(this.batchId)
      this.gen = info
      if (!info.running) await this.loadItems()
      return !!info.running
    },
    async loadStatus() {
      if (!this.batchId) { this.runStatus = null; return }
      this.runStatus = await apiBatchStatus(this.batchId)
      // 调度结束后同步一次条目, 让表格状态/环图收尾
      if (this.runStatus && !this.runStatus.scheduler.alive) await this.loadItems()
    },
    async updateItem(id: number, fields: Record<string, unknown>) {
      await apiBatchItemUpdate(id, fields)
      await this.loadItems()
    },
    async regenerate(id: number) {
      await apiBatchItemRegenerate(id)
      await this.loadItems()
    },
    async retry(id: number) {
      await apiBatchItemRetry(id)
      await Promise.allSettled([this.loadItems(), this.loadStatus()])
    },
    async approve(itemIds?: number[], approved = true) {
      const r = await apiBatchApprove(this.batchId, itemIds, approved)
      await this.loadItems()
      return r
    },
    async quota(): Promise<Quota> {
      return apiBatchQuota(this.batchId)
    },
    async run(opts: { interval_min: number; dry_run: boolean; draft: boolean; headless: boolean; force: boolean }) {
      this.starting = true
      try {
        const r = await apiBatchRun({ batch_id: this.batchId, ...opts })
        await this.loadStatus()
        return r
      } finally { this.starting = false }
    },
    async stop() {
      await apiBatchStop(this.batchId)
      await this.loadStatus()
    },
    async removeBatch() {
      await apiBatchDelete(this.batchId)
      this.newBatch()
      await this.loadBatches()
    },
  },
})
