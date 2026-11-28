# ContentHub AI — Architecture

## 1. Architectural Style

ContentHub AI uses a **modular monolith** architecture paired with **separate Python background execution** (Phase 2/2.1 detached scan executor & scheduled CLI; full persistent job worker in Phase 6). It runs safely alongside production websites on a single aaPanel Linux server (`Asia/Manila` default display timezone) using existing MySQL without Redis, Celery, SQLite, or Docker requirements.

## 2. Three Independent Components

```text
                       ┌──────────────────────────────┐
                       │    Nginx (aaPanel Reverse    │
                       │    Proxy / Private Access)   │
                       └───────┬──────────────┬───────┘
                               │ /            │ /api/
                               ▼              ▼
             ┌──────────────────────┐   ┌──────────────────────────┐
             │  1. Nuxt 4 Frontend  │   │  2. FastAPI Backend API  │
             │  (PM2, :3100, TS)    │──▶│  (Supervisor, :8100)     │
             └──────────────────────┘   └────────────┬─────────────┘
                                                     │
                                                     │ SQLAlchemy + PyMySQL
                                                     │ (pool=3, overflow=2)
                                                     ▼
                                        ┌──────────────────────────┐
                                        │  Existing aaPanel MySQL  │
                                        │  (InnoDB, utf8mb4,       │
                                        │   FULLTEXT, Scan Items)  │
                                        └────────────▲─────────────┘
                                                     │
                                                     │ Row-locked claiming &
                                                     │ MySQL advisory locks
                                                     ▼
                                        ┌──────────────────────────┐
                                        │ 3. Python Background     │
                                        │    Executor & Worker     │
                                        │ (Phase 2.1 CLI + Phase 6)│
                                        └──────────────────────────┘
```

1. **Nuxt 4 Frontend (`frontend/` — Active Phases 1–3):** Desktop-first administrative dashboard built with Nuxt 4 (`app/` directory), TypeScript, Tailwind CSS v4, Nuxt UI v4, Pinia, and Lucide Icons. Employs a **Website-Centric** workspace (no standalone `/brands`), 7-tab `/websites/[id]` workspace (including `Social Profiles` & `AI Settings`), Universal Content Library with Generate Social modal, **AI Management Center** (`/ai-management`), and **Social Media Draft Queue** (`/social-media`).
2. **FastAPI Backend (`backend/` — Active Phases 1–3):** Python 3.12 REST API handling auth, CSRF, Settings/Categories, Website + merged Brand management, URL Rules, Discovery Sources, Content Library, Media assets, Website Social Profiles, Gemini AI configurations, Website Knowledge Profiles, Sandboxed Prompts, Response Cache, Generation Jobs/Usage/CSV History, and Draft Management.
3. **Python Background Executor & Worker (`backend/app/cli.py`, `backend/workers/`):** Non-blocking detached scan and AI generation execution (`run-scan`, `run-due-scans`, `run-ai-job`, `run-pending-ai-jobs`) with MySQL advisory locking & row-locked `FOR UPDATE` claiming, batched checkpoints, stale recovery, and `psutil` Resource Guardian deferral.

## 3. Website-Centric Aggregated Multi-Source Discovery *(Phase 2.1)*

