# Platform Developer Setup & Official API Integration Guides

This guide documents official API prerequisites, developer app setup, required OAuth 2.0 scopes, account eligibility rules, free vs paid tier limits, media requirements, and manual fallback workflows for all platforms supported in ContentHub AI Phase 4.

> **Strict Policy:** ContentHub AI integrates ONLY via official REST/Graph APIs or compliant Manual Publishing workflows (`Copy Content` + `Download Media` + `Mark as Published`). Unofficial browser automation (`Playwright`, Puppeteer, Chrome injection) for social login or posting is strictly prohibited.

Open **Credential Setup** on a profile under **Websites → Social Profiles** or **Connected Accounts** for its developer portal, permissions, and exact OAuth callback. Enter the app credentials in **Connected Accounts → Connect OAuth**, authorize, and select the destination if the platform offers a target picker. **Verify** checks the connection. **Test Post** creates an editable draft for that profile. To exercise publishing, open the draft, attach required media, approve it, then confirm publishing in Social Media. A confirmed API publish can create a live post.

---

## 1. Priority 1 Platforms

### 1.1 Facebook Pages (`facebook` — Meta Graph API `v27.0`)

- **Account Eligibility:** Facebook **Pages only**. Personal Facebook user timelines cannot publish via the official Graph API (`FB_PERSONAL_PROFILE_UNSUPPORTED`).
- **Developer App Setup:**
  1. [Create a Meta app](https://developers.facebook.com/documentation/development/create-an-app) with the **Manage everything on your Page** use case and copy the App ID and App Secret from **App Settings → Basic**.
  2. Configure **Facebook Login for Business** and the [Page publishing permissions](https://developers.facebook.com/docs/graph-api/reference/page/feed/).
  3. Add your ContentHub callback URL to Valid OAuth Redirect URIs (default: `http://127.0.0.1:3100/connected-accounts?oauth_callback=1` or your production HTTPS domain registered in `OAUTH_ALLOWED_REDIRECT_HOSTS`).
- **Required Permissions / Scopes:** `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`.
- **OAuth & Target Selection Flow:** ContentHub exchanges the short-lived user token for a long-lived user token (`fb_exchange_token`), queries `/me/accounts`, stores Page-scoped tokens encrypted via Fernet, and lets the administrator select the exact managed **Page** in **Connected Accounts**.
- **Supported Post & Media Types:** Text + link (`/{page_id}/feed`), single photo with caption (`/{page_id}/photos`).
- **App Review & Limitations:** Before passing Meta App Review (`Live Mode`), posting works only for Pages owned/managed by App Admins, Developers, or Testers.

---

### 1.2 Instagram (`instagram` — Instagram Graph API via Meta `v27.0`)

- **Account Eligibility:** **Instagram Professional (Business or Creator) accounts only**, linked to a managed Facebook Page (`IG_PERSONAL_UNSUPPORTED` rejects `PERSONAL` accounts).
- **Developer App Setup:** Configure [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/content-publishing) in a compatible Meta app. Use its App ID and App Secret.
- **Required Permissions / Scopes:** `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
- **Credential Option:** Under **Credentials**, supply a Facebook Page access token with the publishing permissions and the linked Instagram professional account ID if OAuth does not discover the account.
- **Supported Post & Media Types:** Text-only posts are **not supported**. Requires JPEG image (`320–1440px` width, aspect ratio between `0.8` portrait and `1.91` landscape, max `8 MB`).
- **Media Delivery Rule:** Instagram's `/media` endpoint requires a publicly reachable **HTTPS URL** (`PUBLIC_MEDIA_BASE_URL` or public HTTPS `APP_URL`). ContentHub's Pillow processor converts/resizes attachments into `STORAGE_ROOT/prepared_media/post_<id>/` without altering original uploads and serves them over scoped 24-hour tokenized URLs (`/api/v1/public-media/{token}`).
- **Two-Step Publishing Lifecycle:** Creates container (`POST /{ig_id}/media`), polls container `status_code == FINISHED`, then publishes (`POST /{ig_id}/media_publish`).

---

### 1.3 Google Business Profile (`google_business_profile` — GBP API `v1` + `v4`)

- **Account Eligibility:** Verified Google Business Profile Locations accessible to the authorized Google account.
- **Developer App Setup:**
  1. Create a Google Cloud Project in [Google Cloud Console](https://console.cloud.google.com/).
  2. [Request Google Business Profile API access](https://developers.google.com/my-business/content/prereqs) (unapproved Cloud projects default to **0 QPM** quota).
  3. Enable My Business Account Management API (`v1`), My Business Business Information API (`v1`), and Google My Business API (`v4` Local Posts).
  4. [Create a Web application OAuth client](https://developers.google.com/my-business/content/implement-oauth) and add ContentHub's callback URL. Use the Client ID and Client Secret. ContentHub requests offline access (`access_type=offline`, `prompt=consent`).
- **Required Scope:** `https://www.googleapis.com/auth/business.manage`.
- **Policy & Limitations Notice:** Certain regulated niches (e.g., gambling/gaming) may face GBP policy restrictions or location suspension; ContentHub surfaces a non-blocking compliance warning during preflight when restricted keywords appear in website metadata.

---

### 1.4 Manual Publishing Workflow (`custom_social` or `publishing_method=manual`)

- **Use Cases:** Telegram channels, Viber communities, TikTok/Reels manual uploads, restricted GBP/X profiles without paid/approved APIs, or human-reviewed manual posting.
- **Zero Cost / Zero Credentials:** Requires no external API tokens.
- **Workflow:** Approve draft -> optional Calendar Reminder (`manual_reminder`) -> open **Manual Workflow** modal -> follow platform checklist -> **Copy Final Content** + **Download Media** -> post natively -> paste **Live Published Post URL** -> **Mark as Published** (`manually_published` + `publication_records`).

---

## 2. Priority 2 & 3 Official APIs

### 2.1 Threads (`threads` — `graph.threads.net`)

- **Developer App Setup:** [Create a Meta app with the Threads use case](https://developers.facebook.com/documentation/threads/get-started). Copy the Threads App ID and App Secret and register your callback in the Threads settings.
- **Scopes:** `threads_basic`, `threads_content_publish`.
- **Auth & Refresh:** OAuth 2.0 code exchange -> `th_exchange_token` (60-day long-lived token) + `th_refresh_token` endpoint.
- **Media & Quota:** Supports text, text+image (HTTPS URL), and carousel containers (`/{user_id}/threads` -> wait container -> `/{user_id}/threads_publish`). Official rate limit: **250 API posts per 24 hours**.

### 2.2 LinkedIn (`linkedin` — `/rest/posts` & `/rest/images`)

- **Developer App Setup:** Create a LinkedIn developer app, add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn** for member posting, then copy the Client ID and Client Secret and register the callback in the [Auth tab](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow).
- **Version Headers:** `Linkedin-Version: 202610`, `X-Restli-Protocol-Version: 2.0.0`.
- **Scopes & Tier Distinction:**
  - `openid`, `profile`, `w_member_social` (available via self-serve **Share on LinkedIn** product for personal member URNs `urn:li:person:...`).
  - Company Page posting requires [Community Management API approval](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview). Supply a user token with `openid`, `profile`, `w_organization_social`, and `rw_organization_admin` under **Credentials**, then select the organization target.
- **Media:** Images are uploaded binary via `initializeUpload` -> `PUT` binary upload -> attached using `urn:li:image:...`.

### 2.3 Pinterest (`pinterest` — Pinterest API `v5`)

- **Developer App Setup:** [Connect an app](https://developers.pinterest.com/docs/getting-started/connect-app/) using a business account and request Trial access. Once approved, use the App ID and App Secret from **My apps** and add the callback in **Configure**.
- **Auth:** OAuth 2.0 with **PKCE (`S256`)** and Basic-authenticated token exchange.
- **Scopes:** `boards:read`, `pins:read`, `pins:write`, `user_accounts:read`.
- **Target & Media Rules:** Requires selecting a destination `board_id` and attaching an image. **Trial access** apps create pins visible in Pinterest sandbox testing; **Standard access** approval (including a screencast video demo) is required for live production Pins.

### 2.4 X / Twitter (`twitter` — X API `v2`)

- **Developer App Setup:** Create an app in the [X Developer Console](https://console.x.com/), enable [OAuth 2.0 user authentication](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code), and use the OAuth 2.0 Client ID and Client Secret (if your app uses one).
- **Auth:** OAuth 2.0 with **PKCE (`S256`)** and `offline.access` (`tweet.write`, `tweet.read`, `users.read`, `offline.access`; 2-hour access tokens automatically flagged as `expiring_soon` when refresh is needed).
- **Paid-API Policy:** X API writes use [pay-per-use credits](https://docs.x.com/x-api/getting-started/pricing). Current rates are listed in the Developer Console.
- **Explicit Admin Opt-In Safeguard:** By default `allow_paid_publishing` is `false`, placing connected X profiles in `manual_only` eligibility unless an administrator explicitly enables **Paid X API Authorization** (`POST /social-profiles/{id}/paid-policy`) or confirms per-post before publishing.

---

## 3. Environment & Callback Checklist

1. Set `OAUTH_ALLOWED_REDIRECT_HOSTS` in `backend/.env` for non-localhost admin domains (e.g. `admin.contenthub.example.com`).
2. Set `PUBLIC_MEDIA_BASE_URL` to your public HTTPS backend URL when publishing images to **Instagram** or **Threads**.
3. Run `alembic upgrade head` (`20261128_0008`) and verify via `python -m app.cli check-db`.
