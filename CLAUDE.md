# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A photography portfolio app: React SPA frontend + FastAPI backend deployed on AWS Lambda. Images are stored in S3 (`originals/` prefix), thumbnails in S3 (`thumbnails/` prefix). API Gateway exposes the Lambda as a REST API. The site is served from `shivyank.com` via CloudFront, which also serves all images and thumbnails via CDN edge caching.

## Commands

### Frontend (`frontend/`)
```bash
npm start          # Dev server at localhost:3000
npm run build      # Production build
npm test           # Run tests
```

### Backend (`backend/`)
```bash
source venv/bin/activate
uvicorn main:app --reload   # Dev server at localhost:8000
bash deploy_lambda.sh        # Build + deploy Lambda, frontend, and CloudFront
```

### Deploying
Run from `backend/` to deploy everything in one step:
```bash
bash deploy_lambda.sh
```
This builds the Lambda package (including Pillow Linux wheel), deploys to Lambda, builds the React frontend, syncs to S3, and invalidates the CloudFront cache.

### Backfilling thumbnails for existing images (run locally, not via Lambda)
```bash
python3 backfill_thumbnails.py   # requires Pillow + boto3 installed natively (not venv)
```
Or run the inline script directly — it lists `originals/`, resizes each to 400×267 JPEG, uploads to `thumbnails/` with `Cache-Control: max-age=31536000, immutable`.

## Architecture

**Auth flow:**
- All API endpoints require a valid Cognito JWT (`Authorization: Bearer <token>`)
- `App.js` checks for an active Cognito session on load; shows `LoginPage` if none
- On login, `amazon-cognito-identity-js` exchanges credentials for tokens — no Amplify
- `services/api.js` axios interceptor calls `getIdToken()` and attaches `Bearer` header to every request
- Backend `auth.py` validates JWTs locally using Cognito's JWKS endpoint (RS256); no network call after first fetch (cached)
- Three Cognito groups control access:
  - `Admin` — view, upload, delete, download, process thumbnails
  - `Downloader` — view + download
  - `Viewer` — view only
- Upload zone, Delete button, and admin stats are hidden in the UI for non-Admin users (role checked via `cognito:groups` claim)
- S3 connection status indicator is visible to Admin only

**Upload flow (presigned URLs):**
- Frontend calls `POST /api/presigned-upload` with filenames/content-types
- Backend generates S3 presigned PUT URLs (valid 15 min)
- Frontend uploads files **directly to S3** via presigned URLs — bypasses API Gateway's 10MB limit
- After upload, frontend calls `POST /api/process-thumbnails` with the uploaded keys
- Backend generates 400×267 JPEG thumbnails using Pillow, stores in `thumbnails/` prefix with 1-year cache headers
- Frontend refreshes gallery after upload + thumbnail generation

**Delete flow:**
- Gallery shows a 🗑 icon-only circle button at the top-left of the currently viewed image (Admin only)
- Clicking confirms then calls `DELETE /api/images/{key}`
- Backend deletes the original from S3, also deletes the corresponding thumbnail from `thumbnails/`, and invalidates the metadata cache
- Frontend removes it from state immediately

**Thumbnail flow:**
- On upload: `POST /api/process-thumbnails` generates thumbnails server-side via Pillow
- Thumbnails are 400×267px JPEG, quality 85, stored as `thumbnails/{same-filename}`
- `Cache-Control: max-age=31536000, immutable` set on all thumbnails — browsers and CloudFront cache for 1 year
- `process_image_info()` checks if a thumbnail exists (via `head_object`) and returns the thumbnail URL; falls back to original if not found
- Pillow is installed in Lambda using `--platform manylinux2014_x86_64 --python-version 39` to get the correct Linux wheel (not macOS wheel)

**Image serving (CDN):**
- All images and thumbnails are served via CloudFront (`shivyank.com/originals/*` and `shivyank.com/thumbnails/*`)
- CloudFront has two origins: website bucket (default) and image bucket (for `/originals/*` and `/thumbnails/*`)
- Cache behaviors use AWS managed `CachingOptimized` policy (ID `658327ea-f89d-4fab-a63d-7e88639e58f6`) — default TTL 86400s, max 31536000s
- Images are **NOT** served from direct S3 URLs — always use CloudFront URLs via `CLOUDFRONT_BASE_URL` env var

