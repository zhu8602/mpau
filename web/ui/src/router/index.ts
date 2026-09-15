import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/batch' },
    // 单条发布已并入批量发布(选择单条视频模块), 旧链接优雅降级
    { path: '/single', redirect: '/batch' },
    { path: '/batch', name: 'batch', component: () => import('../views/BatchPublish.vue') },
  ],
})
