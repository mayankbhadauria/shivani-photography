#!/bin/bash
set -e

FUNCTION_NAME="shivani-photography-api"
WEBSITE_BUCKET="shivani-photography-website-1765593468"
CLOUDFRONT_ID="E1NWD0ZPJOTN29"
REGION="us-east-1"

echo "=== Building Lambda package ==="
rm -rf lambda-deploy
mkdir lambda-deploy
cd lambda-deploy

cp ../main.py ./main.py
cp ../lambda_function.py .
cp ../auth.py .

pip install --target . \
    fastapi==0.68.0 \
    uvicorn==0.15.0 \
    mangum==0.12.3 \
    python-multipart==0.0.5 \
    python-dotenv==0.19.0 \
    starlette==0.14.2 \
    pydantic==1.8.2 \
    typing-extensions \
    "python-jose[cryptography]==3.3.0" \
    requests==2.32.3 \
    --no-deps -q

rm -rf boto3* botocore* s3transfer*
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
zip -r9 deployment.zip . -x "*.pyc" > /dev/null
echo "Package size: $(du -h deployment.zip | cut -f1)"
cd ..

echo "=== Deploying to Lambda ==="
aws lambda update-function-code \
    --function-name $FUNCTION_NAME \
    --zip-file fileb://lambda-deploy/deployment.zip \
    --region $REGION \
    --query '[FunctionName, LastModified]' \
    --output text

echo "=== Building frontend ==="
cd ../frontend
npm run build --silent
cd ../backend

echo "=== Deploying frontend to S3 ==="
aws s3 sync ../frontend/build s3://$WEBSITE_BUCKET --delete

echo "=== Invalidating CloudFront cache ==="
aws cloudfront create-invalidation \
    --distribution-id $CLOUDFRONT_ID \
    --paths "/*" \
    --query 'Invalidation.[Id,Status]' \
    --output text

echo "=== Done ==="
