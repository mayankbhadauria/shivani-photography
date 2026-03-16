# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A photography portfolio app: React SPA frontend + FastAPI backend deployed on AWS Lambda. Images are stored in S3 (`originals/` prefix). API Gateway exposes the Lambda as a REST API. The site is served from `shivyank.com` via CloudFront.

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
This builds the Lambda package, deploys to Lambda, builds the React frontend, syncs to S3, and invalidates the CloudFront cache.

## Architecture

**Auth flow:**
- All API endpoints require a valid Cognito JWT (`Authorization: Bearer <token>`)
- `App.js` checks for an active Cognito session on load; shows `LoginPage` if none
- On login, `amazon-cognito-identity-js` exchanges credentials for tokens — no Amplify
- `services/api.js` axios interceptor calls `getIdToken()` and attaches `Bearer` header to every request
- Backend `auth.py` validates JWTs locally using Cognito's JWKS endpoint (RS256); no network call after first fetch (cached)
- Three Cognito groups control access:
  - `Admin` — view, upload, delete, download
  - `Downloader` — view + download
  - `Viewer` — view only
- Upload zone and Delete button are hidden in the UI for non-Admin users (role checked via `cognito:groups` claim)

**Upload flow (presigned URLs):**
- Frontend calls `POST /api/presigned-upload` with filenames/content-types
- Backend generates S3 presigned PUT URLs (valid 5 min)
- Frontend uploads files **directly to S3** via presigned URLs — bypasses API Gateway's 10MB limit
- Frontend refreshes gallery after upload

**Delete flow:**
- Gallery shows a 🗑 Delete button on the currently viewed image
- Clicking confirms then calls `DELETE /api/images/{key}`
- Backend deletes the object from S3; frontend removes it from state immediately

**Frontend → Backend flow:**
- `services/api.js` — Axios client; reads `REACT_APP_API_URL` from env (`.env` = localhost, `.env.production` = API Gateway URL)
- On load: `GET /api/health` checks S3 connectivity, `GET /api/images` fetches all portfolio images

**Backend:**
- `main.py` — FastAPI app with `S3PhotoService` class handling all S3 operations (list, upload, presigned URLs). CORS allows localhost:3000, shivyank.com, and AWS origins.
- `auth.py` — JWT validation via Cognito JWKS. Exposes `require_admin` and `require_any_authenticated` FastAPI dependencies. Uses pure-Python `python-jose` + `rsa` + `ecdsa` (no C extensions) so it works on Lambda without platform-specific wheels.
- `lambda_function.py` — Mangum wrapper around the FastAPI app for Lambda execution
- Images are stored with UUID prefix in S3 `originals/` folder
- Protected endpoints: `GET /api/images` (any auth), `POST /api/presigned-upload` / `DELETE /api/images/{key}` / `POST /api/bulk-upload` (Admin only)

**Environment config:**
- Backend reads AWS credentials from `.env` locally; Lambda uses IAM execution role + `AWS_SESSION_TOKEN` env var
- S3 bucket: `shivani-photography-bucket-1765340851` (us-east-1)
- Production API: `https://ndtofxs2z1.execute-api.us-east-1.amazonaws.com/prod`
- CloudFront distribution: `E1NWD0ZPJOTN29` (serves shivyank.com)
- Frontend is a git submodule — commit frontend changes separately inside `frontend/`
- Cognito User Pool: `us-east-1_BcEX8Ytg2`, App Client: `7ki1081bbgu6529j8ohftmujvi`
- Backend Cognito env vars: `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID` (set on Lambda via `update-function-configuration`)
- Frontend Cognito env vars: `REACT_APP_COGNITO_USER_POOL_ID`, `REACT_APP_COGNITO_APP_CLIENT_ID` (in `.env` and `.env.production`)

**Managing users:**
```bash
# Create a new user (self-registration is disabled)
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_BcEX8Ytg2 \
  --username "user@example.com" \
  --temporary-password "TempPass123" \
  --user-attributes Name=email,Value=user@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS --region us-east-1

# Assign to a group (Admin / Downloader / Viewer)
aws cognito-idp admin-add-user-to-group \
  --user-pool-id us-east-1_BcEX8Ytg2 \
  --username "user@example.com" \
  --group-name "Viewer" --region us-east-1
```
First login with a temporary password triggers a new-password-required challenge handled by `LoginPage.js`.

## Known AWS Configuration (must be maintained)

These are infrastructure settings that are NOT in code — if recreating, they must be re-applied:

- **API Gateway binary media types:** `multipart/form-data` must be set as binary, otherwise uploaded images are corrupted (binary bytes decoded as UTF-8, replacing `FF D8` JPEG headers with `EF BF BD`)
- **S3 bucket CORS:** must allow `GET` and `PUT` methods from `*` so the gallery loads and presigned URL uploads work from the browser
- **S3 bucket policy:** public `s3:GetObject` on `arn:aws:s3:::shivani-photography-bucket-1765340851/*` for gallery display
- **Lambda IAM role:** `lambda-execution-role` with `shivani-photography-s3-access` policy attached
- **boto3 session token:** Lambda uses temporary credentials — boto3 client must pass `aws_session_token=os.getenv("AWS_SESSION_TOKEN")` or S3 calls will fail with auth errors
- **MIME types:** use `image/jpeg` for both `.jpg` and `.jpeg` files — `image/jpg` is invalid and causes browsers to reject the image
- **Lambda JWT deps:** `auth.py` uses `python-jose` (no `[cryptography]` extra) + `rsa` + `ecdsa` + `pyasn1`. Do NOT switch to `python-jose[cryptography]` — the `cryptography` package has C extensions; building on macOS produces macOS wheels that break on Lambda's Amazon Linux
- **Cognito JWT validation:** JWKS keys are fetched once at cold start and cached via `@lru_cache`. If the User Pool is recreated, redeploy Lambda to bust the cache
