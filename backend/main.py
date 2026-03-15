import sys
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import io
import os
from typing import List
import uuid
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

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
    "http://www.shivyank.com",
    "https://www.shivyank.com",
    "http://shivani-photography-website-1765593468.s3-website-us-east-1.amazonaws.com",
    "https://*.amazonaws.com",  # CloudFront
    "https://*.s3-website-us-east-1.amazonaws.com",
    "https://*.cloudfront.net"  # CloudFront alternative domains
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

    def get_all_images(self):
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix='originals/',
                MaxKeys=100
            )

            images = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    if self.is_image_file(obj['Key']) and obj['Size'] > 0:
                        image_info = self.process_image_info(obj)
                        if image_info:
                            images.append(image_info)

            images.sort(key=lambda x: x['last_modified'], reverse=True)
            return images

        except Exception as e:
            logger.error(f"Error fetching images: {e}")
            return []

    def process_image_info(self, s3_object):
        try:
            original_key = s3_object['Key']
            # For now, use original as thumbnail (no processing)
            base_url = f"https://{self.bucket_name}.s3.{AWS_REGION}.amazonaws.com"

            return {
                'id': original_key.split('/')[-1],
                'original': f"{base_url}/{original_key}",
                'thumbnail': f"{base_url}/{original_key}",  # Same as original for now
                'last_modified': s3_object['LastModified'].isoformat(),
                'size': s3_object['Size'],
                'key': original_key
            }

        except Exception as e:
            logger.error(f"Error processing image info: {e}")
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
async def get_images():
    try:
        images = photo_service.get_all_images()
        return {
            "images": images,
            "count": len(images),
            "bucket": BUCKET_NAME
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching images: {str(e)}")


@app.post("/api/presigned-upload")
async def get_presigned_urls(request: dict):
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
                ExpiresIn=300
            )
            urls.append({'filename': filename, 'key': key, 'url': presigned_url, 'content_type': content_type})
        return {"urls": urls}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URLs: {str(e)}")


@app.delete("/api/images/{image_key:path}")
async def delete_image(image_key: str):
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=image_key)
        return {"status": "deleted", "key": image_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")


@app.post("/api/bulk-upload")
async def bulk_upload_images(files: List[UploadFile] = File(...)):
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