**Image ordering:**
- Images are always sorted latest-uploaded first (descending `LastModified`)
- S3 `list_objects_v2` returns alphabetical order only — the backend fetches all metadata, sorts by `LastModified` descending, then paginates by offset
- Pagination uses integer `offset` (not S3 continuation tokens, which are tied to alphabetical order)

**Metadata cache:**
- `get_all_objects_sorted()` caches the sorted S3 object list in Lambda module memory for 60 seconds (`CACHE_TTL`)
- Cache is invalidated immediately on upload (`process-thumbnails`) and delete
- Eliminates repeated S3 LIST calls on every page request during the TTL window
- Uses 3 LIST calls (thumbnails/, display/, originals/) to pre-build existence sets — annotates each object with `_has_thumb` and `_has_display` booleans
- `process_image_info()` reads these flags directly — no per-image `head_object` calls (removed `thumbnail_exists()` and `display_exists()` methods)

**Session management:**
- 10-minute inactivity auto sign-out: `App.js` tracks mousemove/click/keypress/scroll/touch; resets a `setTimeout` on each event
- Any 401 response from the API triggers `window.dispatchEvent(new Event('auth:expired'))`, caught by `App.js` to sign out immediately
- Both paths call `signOut()` + `setSession(null)` which returns user to login page

**Frontend → Backend flow:**
- `services/api.js` — Axios client; reads `REACT_APP_API_URL` from env (`.env` = localhost, `.env.production` = API Gateway URL)
- On load: `GET /api/health` checks S3 connectivity, `GET /api/images` fetches first page (10 images) sorted latest-first
- "Load more" uses offset-based pagination: passes `offset=N` to get the next 10

**Backend:**
- `main.py` — FastAPI app with `S3PhotoService` class handling all S3 operations (list, upload, presigned URLs, thumbnail generation). CORS allows localhost:3000, shivyank.com, and AWS origins.
- `auth.py` — JWT validation via Cognito JWKS. Exposes `require_admin` and `require_any_authenticated` FastAPI dependencies. Uses pure-Python `python-jose` + `rsa` + `ecdsa` (no C extensions) so it works on Lambda without platform-specific wheels.
- `lambda_function.py` — Mangum wrapper around the FastAPI app for Lambda execution
- Images are stored with UUID prefix in S3 `originals/` folder
- Protected endpoints:
  - `GET /api/images` — any authenticated user
  - `GET /api/health` — any authenticated user
  - `POST /api/presigned-upload` — Admin only
  - `POST /api/process-thumbnails` — Admin only
  - `DELETE /api/images/{key}` — Admin only
  - `POST /api/bulk-upload` — Admin only

**Frontend UI:**
- Fonts: **Playfair Display** (title) + **Raleway** (body/UI) via Google Fonts
- Color theme: sky blue and white (`#4a9fd4` / `#87ceeb` / `#f0f8ff`)
- Thumbnail strip shows **10** thumbnails at a time (was 6), size 125×87px
- Navigation arrows in thumbnail strip are 78px (large)
- Download button: icon-only `↓` circle at bottom-left of image
- Delete button: icon-only 🗑 circle at top-left of image (Admin only)
- Select Photos / Refresh / Sign Out buttons always right-aligned
- "Load more" loads 10 images per click
- Gallery stats (photo count, size, upload date) visible to Admin only
- S3 connection status visible to Admin only

