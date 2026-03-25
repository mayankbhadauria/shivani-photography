import sys
import os
from dotenv import load_dotenv

# Load .env BEFORE importing auth (auth reads env vars at module level)
load_dotenv()

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import io
from typing import List
import uuid
import time
import logging
from auth import require_admin, require_any_authenticated

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Shivani Photography API",
    description="Photography portfolio API deployed on AWS Lambda",
    version="1.0.0",
    # Add these for Lambda deployment
    openapi_url="/prod/openapi.json" if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else "/openapi.json",
    docs_url="/prod/docs" if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else "/docs",
    redoc_url="/prod/redoc" if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else "/redoc"
)

# Update CORS for production
CORS_ORIGINS = [
    "http://localhost:3000",  # Local development
    "http://shivyank.com",
    "https://shivyank.com",
    "https://shivanijadonphotography.com",
    "https://www.shivanijadonphotography.com",
    "http://shivani-photography-website-1765593468.s3-website-us-east-1.amazonaws.com",
    "https://*.amazonaws.com",
    "https://*.s3-website-us-east-1.amazonaws.com",
    "https://*.cloudfront.net"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# AWS Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
CLOUDFRONT_BASE_URL = os.getenv("CLOUDFRONT_BASE_URL", "https://shivyank.com")

# Module-level metadata cache — avoids re-listing S3 on every request
_objects_cache = {"data": None, "ts": 0}
_cat_cache = {}   # per-category cache: {category: {"data": [...], "ts": 0}}
CACHE_TTL = 60    # seconds

VALID_CATEGORIES = ["maternity", "family-kids", "brand-shoot", "creative-portrait"]
HIGHLIGHT_SLOTS  = ["hero", "about", "contact", "login", "portrait-session", "standard-session"]

logger.info(f"Connecting to S3 bucket: {BUCKET_NAME} in region: {AWS_REGION}")

# Initialize S3 client — use explicit keys locally, rely on IAM role in Lambda
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID or None,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
    aws_session_token=os.getenv("AWS_SESSION_TOKEN") or None,
    region_name=AWS_REGION
)


