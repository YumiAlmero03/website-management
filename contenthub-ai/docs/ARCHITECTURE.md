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

1. **Nuxt 4 Frontend (`frontend/` — Active Phases 1–2.1):** Desktop-first administrative dashboard built with Nuxt 4 (`app/` directory), TypeScript, Tailwind CSS v4, Nuxt UI v4, Pinia, and Lucide Icons. Employs a simplified **Website-Centric** workspace (no standalone `/brands` section), Settings-managed Website Categories, a 5-tab Website Detail Console, and a Universal Content Library with live tab counts.
2. **FastAPI Backend (`backend/` — Active Phases 1–2.1):** Python 3.12 REST API handling auth, CSRF, Settings/Categories, Website + merged Brand management, URL Rules, Discovery Sources, Content Library & Revisions, and Media assets.
3. **Python Background Executor & Worker (`backend/app/cli.py`, `backend/workers/`):** Non-blocking detached scan execution (`run-scan --scan-id`) and Cron scheduler (`run-due-scans`) with MySQL advisory locking, batched checkpoints, stale recovery, and `psutil` Resource Guardian deferral.

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
    BlogPost -- No --> Schema{JSON-LD Article / BlogPosting or og:type=article?}
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

## 6. Backend Internal Layering

```text
backend/app/
├── main.py            # App factory, CORS, security headers, middleware, router mounting
├── config.py          # Pydantic Settings loaded from .env (Phases 1–2.1)
├── database.py        # SQLAlchemy 2 engine, pool configuration, MySQL health/version probe
├── cli.py             # CLI: check-db, init-admin, run-scan, run-due-scans
├── core/              # Argon2id, Fernet, sessions, CSRF, rate limit, redaction, deps
├── models/            # Phase 1 (4) + Phase 2.1 (9) = 13 SQLAlchemy InnoDB/utf8mb4 models
├── schemas/           # Pydantic v2 API request & response contracts (category, website, content, media, dashboard)
├── repositories/      # Protocol + SQLAlchemy repositories (Phase 1 & Phase 2.1)
├── services/
│   ├── auth_service.py, settings_service.py, dashboard_service.py
│   ├── category_service.py, website_service.py, scan_executor.py, content_service.py, media_service.py
│   ├── monitoring/    # Live psutil Resource Guardian & health checks
│   ├── scanner/       # Aggregated discovery adapters + classifier + security (15 modules)
│   ├── content/       # Content-type-aware Trafilatura/BS4/Markdownify/YAKE/RapidFuzz/Pillow (9 modules)
│   └── ai/, seo/, social/, editorial/, publishers/, scheduler/, analytics/ (Phases 3–6 stubs)
└── routers/           # Lightweight FastAPI HTTP routers
```
