import { describe, expect, it } from 'vitest'
import { SIDEBAR_MODULES, filterModulesByQuery, findModuleByRoute } from '~/utils/navigation'

describe('sidebar navigation catalog', () => {
  it('defines all 15 required administrative modules in order with unique routes', () => {
    expect(SIDEBAR_MODULES).toHaveLength(15)

    const labels = SIDEBAR_MODULES.map((item) => item.label)
    expect(labels).toEqual([
      'Dashboard',
      'Brands',
      'Websites',
      'Content Library',
      'Social Media',
      'Editorial Planner',
      'Articles',
      'Publishing Calendar',
      'Connected Accounts',
      'AI Management',
      'Automation',
      'Analytics',
      'System Health',
      'Logs',
      'Settings',
    ])

    const routes = new Set(SIDEBAR_MODULES.map((item) => item.to))
    expect(routes.size).toBe(15)
  })

  it('resolves routes and filters modules by search query', () => {
    expect(findModuleByRoute('/')?.id).toBe('dashboard')
    expect(findModuleByRoute('/system-health')?.label).toBe('System Health')
    expect(findModuleByRoute('/settings')?.phase).toBe(1)

    const matches = filterModulesByQuery('gemini')
    expect(matches.some((m) => m.id === 'ai-management')).toBe(true)
    expect(filterModulesByQuery('   ')).toEqual([])
  })
})
