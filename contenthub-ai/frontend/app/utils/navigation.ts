export interface NavModuleItem {
  id: string
  label: string
  to: string
  icon: string
  phase: number
  implemented?: boolean
  section: 'overview' | 'content' | 'publishing' | 'system'
  description: string
  plannedCapabilities?: string[]
}

export const SIDEBAR_MODULES: readonly NavModuleItem[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    to: '/',
    icon: 'LayoutDashboard',
    phase: 1,
    implemented: true,
    section: 'overview',
    description: 'Live system health, database status, active counts, and recent activity.',
  },
  {
    id: 'brands',
    label: 'Brands',
    to: '/brands',
    icon: 'Tags',
    phase: 2,
    implemented: true,
    section: 'content',
    description: 'Manage brand profiles, languages, tone, keywords, hashtags, and CTAs.',
  },
  {
    id: 'websites',
    label: 'Websites',
    to: '/websites',
    icon: 'Globe',
    phase: 2,
    implemented: true,
    section: 'content',
    description: 'Register monitored websites, discovery endpoints, and scan frequencies.',
  },
  {
    id: 'content-library',
    label: 'Content Library',
    to: '/content-library',
    icon: 'Library',
    phase: 2,
    implemented: true,
    section: 'content',
    description: 'Browse extracted articles, clean Markdown, content hashes, and keywords.',
  },
  {
    id: 'social-media',
    label: 'Social Media',
    to: '/social-media',
    icon: 'Share2',
    phase: 4,
    section: 'publishing',
    description: 'Generate, edit, approve, and schedule platform-specific social media posts.',
    plannedCapabilities: [
      'Platform-specific captions, variants, character limit checks, hashtags, and UTM parameters',
      'Manual, Semi-automatic (default), and rule-based Automatic publishing modes',
      'Bulk generation, bulk approval, and publishing history verification',
    ],
  },
  {
    id: 'editorial-planner',
    label: 'Editorial Planner',
    to: '/editorial-planner',
    icon: 'Compass',
    phase: 5,
    section: 'content',
    description: 'Research keywords, content gaps, clusters, and weekly/monthly editorial plans.',
    plannedCapabilities: [
      'Google Search Console and Google Trends RSS integration',
      'Content gap analysis, topic clustering, search intent classification, and content pillars',
      'Topic-first approval before generating outlines or full articles',
    ],
  },
  {
    id: 'articles',
    label: 'Articles',
    to: '/articles',
    icon: 'FileText',
    phase: 5,
    section: 'content',
    description: 'Rich-text Tiptap editorial article workspace with non-blocking SEO checks.',
    plannedCapabilities: [
      'Tiptap open-source rich-text editor with outline, internal/external links, and references',
      'Configurable non-blocking SEO warnings (title 50-60 chars, meta 130-160 chars, heading structure)',
      'Revision history plus Markdown, HTML, and JSON export',
    ],
  },
  {
    id: 'publishing-calendar',
    label: 'Publishing Calendar',
    to: '/publishing-calendar',
    icon: 'CalendarDays',
    phase: 4,
    section: 'publishing',
    description: 'FullCalendar Standard monthly, weekly, and daily publishing schedule.',
    plannedCapabilities: [
      'Month, week, and day views with drag-and-drop rescheduling',
      'Color-coded social posts, editorial articles, draft topics, and failed jobs',
      'UTC storage rendered in the configured Asia/Manila display timezone',
    ],
  },
  {
    id: 'connected-accounts',
    label: 'Connected Accounts',
    to: '/connected-accounts',
    icon: 'Plug',
    phase: 4,
    section: 'publishing',
    description: 'Official API publishing adapters and manual publishing fallback workflows.',
    plannedCapabilities: [
      'Priority 1 adapters: WordPress REST API, Facebook Pages Graph API, Blogger API, Manual fallback',
      'Priority 2 & 3 phased adapters using official APIs only (never unofficial browser posting)',
      'Fernet-encrypted credentials, connection testing, capability detection, and URL recording',
    ],
  },
  {
    id: 'ai-management',
    label: 'AI Management',
    to: '/ai-management',
    icon: 'Sparkles',
    phase: 3,
    section: 'system',
    description: 'Google Gemini API settings, prompt templates, token optimization, and cache.',
    plannedCapabilities: [
      'Official Google Gen AI SDK with dynamic model selection (free-tier Flash/Flash-Lite preferred)',
      'Daily request and token quota protection (never auto-switches to paid tiers)',
      'MySQL AI response cache keyed by model, prompt version, brand rules, and content hash',
    ],
  },
  {
    id: 'automation',
    label: 'Automation',
    to: '/automation',
    icon: 'Workflow',
    phase: 6,
    section: 'system',
    description: 'MySQL persistent job queue, retries, schedules, and background worker status.',
    plannedCapabilities: [
      'Transactional MySQL job claiming with idempotency keys, retries, backoff, and stale recovery',
      'Separate Supervisor-managed Python worker with aaPanel Cron triggers',
      'Ambiguous publishing outcome verification before retrying external posts',
    ],
  },
  {
    id: 'analytics',
    label: 'Analytics',
    to: '/analytics',
    icon: 'BarChart3',
    phase: 6,
    section: 'system',
    description: 'Measured publishing performance, Gemini token usage, and Search Console data.',
    plannedCapabilities: [
      'Article discovery, generated drafts, publishing success/failure rates, and platform mix',
      'Measured Gemini request/token usage clearly separated from estimates and unavailable metrics',
      'Chart.js visualizations backed by real MySQL analytics records',
    ],
  },
  {
    id: 'system-health',
    label: 'System Health',
    to: '/system-health',
    icon: 'Activity',
    phase: 1,
    implemented: true,
    section: 'system',
    description: 'Live MySQL diagnostics, psutil server metrics, Resource Guardian, and storage.',
  },
  {
    id: 'logs',
    label: 'Logs',
    to: '/logs',
    icon: 'ScrollText',
    phase: 1,
    implemented: true,
    section: 'system',
    description: 'Paginated, filterable, redacted audit trail for authentication and system events.',
  },
  {
    id: 'settings',
    label: 'Settings',
    to: '/settings',
    icon: 'Settings',
    phase: 1,
    implemented: true,
    section: 'system',
    description: 'Manage timezone, publishing defaults, Resource Guardian thresholds, SEO, and backups.',
  },
]

export function findModuleByRoute(path: string): NavModuleItem | undefined {
  if (path === '/') {
    return SIDEBAR_MODULES[0]
  }
  return SIDEBAR_MODULES.find((item) => item.to !== '/' && path.startsWith(item.to))
}

export function filterModulesByQuery(query: string): NavModuleItem[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) {
    return []
  }
  return SIDEBAR_MODULES.filter(
    (item) =>
      item.label.toLowerCase().includes(normalized)
      || item.description.toLowerCase().includes(normalized)
      || item.to.toLowerCase().includes(normalized),
  )
}