```mermaid
flowchart TD
    Start[Website Scan Triggered: full / incremental / resume / retry_failed / discover_only] --> RG{Resource Guardian Healthy?}
    RG -- Critical --> Pause[Mark paused & Preserve Pending Queue]
    RG -- Healthy --> Mode{Scan Mode}
    Mode -- resume --> LoadPend[Load Pending URLs from website_contents / scan_items]
    Mode -- retry_failed --> LoadFail[Load Failed URLs from website_contents]
    Mode -- full / incremental / discover_only --> Plan[Build Aggregated Plan Across All Enabled Sources]

    Plan --> E1[Homepage & Internal HTML Links]
    Plan --> E2[WordPress / Custom REST API]
    Plan --> E3[RSS / Atom Feeds w/ Isolated ETag]
    Plan --> E4[Robots.txt + Recursive XML / PHP / .gz Sitemaps w/ Isolated ETag]
    Plan --> E5[llms.txt + Blog Index Follow-up]
    Plan --> E6[Optional Playwright Fallback if Enabled]

    E1 & E2 & E3 & E4 & E5 & E6 --> Source304{Endpoint returned 304 Not Modified?}
    Source304 -- Yes --> KeepPrior[Keep Prior DB URLs Intact & Continue Other Sources]
    Source304 -- No --> Merge[Normalize, Deduplicate by url_hash & Merge discovery_sources]

    KeepPrior --> Merge
    Merge --> PersistAll[Phase A: Persist ALL URLs & Exclusions into website_scan_items + website_contents]
    PersistAll --> DiscoverCheck{discover_only mode?}
    DiscoverCheck -- Yes --> MarkIncomplete[Finish Discovery w/ pending_count for Resume]
    DiscoverCheck -- No --> BatchLoop

    LoadPend --> BatchLoop
    LoadFail --> BatchLoop
    BatchLoop[Phase B: Extract in Configurable Batches up to crawl_max_urls_per_run] --> Fetch[SafeHttpFetcher + Robots Check]
    Fetch -- HTTP Error / Network Error --> SaveFail[Persist Failed Status, HTTP Code & Error Detail]
    Fetch -- HTTP 200 --> Classify[Deterministic Classifier + Custom Rules + JSON-LD + Manual Override Check]
    Classify --> Extract[Content-Type-Aware Trafilatura / BS4 Extraction + Markdown + YAKE + Context Compression]
    Extract --> Diff{content_hash changed?}
    Diff -- Yes --> SnapRev[Save Snapshot in content_revisions]
    Diff -- No --> SaveOK[Save Extracted Content & Update Item Status]
    SnapRev --> SaveOK
    SaveOK & SaveFail --> Budget{More pending items > run budget?}
    Budget -- Yes --> StatusInc[Mark Scan 'incomplete' for Resumable Continuation]
    Budget -- No --> StatusDone[Mark 'completed' or 'partially_completed' & Reconcile Exact Counts]
```

## 4. Deterministic URL Classification Priority *(Phase 2.1)*

```mermaid
flowchart LR
    URL[Normalized URL + Path + Website Domain] --> M{Manual Override?}
    M -- Yes --> OutM[Preserve Pinned content_type]
    M -- No --> R{Website Custom URL Rules ordered by priority + specificity}
    R -- Match Exclude --> Excl[Mark Excluded]
    R -- Match Rule --> OutR[Assign Rule target_content_type]
    R -- No Match --> Root{Root '/' or '/index.*'?}
    Root -- Yes --> OutH[homepage]
    Root -- No --> Sys{System / Binary Exclude Pattern?}
    Sys -- Yes --> Excl
    Sys -- No --> Tax{Taxonomy or Archive Path? category / tag / author / yyyy/mm}
    Tax -- Yes --> OutT[category / tag / archive]
    Tax -- No --> BlogRoot{Blog Root /blog, /blogs, /news or /blog/page/N?}
    BlogRoot -- Yes --> OutBI[blog_index]
    BlogRoot -- No --> BlogPost{Post Path /blog/*, /blogs/*, /news/*, yyyy/mm/slug?}
    BlogPost -- Yes --> OutBP[blog_post]
    BlogPost -- No --> GamePath{Game Path /game/* or /games/*?}
    GamePath -- Yes --> OutGP[game_page]
    GamePath -- No --> Schema{JSON-LD Article / BlogPosting or og:type=article?}
    Schema -- Yes --> OutBP
    Schema -- No --> OutP[page fallback — retain valid pages without requiring article metadata]
```

## 5. Website Scan Lifecycle *(Phase 2.1 State Diagram)*

```mermaid
stateDiagram-v2
    [*] --> pending : Full, Incremental, Resume, Retry Failed, or Discover Only queued
    pending --> processing : Transactional claim via SELECT FOR UPDATE
    pending --> paused : Resource Guardian critical load or stale heartbeat with pending items
    pending --> failed : Stale heartbeat timeout recovered without pending queue

    processing --> completed : All discovered items processed with 0 pending & 0 failures
    processing --> partially_completed : 0 pending items & >= 1 failed item or failing optional source
    processing --> incomplete : Stopped cleanly at crawl_max_urls_per_run with pending items saved
    processing --> paused : Resource Guardian critical load mid-run
    processing --> failed : Fatal discovery failure across all sources or interrupted without queue

    incomplete --> pending : Resume Incomplete Scan enqueues next batch
    paused --> pending : Resume Incomplete Scan or Retry resumes safely
    partially_completed --> pending : Retry Failed URLs re-attempts failed items
    failed --> pending : Retry / Full Scan

    completed --> [*]
    cancelled --> [*]
```

## 5.1 Phase 3 — Gemini AI Engine & Multi-Profile Social Draft Flow

