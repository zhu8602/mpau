import axios, { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

export const http = axios.create({ baseURL: '/', timeout: 150000 })

http.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError<{ error?: string }>) => {
    const msg = err.response?.data?.error || err.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(err)
  },
)

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const resp = await http.get<T>(url, { params })
  return resp.data
}

export async function post<T>(url: string, data?: Record<string, unknown>): Promise<T> {
  const resp = await http.post<T>(url, data ?? {})
  return resp.data
}
