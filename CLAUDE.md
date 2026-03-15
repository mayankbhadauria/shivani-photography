# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A photography portfolio app: React SPA frontend + FastAPI backend deployed on AWS Lambda. Images are stored in S3 (`originals/` prefix). API Gateway exposes the Lambda as a REST API.

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
bash deploy_lambda.sh        # Package and deploy to AWS Lambda
```

## Architecture

**Frontend → Backend flow:**
- `services/api.js` — Axios client; reads `REACT_APP_API_URL` from env (`.env` = localhost, `.env.production` = API Gateway URL)
- On load: `GET /api/health` checks S3 connectivity, `GET /api/images` fetches all portfolio images
- Upload: `POST /api/bulk-upload` with multipart form data; frontend waits 2s then refreshes gallery

**Backend:**
- `main.py` — FastAPI app with `S3PhotoService` class handling all S3 operations (list, upload, thumbnail validation). CORS allows localhost:3000 and AWS origins.
- `lambda_function.py` — Mangum wrapper around the FastAPI app for Lambda execution
- Images are stored with UUID prefix in S3 `originals/` folder

**Environment config:**
- Backend reads AWS credentials from `.env` locally; Lambda uses IAM execution role + env vars from `env.json`
- S3 bucket: `shivani-photography-bucket-1765340851` (us-east-1)
- Production API: `https://ndtofxs2z1.execute-api.us-east-1.amazonaws.com/prod`
