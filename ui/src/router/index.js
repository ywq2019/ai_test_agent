import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('../views/Tasks.vue')
  },
  {
    path: '/cases',
    name: 'Cases',
    component: () => import('../views/Cases.vue')
  },
  {
    path: '/execution',
    name: 'Execution',
    component: () => import('../views/Execution.vue')
  },
  {
    path: '/reports',
    name: 'Reports',
    component: () => import('../views/Reports.vue')
  },
  {
    path: '/ai-cases',
    name: 'AiCases',
    component: () => import('../views/AiCases.vue')
  },
  {
    path: '/api-test',
    name: 'ApiTest',
    component: () => import('../views/ApiTest.vue')
  },
  {
    path: '/test-plan',
    name: 'TestPlan',
    component: () => import('../views/TestPlan.vue')
  },
  {
    path: '/skills',
    name: 'Skills',
    component: () => import('../views/Skills.vue')
  },
  {
    path: '/llm',
    name: 'LLM',
    component: () => import('../views/LLM.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
