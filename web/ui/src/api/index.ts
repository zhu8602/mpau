import { get, post } from './http'
import type {
  AccountsResp, BatchInfo, BatchStatus, CopyGenerateResp, CopyRules, Drive, FilesResp,
  GenProgress, Item, PlatformInfo, QrCode, Quota, Settings, Task, TodayStats, Video,
} from './types'

// ---------------- 平台 / 账号 ----------------
export const apiPlatforms = () => get<PlatformInfo[]>('/api/platforms')
export const apiAccounts = (platform: string) => get<AccountsResp>('/api/accounts', { platform })
export const apiLogin = (platform: string, account: string, headless: boolean) =>
  post<{ id: string; account: string }>('/api/accounts/login', { platform, account, headless })
export const apiCheckAccount = (platform: string, account: string) =>
  post<{ valid: boolean | null; output: string }>('/api/accounts/check', { platform, account })
export const apiFinishLogin = (platform: string, account: string) =>
  post('/api/accounts/finish-login', { platform, account })
export const apiLogout = (platform: string, account: string) =>
  post('/api/accounts/logout', { platform, account })
export const apiVerify = (platform: string, account: string, code: string) =>
  post('/api/verify', { platform, account, code })
export const apiQrcodes = () => get<QrCode[]>('/api/qrcodes')

// ---------------- 任务 ----------------
export const apiTasks = () => get<{ tasks: Task[] }>('/api/tasks')
export const apiCreateTask = (payload: Record<string, unknown>) => post<{ id: string }>('/api/tasks', payload)
export const apiCancelTask = (id: string) => post(`/api/tasks/${encodeURIComponent(id)}/cancel`)

// ---------------- 文件浏览 ----------------
export const apiDrives = () => get<Drive[]>('/api/drives')
export const apiFiles = (path: string) => get<FilesResp>('/api/files', { path })

// ---------------- 统计 / 设置 / 文案 ----------------
export const apiTodayStats = () => get<TodayStats>('/api/stats/today')
export const apiGetSettings = () => get<Settings>('/api/settings')
export const apiSaveSettings = (s: Settings) => post('/api/settings', s as unknown as Record<string, unknown>)
export const apiTestSettings = () => post<{ ok: boolean; message?: string }>('/api/settings/test')
export const apiCopyRules = () => get<CopyRules>('/api/copy/rules')
export const apiCopyGenerate = (payload: Record<string, unknown>) =>
  post<CopyGenerateResp>('/api/copy/generate', payload)
export const apiCopyValidate = (platform: string, title: string) =>
  post<{ ok: boolean; issues: { level: string; msg: string }[] }>('/api/copy/validate', { platform, title })

// ---------------- 批量 ----------------
export const apiBatchBatches = () => get<{ batches: BatchInfo[] }>('/api/batch/batches')
export const apiBatchScan = (dir: string, batchId?: string) =>
  post<{ batch_id: string; videos: Video[] }>('/api/batch/scan', { dir, batch_id: batchId })
export const apiBatchImport = (csv: string, batchId?: string) =>
  post<{ batch_id: string; videos: Video[] }>('/api/batch/import', { csv, batch_id: batchId })
export const apiBatchAddVideo = (path: string, batchId?: string) =>
  post<{ batch_id: string; video: Video; added: boolean }>('/api/batch/videos/add', { path, batch_id: batchId })
export const apiBatchVideos = (batchId: string) =>
  get<{ videos: Video[]; batch_id: string }>('/api/batch/videos', { batch_id: batchId })
export const apiBatchUpdateVideo = (id: number, fields: Record<string, unknown>) =>
  post(`/api/batch/videos/${id}`, fields)
export const apiBatchPlan = (payload: Record<string, unknown>) =>
  post<{ created?: number; items?: number }>('/api/batch/plan', payload)
export const apiBatchBriefGet = (batchId: string) =>
  get<{ batch_id: string; brief: string }>('/api/batch/brief', { batch_id: batchId })
export const apiBatchBriefSet = (batchId: string, brief: string) =>
  post('/api/batch/brief', { batch_id: batchId, brief })
export const apiBatchGenerate = (payload: Record<string, unknown>) => post('/api/batch/generate', payload)
export const apiBatchGenProgress = (batchId: string) =>
  get<GenProgress & { failed: number; error: string }>('/api/batch/generate-progress', { batch_id: batchId })
export const apiBatchItems = (batchId: string) => get<{ items: Item[] }>('/api/batch/items', { batch_id: batchId })
export const apiBatchItemUpdate = (id: number, fields: Record<string, unknown>) =>
  post<Item>(`/api/batch/items/${id}`, fields)
export const apiBatchItemRegenerate = (id: number, payload?: Record<string, unknown>) =>
  post(`/api/batch/items/${id}/regenerate`, payload)
export const apiBatchItemRetry = (id: number) => post(`/api/batch/items/${id}/retry`)
export const apiBatchApprove = (batchId: string, itemIds?: number[], approved = true) =>
  post<{ approved: number }>('/api/batch/approve', { batch_id: batchId, item_ids: itemIds, approved })
export const apiBatchQuota = (batchId: string) => get<Quota>('/api/batch/quota', { batch_id: batchId })
export const apiBatchRun = (payload: Record<string, unknown>) => post('/api/batch/run', payload)
export const apiBatchStop = (batchId: string) => post('/api/batch/stop', { batch_id: batchId })
export const apiBatchStatus = (batchId: string) => get<BatchStatus>('/api/batch/status', { batch_id: batchId })
export const apiBatchDelete = (batchId: string) => post('/api/batch/delete', { batch_id: batchId })

// 文件下载(新窗口)
export const batchVideosCsvUrl = (batchId: string) => `/api/batch/videos/csv?batch_id=${encodeURIComponent(batchId)}`
export const batchReportUrl = (batchId: string) => `/api/batch/report?batch_id=${encodeURIComponent(batchId)}`