**Environment config:**
- Backend reads AWS credentials from `.env` locally; Lambda uses IAM execution role + `AWS_SESSION_TOKEN` env var
- S3 image bucket: `shivani-photography-bucket-1765340851` (us-east-1)
- S3 website bucket: `shivani-photography-website-1765593468`
- Production API: `https://ndtofxs2z1.execute-api.us-east-1.amazonaws.com/prod`
- CloudFront distribution: `E1NWD0ZPJOTN29` (serves shivyank.com — both website and images)
- Frontend is a git submodule — commit frontend changes separately inside `frontend/`
- Cognito User Pool: `us-east-1_BcEX8Ytg2`, App Client: `7ki1081bbgu6529j8ohftmujvi`
- Backend Cognito env vars: `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `CLOUDFRONT_BASE_URL` (set on Lambda via `update-function-configuration`)
- Frontend Cognito env vars: `REACT_APP_COGNITO_USER_POOL_ID`, `REACT_APP_COGNITO_APP_CLIENT_ID` (in `.env` and `.env.production`)

**Users:**
- `admin@shivyank.com` — Admin group
- `guest@shivyank.com` — Viewer group (replaced old `viewer@shivyank.com`)
- Self-registration disabled; all users created via CLI with temporary password + forced reset on first login

**Managing users:**
```bash
# Create a new user (self-registration is disabled)
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_BcEX8Ytg2 \
  --username "user@example.com" \
  --temporary-password "TempPass123" \
  --user-attributes Name=email,Value=user@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS --region us-east-1

# Set permanent password (skip forced reset)
aws cognito-idp admin-set-user-password \
  --user-pool-id us-east-1_BcEX8Ytg2 \
  --username "user@example.com" \
  --password "Password123!" \
  --permanent --region us-east-1

# Assign to a group (Admin / Downloader / Viewer)
aws cognito-idp admin-add-user-to-group \
  --user-pool-id us-east-1_BcEX8Ytg2 \
  --username "user@example.com" \
  --group-name "Viewer" --region us-east-1

# Delete a user
aws cognito-idp admin-delete-user \
  --user-pool-id us-east-1_BcEX8Ytg2 \
  --username "user@example.com" --region us-east-1
```
First login with a temporary password triggers a new-password-required challenge handled by `LoginPage.js`.

## Known AWS Configuration (must be maintained)

These are infrastructure settings that are NOT in code — if recreating, they must be re-applied:

- **API Gateway binary media types:** `multipart/form-data` must be set as binary, otherwise uploaded images are corrupted (binary bytes decoded as UTF-8, replacing `FF D8` JPEG headers with `EF BF BD`)
- **S3 bucket CORS:** must allow `GET` and `PUT` methods from `*` so the gallery loads and presigned URL uploads work from the browser
- **S3 bucket policy:** public `s3:GetObject` on `arn:aws:s3:::shivani-photography-bucket-1765340851/*` for gallery display and CloudFront serving
- **Lambda IAM role:** `lambda-execution-role` with `shivani-photography-s3-access` policy attached
- **boto3 session token:** Lambda uses temporary credentials — boto3 client must pass `aws_session_token=os.getenv("AWS_SESSION_TOKEN")` or S3 calls will fail with auth errors
- **MIME types:** use `image/jpeg` for both `.jpg` and `.jpeg` files — `image/jpg` is invalid and causes browsers to reject the image
- **Lambda JWT deps:** `auth.py` uses `python-jose` (no `[cryptography]` extra) + `rsa` + `ecdsa` + `pyasn1`. Do NOT switch to `python-jose[cryptography]` — the `cryptography` package has C extensions; building on macOS produces macOS wheels that break on Lambda's Amazon Linux
- **Pillow on Lambda:** Must be installed with `--platform manylinux2014_x86_64 --only-binary=:all: --python-version 39` in `deploy_lambda.sh`. Do NOT install Pillow from the venv (macOS ARM64 wheel) — it will crash on Lambda x86_64
- **Cognito JWT validation:** JWKS keys are fetched once at cold start and cached via `@lru_cache`. If the User Pool is recreated, redeploy Lambda to bust the cache
- **CloudFront image origin:** Distribution `E1NWD0ZPJOTN29` has two origins — website bucket (default) and image bucket (`shivani-photography-bucket-1765340851.s3.us-east-1.amazonaws.com`). Cache behaviors for `originals/*` and `thumbnails/*` use `CachingOptimized` managed policy. If recreating, both origins and both cache behaviors must be re-added.
- **CLOUDFRONT_BASE_URL Lambda env var:** Must be set to `https://shivyank.com`. All image URLs in API responses use this base. If the domain changes, update this env var and redeploy.