```mermaid
flowchart TD
    Trigger["Manual Generate Content or Auto-Scan New Blog Post"] --> Guard{"Active generation_enabled Social Profiles >= 1?"}
    Guard -- "No (0 Profiles)" --> Block["Return Prompt to Configure Website Social Profiles (No Gemini Call)"]
    Guard -- Yes --> Enqueue["Enqueue MySQL ai_generation_jobs Row"]
    Enqueue --> Claim["CLI Worker Transactional Claim (SELECT FOR UPDATE)"]
    Claim --> RG{"Resource Guardian Healthy & Concurrent Slots Open?"}
    RG -- Critical / Busy --> Defer["Defer Job Safely in MySQL for Retry"]
    RG -- Healthy --> Prep["Python Context Prep (metadata_only / optimized / full) + Website Knowledge Profile"]
    Prep --> Render["Sandboxed Jinja2 Prompt Rendering + Destination Profile Specs"]
    Render --> Cache{"Valid Website-Scoped SHA-256 Cache Hit?"}
    Cache -- Yes --> RecordHit["Record cache_hit=true Log (Zero Tokens)"]
    Cache -- No --> Quota{"Free-First Daily Requests / Tokens & RPM Available?"}
    Quota -- Exhausted --> Defer
    Quota -- Available --> Gemini["google-genai Interactions Structured JSON Output"]
    Gemini --> Validate{"Validate social_profile_id Ownership & Platform Limits"}
    Validate -- "Invalid / Foreign Profile ID" --> FailJob["Fail Explicitly Without Caching or Writing Foreign Drafts"]
    Validate -- "Validated (Full or Partial)" --> StoreCache["Persist Validated Output to ai_response_cache"]
    RecordHit & StoreCache --> Drafts["Save social_posts & social_post_revisions (pending_review / generation_failed)"]
```

## 5.2 Phase 3 — SEO Keyword Mapping, Content Approval & Auto-Generation Gating

```mermaid
flowchart TD
    Scan[Scanner Discovers & Extracts Eligible URL] --> Queue["Create awaiting_extraction -> pending_review + Python Focus/Secondary/Anchor/Image Alt Suggestions"]
    Scan --> Unchanged{"Already Approved or Rejected & Content Unchanged?"}
    Unchanged -- Yes --> Preserve["Preserve Existing Approval Decision & Locked Approved Keywords"]
    Unchanged -- No --> Changed["Meaningful Update -> Transition to needs_rereview (Keep Approved Keywords)"]
    Queue & Changed --> Review["/content-approval or Content Library Detail Review"]
    Review --> InlineEdit["Edit Focus Keyphrase, Secondary Keywords, Anchors, Alt Text, Classification Inline"]
    InlineEdit --> Cannibal{"Check Same-Website Focus Overlap (RapidFuzz)"}
    Cannibal -- Overlap Found --> Warn["Non-Blocking Cannibalization Warning Shown"]
    InlineEdit & Warn --> Approve["Approve Content & Keyword Mapping Atomically"]
    Review --> Reject["Reject Content (Excluded from AI Generation)"]
    Approve --> Eligibility{"Website Active & auto_generate & Post-Baseline blog_post & First Trigger?"}
    Eligibility -- Yes --> AutoGen["Enqueue Auto Social Draft Job Using Focus Keyphrase, Secondary Keywords & Internal Links"]
    Eligibility -- No --> KeywordMap["Available in Keyword Map & KeywordReuseService"]
    AutoGen --> KeywordMap
```

## 6. Backend Internal Layering

```text
backend/app/
├── main.py            # App factory, CORS, security headers, middleware, router mounting
├── config.py          # Pydantic Settings loaded from .env (Phases 1–3)
├── database.py        # SQLAlchemy 2 engine, pool configuration, MySQL health/version probe
├── cli.py             # CLI: check-db, init-admin, run-scan, run-due-scans, run-ai-job, run-pending-ai-jobs
├── core/              # Argon2id, Fernet, sessions, CSRF, rate limit, redaction, deps
├── models/            # Phase 1 (4) + Phase 2.1 (9) + Phase 3 (12) + Phase 3 Keywords/Approval (4) = 29 InnoDB/utf8mb4 models
├── schemas/           # Pydantic v2 contracts (category, website, content, keyword_approval, media, dashboard, social_profile, ai, social_post)
├── repositories/      # Protocol + SQLAlchemy repositories (Phases 1–3)
├── services/
│   ├── auth_service.py, settings_service.py, dashboard_service.py
│   ├── category_service.py, website_service.py, scan_executor.py, content_service.py, media_service.py
│   ├── content_approval_service.py # Approval queue, inline keyword edits, cannibalization & KeywordReuseService
│   ├── social_profile_service.py, social_post_service.py
│   ├── monitoring/    # Live psutil Resource Guardian & health checks
│   ├── scanner/       # Aggregated discovery adapters + classifier + security (15 modules)
│   ├── content/       # Extraction, Markdownify, YAKE, Python Keyword Suggester (keyword_suggester.py), RapidFuzz, Pillow
│   ├── ai/            # Gemini SDK adapter, quotas, knowledge, sandboxed prompts, cache, validator, generation jobs
│   └── seo/, editorial/, publishers/, scheduler/, analytics/ (Phases 4–6 stubs)
└── routers/           # Lightweight FastAPI HTTP routers
```


