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
    id: 'websites',
    label: 'Websites',
    to: '/websites',
    icon: 'Globe',
    phase: 2,
    implemented: true,
    section: 'content',
    description: 'Website-centric brand identity, discovery sources, classification rules, and scans.',
  },
  {
    id: 'content-library',
    label: 'Content Library',
    to: '/content-library',
    icon: 'Library',
    phase: 2,
    implemented: true,
    section: 'content',
    description: 'All discovered homepages, pages, blog posts, blog indexes, revisions, and errors.',
  },
  {
    id: 'content-approval',
    label: 'Content Approval',
    to: '/content-approval',
    icon: 'CheckSquare',
    phase: 3,
    implemented: true,
    section: 'content',
    description: 'Review discovered pages & posts, edit focus/secondary keywords inline, and approve content.',
  },
  {
    id: 'social-media',
    label: 'Social Media',
    to: '/social-media',
    icon: 'Share2',
    phase: 3,
    implemented: true,
    section: 'publishing',
    description: 'Approve drafts, run preflight checks, schedule, publish via API, or track manual posts.',
    plannedCapabilities: [
      'Platform-specific captions, UTM parameters, alternative hooks, media preparation & revisions',
      'Direct API publishing, scheduling, manual copy + URL recording, and execution logs',
      'Permanent publication history snapshots with CSV export and website isolation',
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
    implemented: true,
    section: 'publishing',
    description: 'FullCalendar Standard monthly, weekly, and daily publishing schedule.',
    plannedCapabilities: [
      'Month, week, and day views with drag-and-drop rescheduling',
      'Color-coded scheduled API posts, manual reminders, published posts, and failed jobs',
      'UTC storage rendered in Asia/Manila or profile display timezones via Luxon',
    ],
  },
  {
    id: 'connected-accounts',
    label: 'Connected Accounts',
    to: '/connected-accounts',
    icon: 'Plug',
    phase: 4,
    implemented: true,
    section: 'publishing',
    description: 'Official API publishing adapters, OAuth/PKCE setup, and manual publishing fallback.',
    plannedCapabilities: [
      'Priority 1 adapters: Facebook Pages, Instagram Graph, Google Business Profile & Manual fallback',
      'Priority 2 & 3 adapters: Threads, LinkedIn REST, Pinterest v5 & X v2 with pay-per-use opt-in',
      'Fernet-encrypted credentials, target Page/Location/Board selection, verification & token refresh',
    ],
  },
  {
    id: 'ai-management',
    label: 'AI Management',
    to: '/ai-management',
    icon: 'Sparkles',
    phase: 3,
    implemented: true,
    section: 'system',
    description: 'Google Gemini API settings, prompt templates, token optimization, and cache.',
    plannedCapabilities: [
      'Official Google Gen AI SDK with dynamic model selection (free-tier Flash/Flash-Lite preferred)',
      'Daily request and token quota protection (never auto-switches to paid tiers)',
      'MySQL AI response cache keyed by model, prompt version, website brand rules, and content hash',
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
      'Content discovery, generated drafts, publishing success/failure rates, and platform mix',
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
    id: 'prompt-logs',
    label: 'Prompt Logs',
    to: '/prompt-logs',
    icon: 'ScrollText',
    phase: 4,
    implemented: true,
    section: 'system',
    description: 'Review AI prompts, responses, models, token usage, and errors.',
  },
  {
    id: 'settings',
    label: 'Settings',
    to: '/settings',
    icon: 'Settings',
    phase: 1,
    implemented: true,
    section: 'system',
    description: 'Manage timezone, website categories, publishing defaults, Resource Guardian, and SEO.',
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
