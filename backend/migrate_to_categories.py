"""
One-time migration: moves existing flat originals/thumbnails/display/ images
into the new gallery/{category}/ folder structure.

Photos are distributed round-robin across the 4 categories for testing.
After testing, admin will delete and re-upload real photos per category.

Run with system Python3 (not venv):
  python3 migrate_to_categories.py
"""
import boto3
import os
from dotenv import load_dotenv

load_dotenv('/Users/mayankbhadauria/Documents/Projects/shivani-photography/backend/.env')

BUCKET     = os.getenv('S3_BUCKET_NAME')
REGION     = os.getenv('AWS_REGION', 'us-east-1')
CATEGORIES = ['maternity', 'family-kids', 'brand-shoot', 'creative-portrait']
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}

s3 = boto3.client('s3', region_name=REGION)


def list_all(prefix):
    keys = []
    kwargs = {'Bucket': BUCKET, 'Prefix': prefix}
    while True:
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get('Contents', []):
            if not obj['Key'].endswith('/') and obj['Size'] > 0:
                keys.append(obj['Key'])
        if not resp.get('IsTruncated'):
            break
        kwargs['ContinuationToken'] = resp['NextContinuationToken']
    return keys


def copy_and_delete(src, dst):
    print(f"  {src}  →  {dst}")
    s3.copy_object(Bucket=BUCKET, Key=dst, CopySource={'Bucket': BUCKET, 'Key': src})
    s3.delete_object(Bucket=BUCKET, Key=src)


def is_image(key):
    return any(key.lower().endswith(ext) for ext in IMAGE_EXTS)


# ── Step 1: Migrate originals ─────────────────────────────────────────
print("\n=== Migrating originals/ ===")
originals = [k for k in list_all('originals/') if is_image(k)]
print(f"Found {len(originals)} original images")

filename_to_category = {}  # track which category each file ends up in

for i, key in enumerate(originals):
    category = CATEGORIES[i % len(CATEGORIES)]
    fname    = key.split('/')[-1]
    new_key  = f"gallery/{category}/originals/{fname}"
    copy_and_delete(key, new_key)
    filename_to_category[fname] = category

# ── Step 2: Migrate thumbnails ────────────────────────────────────────
print("\n=== Migrating thumbnails/ ===")
thumbnails = [k for k in list_all('thumbnails/') if is_image(k)]
print(f"Found {len(thumbnails)} thumbnails")

for key in thumbnails:
    fname    = key.split('/')[-1]
    category = filename_to_category.get(fname)
    if category:
        copy_and_delete(key, f"gallery/{category}/thumbnails/{fname}")
    else:
        print(f"  SKIP (no matching original): {key}")

# ── Step 3: Migrate display images ───────────────────────────────────
print("\n=== Migrating display/ ===")
display_imgs = [k for k in list_all('display/') if is_image(k)]
print(f"Found {len(display_imgs)} display images")

for key in display_imgs:
    fname    = key.split('/')[-1]
    category = filename_to_category.get(fname)
    if category:
        copy_and_delete(key, f"gallery/{category}/display/{fname}")
    else:
        print(f"  SKIP (no matching original): {key}")

# ── Summary ───────────────────────────────────────────────────────────
print("\n=== Summary ===")
from collections import Counter
counts = Counter(filename_to_category.values())
for cat, count in sorted(counts.items()):
    print(f"  {cat}: {count} photos")
print("\nMigration complete! Run backfill_thumbnails.py if any thumbnails are missing.")
