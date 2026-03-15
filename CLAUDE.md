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
bash deploy_lambda.sh        # Package zip (does NOT deploy — see below)
```

### Deploying
The `deploy_lambda.sh` script only builds the zip. To fully deploy:
```bash
# 1. Copy main.py into lambda-deploy and rezip
cp backend/main.py backend/lambda-deploy/main.py
cd backend/lambda-deploy && zip -r9 deployment.zip . && cd ../..

# 2. Push to Lambda
aws lambda update-function-code \
  --function-name shivani-photography-api \
  --zip-file fileb://backend/lambda-deploy/deployment.zip \
  --region us-east-1

# 3. Build and deploy frontend
cd frontend && npm run build
aws s3 sync build s3://shivani-photography-website-1765593468 --delete

# 4. Invalidate CloudFront cache
aws cloudfront create-invalidation --distribution-id E1NWD0ZPJOTN29 --paths "/*"
```

## Architecture

**Upload flow (presigned URLs):**
- Frontend calls `POST /api/presigned-upload` with filenames/content-types
- Backend generates S3 presigned PUT URLs (valid 5 min)
- Frontend uploads files **directly to S3** via presigned URLs — bypasses API Gateway's 10MB limit
- Frontend refreshes gallery after upload

**Frontend → Backend flow:**
- `services/api.js` — Axios client; reads `REACT_APP_API_URL` from env (`.env` = localhost, `.env.production` = API Gateway URL)
- On load: `GET /api/health` checks S3 connectivity, `GET /api/images` fetches all portfolio images

**Backend:**
- `main.py` — FastAPI app with `S3PhotoService` class handling all S3 operations (list, upload, presigned URLs). CORS allows localhost:3000, shivyank.com, and AWS origins.
- `lambda_function.py` — Mangum wrapper around the FastAPI app for Lambda execution
- Images are stored with UUID prefix in S3 `originals/` folder

**Environment config:**
- Backend reads AWS credentials from `.env` locally; Lambda uses IAM execution role + `AWS_SESSION_TOKEN` env var
- S3 bucket: `shivani-photography-bucket-1765340851` (us-east-1)
- Production API: `https://ndtofxs2z1.execute-api.us-east-1.amazonaws.com/prod`
- CloudFront distribution: `E1NWD0ZPJOTN29` (serves shivyank.com)
- Frontend is a git submodule — commit frontend changes separately inside `frontend/`

## Known AWS Configuration (must be maintained)

These are infrastructure settings that are NOT in code — if recreating, they must be re-applied:

- **API Gateway binary media types:** `multipart/form-data` must be set as binary, otherwise uploaded images are corrupted (binary bytes decoded as UTF-8, replacing `FF D8` JPEG headers with `EF BF BD`)
- **S3 bucket CORS:** must allow `GET` and `PUT` methods from `*` so the gallery loads and presigned URL uploads work from the browser
- **S3 bucket policy:** public `s3:GetObject` on `arn:aws:s3:::shivani-photography-bucket-1765340851/*` for gallery display
- **Lambda IAM role:** `lambda-execution-role` with `shivani-photography-s3-access` policy attached
- **boto3 session token:** Lambda uses temporary credentials — boto3 client must pass `aws_session_token=os.getenv("AWS_SESSION_TOKEN")` or S3 calls will fail with auth errors
- **MIME types:** use `image/jpeg` for both `.jpg` and `.jpeg` files — `image/jpg` is invalid and causes browsers to reject the image
