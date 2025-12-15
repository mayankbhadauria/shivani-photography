#!/bin/bash
echo "Creating deployment without image processing..."
rm -rf lambda-deploy
mkdir lambda-deploy
cd lambda-deploy
# Copy files - use the no-pillow version
cp ../main_no_pillow.py ./main.py
cp ../lambda_function.py .

# Install only essential dependencies

pip install --target . \
    fastapi==0.68.0 \
    uvicorn==0.15.0 \
    mangum==0.12.3 \
    python-multipart==0.0.5 \
    python-dotenv==0.19.0 \
    starlette==0.14.2 \
    pydantic==1.8.2 \
    typing-extensions \
    --no-deps

# Clean up
rm -rf boto3* botocore* s3transfer*
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
zip -r9 shivani-photography-no-pillow.zip .
echo "Package without Pillow created: $(du -h shivani-photography-no-pillow.zip | cut -f1)"
cd ..