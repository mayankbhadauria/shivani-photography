# Shivani Jadon Photography

A full-stack photography portfolio and booking website live at [shivanijadonphotography.com](https://shivanijadonphotography.com).

## Architecture

```
shivani-photography/          ← this repo (backend + infra)
└── frontend/                 ← git submodule (React SPA)
```

| Layer | Technology |
|---|---|
| Frontend | React 17, styled-components, Amazon Cognito Identity JS |
| Backend | FastAPI (Python 3.9), Mangum, Pillow |
| Hosting | AWS Lambda + API Gateway |
| Storage | S3 (images), S3 (static site) |
| CDN | CloudFront |
| Auth | Amazon Cognito (User Pools + JWT) |
| Domain | Route 53 → CloudFront (`shivanijadonphotography.com`) |

## Pages

| Page | Route | Description |
|---|---|---|
| Home | `/` | Hero banner, category grid, highlights |
| About | `view=about` | Bio, portrait photo, intro text |
| Portfolio | `view=gallery` | Editorial masonry gallery per category |
| Reservation | `view=reservation` | Session types and pricing |
| Info | `view=info` | What to wear tips + FAQ accordion |
| Contact | `view=contact` | Contact form |
| Admin | `view=admin` | Upload, manage highlights (Admin only) |

## Gallery Categories

- `maternity` — Maternity sessions
- `family-kids` — Family & Kids
- `creative-portrait` — Creative Portraits
- `brand-shoot` — Brand Sessions

## S3 Structure

```
shivani-photography-bucket-1765340851/
├── gallery/
│   ├── maternity/
│   │   ├── originals/
│   │   ├── thumbnails/      (400×267px, quality 85)
│   │   └── display/         (1200×800px, quality 82)
│   ├── family-kids/
│   ├── creative-portrait/
│   ├── brand-shoot/
│   └── highlights/
│       ├── hero.jpg
│       ├── about.jpg
│       ├── contact.jpg
│       └── login.jpg
├── originals/               (legacy — pre-category uploads)
├── thumbnails/
└── display/
```

## User Roles (Cognito Groups)

| Group | Permissions |
|---|---|
| `Admin` | View, upload, delete, process thumbnails, manage highlights |
| `Downloader` | View + download |
| `Viewer` | View only |

## Local Development

### Backend

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload     # http://localhost:8000
```

Requires a `.env` file:
```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET_NAME=shivani-photography-bucket-1765340851
CLOUDFRONT_BASE_URL=http://localhost:8000
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_BcEX8Ytg2
COGNITO_APP_CLIENT_ID=7ki1081bbgu6529j8ohftmujvi
```

### Frontend

```bash
cd frontend
npm install
npm start                     # http://localhost:3000
```

Reads from `frontend/.env`:
```
REACT_APP_API_URL=http://localhost:8000
REACT_APP_COGNITO_USER_POOL_ID=us-east-1_BcEX8Ytg2
REACT_APP_COGNITO_APP_CLIENT_ID=7ki1081bbgu6529j8ohftmujvi
```

## Deployment

From the `backend/` directory:

```bash
bash deploy_lambda.sh
```

This will:
1. Build the Lambda ZIP (Python deps + Pillow Linux wheel)
2. Deploy to `shivani-photography-api` Lambda
3. Build the React frontend (`npm run build`)
4. Sync build to S3 website bucket
5. Invalidate CloudFront cache (`/*`)

## AWS Infrastructure

| Resource | ID / Name |
|---|---|
| Lambda | `shivani-photography-api` |
| API Gateway | `ndtofxs2z1` (us-east-1) |
| S3 image bucket | `shivani-photography-bucket-1765340851` |
| S3 website bucket | `shivani-photography-website-1765593468` |
| CloudFront distribution | `E1NWD0ZPJOTN29` |
| Cognito User Pool | `us-east-1_BcEX8Ytg2` |
| Cognito App Client | `7ki1081bbgu6529j8ohftmujvi` |

### Lambda Environment Variables (all required)

```
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_BcEX8Ytg2
COGNITO_APP_CLIENT_ID=7ki1081bbgu6529j8ohftmujvi
S3_BUCKET_NAME=shivani-photography-bucket-1765340851
CLOUDFRONT_BASE_URL=https://shivanijadonphotography.com
```

> **Warning:** When updating Lambda env vars via `update-function-configuration`, the entire `Variables` map is replaced. Always include all five variables or missing ones will be silently dropped, causing S3 calls to fail.

## Cloning (with submodule)

```bash
git clone --recurse-submodules https://github.com/mayankbhadauria/shivani-photography.git
```

Or if already cloned:
```bash
git submodule update --init --recursive
```
