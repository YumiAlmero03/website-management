# ContentHub AI — Security Architecture & Controls

## 1. Threat Model & Deployment Assumptions

ContentHub AI is a **single-administrator private application** deployed on a shared aaPanel Linux server that also hosts production websites. The primary security priorities are:
1. Prevent unauthorized access to the admin dashboard, API, and publishing credentials.
2. Prevent compromise of co-hosted production websites or server resources.
3. Prevent untrusted scraped website content from triggering XSS, SSRF, or prompt injection.
4. Prevent secret leakage in logs, Git history, or backups.

## 2. Phase 1 Implemented Controls

### Authentication & Session Management
- **No Public Registration:** No signup endpoint exists. The single administrator is created explicitly via `python -m app.cli init-admin` with mandatory password complexity (minimum 12 characters, mixed character classes) and zero default passwords.
- **Argon2id Hashing:** Passwords are hashed with `argon2-cffi` (Argon2id).
- **Opaque Hashed Sessions:** Sessions use 256-bit cryptographically random tokens (`secrets.token_urlsafe(32)`). Only the SHA-256 hex digest is persisted in MySQL `sessions.token_hash`, so a read-only database dump cannot directly hijack active sessions.
- **Cookie Flags:** `HttpOnly=true`, `SameSite=Lax` (configurable), `Path=/`, and `Secure=true` in production HTTPS environments.
- **Session Expiration & Revocation:** Enforced server-side via `expires_at` and `revoked_at`. Logout immediately revokes the DB session and deletes the cookie.

### CSRF Protection
- Every authenticated session carries a unique 256-bit `csrf_token`.
- All mutating authenticated endpoints (`POST`, `PUT`, `PATCH`, `DELETE`) require an exact constant-time match (`hmac.compare_digest`) on the `X-CSRF-Token` request header.

### Login Rate Limiting
- Sliding-window rate limiter on `POST /api/v1/auth/login` keyed by client IP and normalized email identifier (`LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5`, `LOGIN_RATE_LIMIT_WINDOW_SECONDS=900`).
- Exceeding limits returns `429 Too Many Requests` with `Retry-After` and logs a redacted security event.

### Credential Encryption at Rest
- Secret settings and future external API tokens are encrypted with `cryptography.fernet.Fernet`.
- `APP_ENCRYPTION_KEY` is stored solely in `.env` (file mode `0600`) outside the database and excluded from Git.
- Missing or malformed `APP_ENCRYPTION_KEY` fails explicitly when encrypting/decrypting secrets rather than falling back to plaintext.

### Sensitive Log & Audit Redaction
- Central redaction utilities scrub sensitive keys (`password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `csrf`, `fernet`, `private_key`) and bearer/credential patterns before writing structured logs or `activity_logs.metadata_json`.

### HTTP Security Headers
- FastAPI appends `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Cache-Control: no-store` on sensitive auth/settings responses.

## 3. Phase 2 Implemented Security Controls (Website Scanner, Extraction & Media)

- **Centralized SSRF Defense (`app/services/scanner/security.py`):** Every outbound HTTP request (connectivity test, auto-discovery, REST/WP API, RSS/Atom, XML sitemap, `llms.txt`, HTML pages, canonical URLs, redirects, image downloads, and optional Playwright) passes through `validate_outbound_url` + `SafeHttpFetcher`:
  - Permits only `http://` and `https://` schemes and ports `80`/`443` by default.
  - Rejects embedded credentials (`user:pass@host`).
  - Blocks `localhost`, `*.localhost`, `*.local`, `*.internal`, loopback (`127.0.0.0/8`, `::1`), RFC1918 private networks, CGNAT (`100.64.0.0/10`), link-local / cloud metadata (`169.254.169.254`, `100.100.100.200`, `fd00:ec2::254`, `metadata.google.internal`), IPv4-mapped IPv6, reserved, and multicast ranges.
  - **DNS Rebinding Defense:** Pins live outbound TCP connections directly to the validated resolved IP while preserving the `Host` header and TLS `sni_hostname` extension.
  - **Redirect Validation:** Disables automatic redirects and re-validates every `Location` hop up to `SCANNER_MAX_REDIRECTS`.
  - **Trusted Internal Opt-In:** Internal destinations require explicit per-host allowlisting via `SCANNER_TRUSTED_INTERNAL_HOSTS` (SSRF protection is never disabled globally).
- **XML & Decompression Bomb Defenses (`sitemap.py`):** Uses `defusedxml` exclusively (blocks XXE/entity expansion), enforces `SCANNER_MAX_DECOMPRESSED_BYTES` during streaming gzip inflation, enforces depth/file caps, and detects recursive sitemap cycles.
- **Untrusted Content & XSS Protection (`markdown.py` & frontend):** Strips `<script>`, `<style>`, `<iframe>`, `<form>`, boilerplate widgets, inline `on*` event handlers, and `javascript:` URLs; renders original HTML source as escaped text rather than unescaped `v-html`.
- **Safe Media Validation (`media.py`):** Validates MIME types, file size caps (`MEDIA_MAX_FILE_BYTES`), Pillow image integrity and pixel dimension limits (`MEDIA_MAX_DIMENSION_PX`, decompression bomb guard), path traversal containment inside `STORAGE_ROOT/images`, and SHA-256 deduplication.
- **Ethical Crawling:** Respects `robots.txt` (`SCANNER_RESPECT_ROBOTS_TXT=true`), enforces crawl delays and response size caps, keeps Playwright disabled by default, and never attempts CAPTCHA or Cloudflare bypasses.

## 4. Planned Security Controls (Phases 3–7)

- **Prompt Isolation (Phase 3):** Untrusted article contexts are strictly delimited from system instructions in Google Gemini API prompts (sole AI generation provider).
- **Publishing Safeguards (Phases 4–5):** Semi-automatic approval is default; official APIs only; never bypass platform policies with browser automation or session-cookie injection.
- **QA, Security Hardening & Deployment Verification (Phase 7):** Expanded SSRF/security regression tests, least-privilege aaPanel deployment hardening, and backup/restore verification drills.

## 5. Private Deployment & OAuth Callback Considerations

- **Network Exposure:** Bind Nuxt (`127.0.0.1:3100`) and FastAPI (`127.0.0.1:8100`) to loopback only. Place ContentHub AI behind a private VPN (Tailscale/WireGuard), SSH tunnel, IP-allowlisted Nginx reverse proxy, or Cloudflare Access / mutual TLS.
- **OAuth Callback URLs (Phases 4–5):** Integrations such as Facebook Pages Graph API, Google Search Console, Blogger, LinkedIn, and Google Business Profile require an HTTPS callback URL reachable by the administrator's browser (and, for some verification checks, a valid TLS hostname). When running behind a private VPN/allowlist:
  - Prefer a dedicated private subdomain with valid HTTPS TLS (e.g., `https://contenthub.private.example.com/api/v1/accounts/oauth/callback`) restricted by VPN/IP allowlist at Nginx, **or**
  - Use provider-supported manual token / app password flows (such as WordPress Application Passwords or manual publishing fallback) when public callback exposure is undesirable.
- **Never commit** `.env`, TLS keys, SQL dumps, backups, or `storage/` data to Git.
