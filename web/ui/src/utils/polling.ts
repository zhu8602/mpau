import { onUnmounted } from 'vue'

/** setInterval 轮询 composable：立即执行一次，组件卸载自动停止 */
export function usePolling(fn: () => void, ms: number) {
  let timer: ReturnType<typeof setInterval> | undefined
  const stop = () => { if (timer !== undefined) { clearInterval(timer); timer = undefined } }
  const start = () => { stop(); fn(); timer = setInterval(fn, ms) }
  start()
  onUnmounted(stop)
  return { stop, start }
}