---

## Phase 4 Architecture — Social Publishing & Account Connections

Phase 4 extends ContentHub AI with modular official-API adapters, OAuth 2.0 / PKCE session management, Pillow media normalization, 11-point preflight validation, durable MySQL publishing jobs, FullCalendar Standard scheduling, and permanent publication history.

### 1. End-to-End Approval, Preflight & Publishing Flow

```mermaid
flowchart TD
    A["Discovered Content & Keywords"] --> B{"Content + Keyword Approved?"}
    B -- "No" --> C["Blocked by Preflight"]
    B -- "Yes" --> D["Social Draft Edited & Approved (pinned revision)"]
    D --> E{"Material Edit or Media Change?"}
    E -- "Yes" --> F["Invalidate Approval + Cancel Active Schedule"]
    F --> D
    E -- "No" --> G["11-Point Preflight Check"]
    G --> H{"Publishing Method"}
    H -- "Manual / X Paid Disabled" --> I["Copy Content + Download Media + Mark Published"]
    I --> M["PublicationRecord Snapshot + History Log"]
    H -- "Official API (confirm=true)" --> J["Durable PublishingJob (MySQL FOR UPDATE)"]
    J --> K["Pillow Prepare Media + Scoped Public URL (24h)"]
    K --> L["TrustedPublisherHttpClient (HTTPS Host Allowlist)"]
    L -- "2xx Success" --> M
    L -- "429 / 5xx / Critical Load" --> N["Deferred Exponential Backoff Retry"]
    L -- "400 / 401 / 403 Permanent" --> O["Failed Job + Error Details (Manual Retry)"]
    L -- "Timeout After POST Mutation" --> P["VerificationRequired (No Blind Retry)"]
    P --> Q["Reconcile (Auto Feed Check / Confirm Published / Confirm Missing)"]
    Q --> M
```

### 2. OAuth 2.0 + PKCE Connection & Token Refresh Sequence

```mermaid
sequenceDiagram
    actor Admin
    participant UI as Connected Accounts UI
    participant API as FastAPI Publishing Router
    participant DB as MySQL (InnoDB)
    participant Ext as Official Platform OAuth/API

    Admin->>UI: Click Connect OAuth
    UI->>API: POST /social-profiles/{id}/connect (mode=oauth)
    API->>API: Validate redirect_uri host + generate PKCE S256 & state
    API->>DB: Store hashed state + Fernet-encrypted code_verifier (15m TTL)
    API-->>UI: Return authorization_url
    Admin->>Ext: Authorize app scopes
    Ext-->>UI: Redirect back with code & state
    UI->>API: POST /social-profiles/{id}/oauth/complete
    API->>DB: Consume single-use pending state (reject replay/expired)
    API->>Ext: Exchange code + verifier via TrustedPublisherHttpClient
    Ext-->>API: Access token, refresh token & discovered Pages/Locations/Boards
    API->>DB: Store Fernet-encrypted tokens + SocialProfileConnection
    API-->>UI: Return connection status, scopes & target options
```

### 3. Publishing Job Lifecycle & Ambiguous Timeout Recovery

```mermaid
stateDiagram-v2
    [*] --> queued: "Publish Now / Due Schedule"
    queued --> processing: "Worker claims with SELECT FOR UPDATE"
    processing --> deferred: "Resource Guardian critical OR Retryable 429/5xx"
    deferred --> processing: "Re-claimed after next_retry_at"
    processing --> published: "2xx External Post ID + Permalink"
    processing --> failed: "Permanent 400/401/403 OR max_attempts exhausted"
    failed --> queued: "Explicit Admin Retry"
    processing --> verification_required: "Network Timeout after POST mutation OR Stale Heartbeat"
    verification_required --> published: "Reconcile confirms post exists or Admin confirms URL"
    verification_required --> queued: "Reconcile confirms missing (safe re-queue)"
```
