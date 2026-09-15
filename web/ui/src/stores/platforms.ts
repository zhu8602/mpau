import { defineStore } from 'pinia'
import { apiPlatforms } from '../api'
import type { PlatformInfo } from '../api/types'

export interface PlatformMeta {
  id: string
  cn: string
  color: string   // 品牌色(badge 底色)
  glyph: string   // 占位图标字符
}

/** 平台元数据：与后端 pipeline/planner.PLATFORMS 顺序一致 */
export const PLATFORM_META: PlatformMeta[] = [
  { id: 'douyin', cn: '抖音', color: '#161823', glyph: '♪' },
  { id: 'kuaishou', cn: '快手', color: '#ff6a00', glyph: '快' },
  { id: 'xiaohongshu', cn: '小红书', color: '#ff2442', glyph: '红' },
  { id: 'tencent', cn: '视频号', color: '#07c160', glyph: '视' },
  { id: 'pdd', cn: 'PDD多多视频', color: '#e02e24', glyph: '拼' },
  { id: 'tmall', cn: '天猫/淘宝光合', color: '#ff0036', glyph: '天' },
  { id: 'jd', cn: '京东京麦', color: '#e1251b', glyph: '京' },
  { id: 'baijiahao', cn: '百家号', color: '#306eff', glyph: '百' },
  { id: 'tiktok', cn: 'TikTok', color: '#010101', glyph: 'T' },
]

/** AI 文案核心平台(与后端 rules.CORE_PLATFORMS 一致); TikTok 不默认参与, 需在账号映射里勾选 */
export const CORE_PLATFORMS = ['douyin', 'kuaishou', 'xiaohongshu', 'tencent']

/** 批量页账号映射默认展示的平台(对齐设计稿)，其余收进"更多" */
export const MAPPING_MAIN = ['douyin', 'kuaishou', 'tencent', 'xiaohongshu']

/** 平台能力(镜像 pipeline/planner.PLATFORM_OPTS，避免新增接口) */
export const PLATFORM_OPTS: Record<string, { note?: boolean; goods?: 'product' | 'goods_id' | 'goods_name' | null; dry_run?: boolean; draft?: boolean; title_required?: boolean; desc_required?: boolean; no_desc?: boolean; tid?: boolean }> = {
  douyin: { note: true, goods: 'product', dry_run: true },
  // 快手只支持按商品名称关联商品(不支持商品ID)
  kuaishou: { note: true, goods: 'goods_name', dry_run: false },
  xiaohongshu: { note: true, goods: null, dry_run: false },
  tencent: { note: false, goods: 'goods_id', dry_run: false, draft: true },
  pdd: { note: false, goods: 'goods_id', dry_run: true, desc_required: true },
  tmall: { note: false, goods: 'goods_id', dry_run: true, title_required: true },
  jd: { note: false, goods: 'goods_id', dry_run: true, title_required: true },
  baijiahao: { note: false, goods: null, title_required: true },
  tiktok: { note: false, goods: null, title_required: true, no_desc: true },
}

/** 字段可见性: 编辑器据此隐藏平台不支持的字段(TikTok 无描述; 非电商平台无商品区) */
export function platformCaps(platform: string): {
  desc: boolean
  goods: boolean
  goodsKind: 'product' | 'goods_id' | 'goods_name' | null
} {
  const o = PLATFORM_OPTS[platform]
  return {
    desc: !o?.no_desc,
    goods: o?.goods === 'product' || o?.goods === 'goods_id' || o?.goods === 'goods_name',
    goodsKind: o?.goods ?? null,
  }
}

export function platformCn(id: string): string {
  return PLATFORM_META.find((p) => p.id === id)?.cn ?? id
}
export function platformMeta(id: string): PlatformMeta {
  return PLATFORM_META.find((p) => p.id === id) ?? { id, cn: id, color: '#4b5563', glyph: id.slice(0, 1) }
}

export const usePlatformsStore = defineStore('platforms', {
  state: () => ({ list: [] as PlatformInfo[] }),
  actions: {
    async load() {
      if (this.list.length) return
      try { this.list = await apiPlatforms() } catch { /* 后端未启时用本地常量 */ }
      if (!this.list.length) this.list = PLATFORM_META.map((p) => ({ id: p.id, name: p.cn }))
    },
  },
})
