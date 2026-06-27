# AWS Deployment & S3 Storage Ingestion Guide

This document describes the step-by-step procedure to deploy the containerized StreamForge application on an AWS EC2 instance and integrate video storage with an AWS S3 bucket.

---

## Part 1: S3 Ingestion Configuration

To route raw video uploads, transcoded HLS streams, thumbnails, and sprites directly to AWS S3, configure the django-storages backend.

### 1. Production Settings Setup
Add the following blocks to streamforge/settings.py under production configurations:

```python
# Installed apps check
INSTALLED_APPS += [
    'storages',
]

# AWS Credentials
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')

# S3 Custom Domain
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

# Storage Backend Routing
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
```

### 2. IAM Policy Setup
Grant the EC2 instance or S3 API User the following S3 access policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:ListBucket",
                "s3:PutObjectAcl"
            ],
            "Resource": [
                "arn:aws:s3:::your-bucket-name",
                "arn:aws:s3:::your-bucket-name/*"
            ]
        }
    ]
}
```

---

## Part 2: AWS EC2 Instance Deployment

Follow these commands to deploy the containerized environment on a clean Ubuntu EC2 instance:

### Step 1: Prepare Instance
Connect to the server via SSH:
```bash
ssh -i your-key.pem ubuntu@your-instance-ip
```

### Step 2: Install Docker Engine & Compose
Update packages and download Docker:
```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y docker.io curl
sudo systemctl enable --now docker

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### Step 3: Clone Code & Configure Environment
Clone the repository, create an `.env` file in the root directory to store variables, and configure AWS keys:
```bash
git clone https://github.com/senku1505/StreamForge.git
cd StreamForge

# Setup environment variables
cat <<EOF > .env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_STORAGE_BUCKET_NAME=your_s3_bucket_name
AWS_S3_REGION_NAME=us-east-1
CELERY_BROKER_URL=redis://redis:6379/0
EOF
```

### Step 4: Launch Containerized Pipeline
Run Docker Compose in detached mode to pull images, build the containers, and run the pipeline:
```bash
sudo docker-compose up --build -d
```

### Step 5: Verify Containers Status
Verify that all services (Django web container, Redis server, and Celery transcode workers) are running:
```bash
sudo docker-compose ps
```
The application will be accessible on port 8000.
