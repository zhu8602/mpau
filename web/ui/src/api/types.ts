// ---- 平台 ----
export interface PlatformInfo { id: string; name: string }

// ---- 账号 ----
export interface AccountsResp {
  platform: string
  accounts: string[]
  nicknames: Record<string, string>
}
export interface QrCode { name: string; ts?: number; platform?: string; account?: string; mtime?: string }

// ---- 任务 ----
export type TaskStatus = 'queued' | 'running' | 'success' | 'failed' | 'canceled' | 'interrupted'
export interface Task {
  id: string
  kind: 'login' | 'upload' | 'batch-upload' | string
  platform: string
  account: string
  label: string
  cmd: string
  status: TaskStatus
  error: string
  exit: number | null
  created: string
  started: string
  finished: string
  log: string[]
}

// ---- 批量：视频 ----
export interface Video {
  id: number
  path: string
  sha256: string
  size: number
  base_title: string
  base_desc: string
  base_tags: string
  goods_json: string
  schedule: string
  cover: string
  status: string
}

// ---- 批量：条目 ----
export type ItemStatus =
  | 'draft' | 'approved' | 'running' | 'success'
  | 'failed' | 'skipped' | 'needs_manual' | 'interrupted'
export interface CandidateIssue { level: 'error' | 'warning' | string; msg: string }
export interface Candidate {
  title: string
  desc: string
  tags: string[]
  short_title?: string
  issues?: CandidateIssue[]
}
export interface Item {
  id: number
  batch_id: string
  video_id: number
  platform: string
  account: string
  title: string
  desc: string
  tags: string
  candidates: Candidate[]
  schedule: string
  goods_json: string
  status: ItemStatus
  task_id: string
  retry: number
  error: string
  created: string
  updated: string
  published_at: string
  platform_cn: string
  video_path: string
  video_title: string
  sha256: string
}

export interface BatchInfo {
  batch_id: string
  total: number
  success: number
  failed: number
  running: number
  created: string
}

export interface BatchSummary {
  total: number
  draft: number
  approved: number
  running: number
  success: number
  failed: number
  skipped: number
  needs_manual: number
  interrupted?: number
}
export interface BatchStatus {
  batch_id: string
  summary: BatchSummary
  scheduler: { running: boolean; alive: boolean; message: string }
  items: Item[]
}

export interface GenProgress { done: number; total: number; current?: string; running?: boolean }

export interface QuotaPlatform {
  approved: number
  published: number
  cap: number
  remaining: number
  will_publish: number
  will_skip: number
}
export interface Quota { batch_id: string; platforms: Record<string, QuotaPlatform> }

// ---- 文案 ----
export interface CopyRule {
  cn: string
  title_max: number
  title_min: number
  banned: string[]
  goods?: 'product' | 'goods_id' | null
  notes?: string
}
export type CopyRules = Record<string, CopyRule>

export interface CopyResult {
  cn: string
  candidates: Candidate[]
  error?: string
}
/** /api/copy/generate 返回 {platform: CopyResult}; 标题为空等整体失败时为 {error: string} */
export type CopyGenerateResp = Record<string, CopyResult | string>

// ---- 设置 ----
export interface Settings {
  llm: {
    base_url: string
    api_key: string
    model: string
    timeout: number
    max_tokens: number
    temperature: number
    n_candidates: number
  }
  scheduler: {
    interval_min: number
    daily_cap: number
    max_concurrent: number
    platform_daily_caps: Record<string, number | null>
    min_interval_min?: number
    max_interval_min?: number
    min_daily_cap?: number
    max_daily_cap?: number
  }
}

// ---- 统计 ----
export interface TodayStats {
  published: number
  vs_yesterday: number
  success: number
  success_rate: number
  queued: number
  pending: number
}

// ---- 文件浏览 ----
export interface FileEntry { name: string; dir: boolean; size: number | null }
export interface FilesResp { path: string; parent: string | null; entries: FileEntry[] }
export interface Drive { letter: string; root: string; free?: number; total?: number }