class S3PhotoService:
    def __init__(self):
        self.s3_client = s3_client
        self.bucket_name = BUCKET_NAME

    def test_connection(self):
        try:
            response = self.s3_client.head_bucket(Bucket=self.bucket_name)
            return True
        except Exception as e:
            logger.error(f"S3 Connection Error: {e}")
            return False

    def get_all_objects_sorted(self, force_refresh=False):
        """Fetch originals + check which thumbnails/display images exist — all in 3 LIST calls.
        Results are cached in memory for CACHE_TTL seconds."""
        global _objects_cache
        now = time.time()
        if not force_refresh and _objects_cache["data"] is not None and (now - _objects_cache["ts"]) < CACHE_TTL:
            return _objects_cache["data"]

        def list_keys(prefix):
            keys = set()
            kwargs = {'Bucket': self.bucket_name, 'Prefix': prefix}
            while True:
                resp = self.s3_client.list_objects_v2(**kwargs)
                for obj in resp.get('Contents', []):
                    if not obj['Key'].endswith('/') and obj['Size'] > 0:
                        keys.add(obj['Key'].split('/')[-1])
                if not resp.get('IsTruncated'):
                    break
                kwargs['ContinuationToken'] = resp['NextContinuationToken']
            return keys

        thumb_keys = list_keys('thumbnails/')
        disp_keys = list_keys('display/')

        all_objects = []
        kwargs = {'Bucket': self.bucket_name, 'Prefix': 'originals/'}
        while True:
            response = self.s3_client.list_objects_v2(**kwargs)
            if 'Contents' in response:
                for obj in response['Contents']:
                    if self.is_image_file(obj['Key']) and obj['Size'] > 0:
                        fname = obj['Key'].split('/')[-1]
                        obj['_has_thumb'] = fname in thumb_keys
                        obj['_has_display'] = fname in disp_keys
                        all_objects.append(obj)
            if not response.get('IsTruncated'):
                break
            kwargs['ContinuationToken'] = response['NextContinuationToken']

        all_objects.sort(key=lambda o: o['LastModified'], reverse=True)
        _objects_cache["data"] = all_objects
        _objects_cache["ts"] = now
        return all_objects

    def invalidate_cache(self):
        global _objects_cache
        _objects_cache["data"] = None
        _objects_cache["ts"] = 0

    def get_images_page(self, limit=10, offset=0, force_refresh=False):
        try:
            all_objects = self.get_all_objects_sorted(force_refresh=force_refresh)
            page = all_objects[offset:offset + limit]
            images = [info for obj in page for info in [self.process_image_info(obj)] if info]
            has_more = (offset + limit) < len(all_objects)
            return {
                'images': images,
                'has_more': has_more,
                'next_offset': offset + limit if has_more else None
            }
        except Exception as e:
            logger.error(f"Error fetching images: {e}")
            return {'images': [], 'has_more': False, 'next_offset': None}

    def thumbnail_key(self, original_key):
        filename = original_key.split('/')[-1]
        return f"thumbnails/{filename}"

    def process_image_info(self, s3_object):
        try:
            original_key = s3_object['Key']
            fname = original_key.split('/')[-1]
            has_thumb = s3_object.get('_has_thumb', False)
            has_display = s3_object.get('_has_display', False)
            return {
                'id': fname,
                'original': f"{CLOUDFRONT_BASE_URL}/{original_key}",
                'display': f"{CLOUDFRONT_BASE_URL}/display/{fname}" if has_display else f"{CLOUDFRONT_BASE_URL}/{original_key}",
                'thumbnail': f"{CLOUDFRONT_BASE_URL}/thumbnails/{fname}" if has_thumb else f"{CLOUDFRONT_BASE_URL}/{original_key}",
                'last_modified': s3_object['LastModified'].isoformat(),
                'size': s3_object['Size'],
                'key': original_key
            }
        except Exception as e:
            logger.error(f"Error processing image info: {e}")
            return None

    def display_key(self, original_key):
        filename = original_key.split('/')[-1]
        return f"display/{filename}"

    # ── Category-based methods ──────────────────────────────────────────

    def get_category_objects(self, category, force_refresh=False):
        """List originals for a category with thumb/display existence flags. Cached per category."""
        global _cat_cache
        now = time.time()
        cached = _cat_cache.get(category, {"data": None, "ts": 0})
        if not force_refresh and cached["data"] is not None and (now - cached["ts"]) < CACHE_TTL:
            return cached["data"]

        prefix = f"gallery/{category}/"

        def list_keys(sub):
            keys = set()
            kwargs = {'Bucket': self.bucket_name, 'Prefix': f"{prefix}{sub}/"}
            while True:
                resp = self.s3_client.list_objects_v2(**kwargs)
                for obj in resp.get('Contents', []):
                    if not obj['Key'].endswith('/') and obj['Size'] > 0:
                        keys.add(obj['Key'].split('/')[-1])
                if not resp.get('IsTruncated'):
                    break
                kwargs['ContinuationToken'] = resp['NextContinuationToken']
            return keys

        thumb_keys = list_keys('thumbnails')
        disp_keys  = list_keys('display')

        all_objects = []
        kwargs = {'Bucket': self.bucket_name, 'Prefix': f"{prefix}originals/"}
        while True:
            resp = self.s3_client.list_objects_v2(**kwargs)
            for obj in resp.get('Contents', []):
                if self.is_image_file(obj['Key']) and obj['Size'] > 0:
                    fname = obj['Key'].split('/')[-1]
                    obj['_has_thumb']   = fname in thumb_keys
                    obj['_has_display'] = fname in disp_keys
                    all_objects.append(obj)
            if not resp.get('IsTruncated'):
                break
            kwargs['ContinuationToken'] = resp['NextContinuationToken']

        all_objects.sort(key=lambda o: o['LastModified'], reverse=True)
        _cat_cache[category] = {"data": all_objects, "ts": now}
        return all_objects

    def get_category_page(self, category, limit=10, offset=0, force_refresh=False):
        all_objects = self.get_category_objects(category, force_refresh=force_refresh)
        page   = all_objects[offset:offset + limit]
        images = [info for obj in page for info in [self.process_category_image(obj, category)] if info]
        has_more = (offset + limit) < len(all_objects)
        return {
            'images':      images,
            'has_more':    has_more,
            'next_offset': offset + limit if has_more else None,
            'total':       len(all_objects),
        }

    def process_category_image(self, s3_object, category):
        try:
            fname       = s3_object['Key'].split('/')[-1]
            has_thumb   = s3_object.get('_has_thumb', False)
            has_display = s3_object.get('_has_display', False)
            pfx = f"gallery/{category}"
            return {
                'id':            fname,
                'original':      f"{CLOUDFRONT_BASE_URL}/{pfx}/originals/{fname}",
                'display':       f"{CLOUDFRONT_BASE_URL}/{pfx}/display/{fname}"    if has_display else f"{CLOUDFRONT_BASE_URL}/{pfx}/originals/{fname}",
                'thumbnail':     f"{CLOUDFRONT_BASE_URL}/{pfx}/thumbnails/{fname}" if has_thumb   else f"{CLOUDFRONT_BASE_URL}/{pfx}/originals/{fname}",
                'last_modified': s3_object['LastModified'].isoformat(),
                'size':          s3_object['Size'],
                'key':           s3_object['Key'],
                'category':      category,
            }
        except Exception as e:
            logger.error(f"Error processing category image: {e}")
            return None

    def invalidate_category_cache(self, category):
        global _cat_cache
        _cat_cache.pop(category, None)

    def generate_category_thumbnail(self, category, original_key):
        try:
            fname    = original_key.split('/')[-1]
            dest_key = f"gallery/{category}/thumbnails/{fname}"
            return self._resize_and_upload(original_key, dest_key, (400, 267), 85)
        except Exception as e:
            logger.error(f"Category thumbnail failed for {original_key}: {e}")
            return None

    def generate_category_display(self, category, original_key):
        try:
            fname    = original_key.split('/')[-1]
            dest_key = f"gallery/{category}/display/{fname}"
            return self._resize_and_upload(original_key, dest_key, (1200, 800), 82)
        except Exception as e:
            logger.error(f"Category display failed for {original_key}: {e}")
            return None

    def get_highlights(self):
        """Return CloudFront URLs for hero/about/contact highlight images."""
        result = {}
        for slot in HIGHLIGHT_SLOTS:
            key = f"gallery/highlights/{slot}.jpg"
            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
                result[slot] = f"{CLOUDFRONT_BASE_URL}/{key}"
            except Exception:
                result[slot] = None
        return result

    # ── End category methods ────────────────────────────────────────────

    def _resize_and_upload(self, original_key, dest_key, max_size, quality):
        """Shared resize logic: download original, auto-rotate via EXIF, resize, upload to dest_key."""
        from PIL import Image, ImageOps
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=original_key)
        img = Image.open(io.BytesIO(response['Body'].read()))
        img = ImageOps.exif_transpose(img)  # respect EXIF rotation (phone photos)
        img = img.convert('RGB')
        img.thumbnail(max_size, Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        buffer.seek(0)
        self.s3_client.put_object(
            Bucket=self.bucket_name, Key=dest_key, Body=buffer,
            ContentType='image/jpeg', CacheControl='public, max-age=31536000, immutable'
        )
        return dest_key

    def generate_thumbnail(self, original_key):
        """400×267px thumbnail for the strip."""
        try:
            return self._resize_and_upload(original_key, self.thumbnail_key(original_key), (400, 267), 85)
        except Exception as e:
            logger.error(f"Thumbnail generation failed for {original_key}: {e}")
            return None

    def generate_display_image(self, original_key):
        """1200×800px display image for the carousel — ~10x smaller than raw originals."""
        try:
            return self._resize_and_upload(original_key, self.display_key(original_key), (1200, 800), 82)
        except Exception as e:
            logger.error(f"Display image generation failed for {original_key}: {e}")
            return None

    def upload_image(self, file_content, filename):
        try:
            file_extension = filename.split('.')[-1].lower()
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            original_key = f"originals/{unique_filename}"

            mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                        'gif': 'image/gif', 'bmp': 'image/bmp', 'webp': 'image/webp'}
            content_type = mime_map.get(file_extension, f'image/{file_extension}')

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=original_key,
                Body=file_content,
                ContentType=content_type
            )

            return {
                'success': True,
                'key': original_key,
                'filename': unique_filename
            }

        except Exception as e:
            logger.error(f"Error uploading image: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def is_image_file(key):
        if key.endswith('/'):
            return False
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        return any(key.lower().endswith(ext) for ext in image_extensions)


photo_service = S3PhotoService()


@app.get("/")
async def root():
    return {"message": "Shivani Photography API", "version": "1.0.0"}


@app.get("/api/health")
async def health_check():
    s3_connected = photo_service.test_connection()
    return {
        "status": "healthy" if s3_connected else "unhealthy",
        "s3_connected": s3_connected,
        "bucket": BUCKET_NAME,
        "region": AWS_REGION
    }


@app.get("/api/images")
async def get_images(
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(require_any_authenticated)
):
    try:
        result = photo_service.get_images_page(limit=limit, offset=offset)
        return {
            "images": result['images'],
            "count": len(result['images']),
            "has_more": result['has_more'],
            "next_token": result['next_offset'],
            "bucket": BUCKET_NAME
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching images: {str(e)}")


@app.post("/api/presigned-upload")
async def get_presigned_urls(request: dict, user: dict = Depends(require_admin)):
    try:
        files = request.get("files", [])
        urls = []
        for f in files:
            filename = f.get("filename", "")
            content_type = f.get("content_type", "image/jpeg")
            if not photo_service.is_image_file(filename):
                continue
            file_extension = filename.split('.')[-1].lower()
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            key = f"originals/{unique_filename}"
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={'Bucket': BUCKET_NAME, 'Key': key, 'ContentType': content_type},
                ExpiresIn=900
            )
            urls.append({'filename': filename, 'key': key, 'url': presigned_url, 'content_type': content_type})
        return {"urls": urls}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URLs: {str(e)}")


@app.delete("/api/images/{image_key:path}")
async def delete_image(image_key: str, user: dict = Depends(require_admin)):
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=image_key)
        for derived_key in [photo_service.thumbnail_key(image_key), photo_service.display_key(image_key)]:
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=derived_key)
            except Exception:
                pass
        photo_service.invalidate_cache()
        return {"status": "deleted", "key": image_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")


@app.post("/api/process-thumbnails")
async def process_thumbnails(request: dict, user: dict = Depends(require_admin)):
    """Generate thumbnails + display images for a list of original keys after presigned upload."""
    try:
        keys = request.get("keys", [])
        results = []
        for key in keys:
            thumb_key = photo_service.generate_thumbnail(key)
            disp_key = photo_service.generate_display_image(key)
            # Set Cache-Control on the original too
            try:
                head = photo_service.s3_client.head_object(Bucket=photo_service.bucket_name, Key=key)
                ct = head.get('ContentType', 'image/jpeg')
                photo_service.s3_client.copy_object(
                    Bucket=photo_service.bucket_name, Key=key,
                    CopySource={'Bucket': photo_service.bucket_name, 'Key': key},
                    MetadataDirective='REPLACE', ContentType=ct,
                    CacheControl='public, max-age=31536000, immutable'
                )
            except Exception as e:
                logger.warning(f"Cache-Control update failed for {key}: {e}")
            results.append({"key": key, "thumbnail": thumb_key, "display": disp_key,
                            "success": thumb_key is not None and disp_key is not None})
        photo_service.invalidate_cache()
        return {"processed": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Thumbnail processing failed: {str(e)}")


@app.post("/api/bulk-upload")
async def bulk_upload_images(files: List[UploadFile] = File(...), user: dict = Depends(require_admin)):
    try:
        results = []
        successful_uploads = 0

        for i, file in enumerate(files):
            if not photo_service.is_image_file(file.filename):
                results.append({
                    'filename': file.filename,
                    'success': False,
                    'error': 'Invalid file type'
                })
                continue

            file_content = await file.read()
            upload_result = photo_service.upload_image(file_content, file.filename)
            upload_result['filename'] = file.filename

            if upload_result['success']:
                successful_uploads += 1

            results.append(upload_result)

        return {
            "status": "completed",
            "message": f"Upload completed: {successful_uploads}/{len(files)} files successful",
            "summary": {
                "total_files": len(files),
                "successful": successful_uploads,
                "failed": len(files) - successful_uploads
            },
            "details": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ══════════════════════════════════════════════════════════════════════
#  CATEGORY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/gallery/{category}")
async def get_category_images(
    category: str, limit: int = 10, offset: int = 0,
    user: dict = Depends(require_any_authenticated)
):
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Must be one of: {VALID_CATEGORIES}")
    try:
        result = photo_service.get_category_page(category, limit, offset)
        return {**result, "category": category, "bucket": BUCKET_NAME}
    except Exception as e:
        raise HTTPException(500, f"Error fetching category images: {str(e)}")


@app.post("/api/gallery/{category}/presigned-upload")
async def get_category_presigned_urls(
    category: str, request: dict, user: dict = Depends(require_admin)
):
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    try:
        files = request.get("files", [])
        urls  = []
        for f in files:
            filename     = f.get("filename", "")
            content_type = f.get("content_type", "image/jpeg")
            if not photo_service.is_image_file(filename):
                continue
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            key = f"gallery/{category}/originals/{unique_filename}"
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={'Bucket': BUCKET_NAME, 'Key': key, 'ContentType': content_type},
                ExpiresIn=900
            )
            urls.append({'filename': filename, 'key': key, 'url': presigned_url, 'content_type': content_type})
        return {"urls": urls}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate presigned URLs: {str(e)}")


@app.post("/api/gallery/{category}/process-thumbnails")
async def process_category_thumbnails(
    category: str, request: dict, user: dict = Depends(require_admin)
):
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    try:
        keys    = request.get("keys", [])
        results = []
        for key in keys:
            thumb_key = photo_service.generate_category_thumbnail(category, key)
            disp_key  = photo_service.generate_category_display(category, key)
            try:
                head = photo_service.s3_client.head_object(Bucket=photo_service.bucket_name, Key=key)
                ct   = head.get('ContentType', 'image/jpeg')
                photo_service.s3_client.copy_object(
                    Bucket=photo_service.bucket_name, Key=key,
                    CopySource={'Bucket': photo_service.bucket_name, 'Key': key},
                    MetadataDirective='REPLACE', ContentType=ct,
                    CacheControl='public, max-age=31536000, immutable'
                )
            except Exception as e:
                logger.warning(f"Cache-Control update failed for {key}: {e}")
            results.append({"key": key, "thumbnail": thumb_key, "display": disp_key,
                            "success": thumb_key is not None and disp_key is not None})
        photo_service.invalidate_category_cache(category)
        return {"processed": len(results), "results": results}
    except Exception as e:
        raise HTTPException(500, f"Thumbnail processing failed: {str(e)}")


@app.delete("/api/gallery/{category}/{filename:path}")
async def delete_category_image(
    category: str, filename: str, user: dict = Depends(require_admin)
):
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    try:
        for sub in ["originals", "thumbnails", "display"]:
            try:
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=f"gallery/{category}/{sub}/{filename}")
            except Exception:
                pass
        photo_service.invalidate_category_cache(category)
        return {"status": "deleted", "category": category, "filename": filename}
    except Exception as e:
        raise HTTPException(500, f"Failed to delete image: {str(e)}")


# ══════════════════════════════════════════════════════════════════════
#  HIGHLIGHTS ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/highlights")
async def get_highlights(user: dict = Depends(require_any_authenticated)):
    try:
        return photo_service.get_highlights()
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch highlights: {str(e)}")


@app.get("/api/login-bg")
async def get_login_bg():
    """Public endpoint — no auth required. Returns the login page background image URL."""
    key = "gallery/highlights/login.jpg"
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=key)
        return {"url": f"{CLOUDFRONT_BASE_URL}/{key}"}
    except Exception:
        return {"url": None}


@app.get("/api/highlights/{slot}/presigned")
async def get_highlight_presigned(slot: str, user: dict = Depends(require_admin)):
    if slot not in HIGHLIGHT_SLOTS:
        raise HTTPException(400, f"Invalid slot. Must be one of: {HIGHLIGHT_SLOTS}")
    try:
        key = f"gallery/highlights/{slot}.jpg"
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': BUCKET_NAME, 'Key': key, 'ContentType': 'image/jpeg'},
            ExpiresIn=900
        )
        return {"slot": slot, "key": key, "url": presigned_url}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate presigned URL: {str(e)}")