export function fmtBytes(n: number): string {
  if (!n || n <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

/** Windows/Unix 路径取文件名 */
export function fileName(p: string): string {
  if (!p) return ''
  const parts = p.split(/[\\/]/)
  return parts[parts.length - 1] || p
}

/** 'YYYY-MM-DD HH:MM:SS' -> 'MM-DD HH:MM'，空值返回 '-' */
export function fmtTime(t: string | null | undefined): string {
  if (!t) return '-'
  return t.length >= 16 ? t.slice(5, 16) : t
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined
  return (...args: A) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }
}
