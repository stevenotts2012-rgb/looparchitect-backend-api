import os
import logging
from typing import BinaryIO
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import UploadFile

logger = logging.getLogger(__name__)

# Singleton R2 client
_r2_client = None

def get_r2_client():
    """Get or create singleton boto3 S3 client configured for Cloudflare R2."""
    global _r2_client
    
    if _r2_client is None:
        try:
            endpoint = os.environ["R2_ENDPOINT"]
            access_key_id = os.environ["R2_ACCESS_KEY_ID"]
            secret_access_key = os.environ["R2_ACCESS_KEY"]
            
            # Mask secrets in logs
            logger.info(f"Initializing R2 client with endpoint: {endpoint}")
            logger.info(f"Access Key ID: {access_key_id[:8]}...")
            
            config = Config(
                signature_version='s3v4',
                s3={'addressing_style': 'path'}
            )
            
            _r2_client = boto3.client(
                service_name='s3',
                endpoint_url=endpoint,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name='auto',
                config=config
            )
            
            logger.info("R2 client initialized successfully")
            
        except KeyError as e:
            raise ValueError(f"Missing required R2 environment variable: {e}")
    
    return _r2_client


def upload_uploadfile_to_r2(file: UploadFile, key: str) -> str:
    """
    Upload FastAPI UploadFile directly to Cloudflare R2.
    
    Args:
        file: FastAPI UploadFile object
        key: Object key (path) in R2 bucket
    
    Returns:
        str: Public URL to the uploaded file
    
    Raises:
        Exception: If upload fails
    """
    try:
        client = get_r2_client()
        bucket = os.environ["R2_BUCKET_NAME"]
        endpoint = os.environ["R2_ENDPOINT"]
        
        print(">>> USING R2 UPLOAD PATH <<<")
        print(f">>> R2 bucket={bucket} key={key} endpoint={endpoint}")
        
        # Reset stream to beginning
        file.file.seek(0)
        
        # Determine content type
        content_type = file.content_type or "application/octet-stream"
        
        logger.info(f"Uploading to R2: bucket={bucket}, key={key}, content_type={content_type}")
        
        # Upload to R2
        client.upload_fileobj(
            file.file,
            bucket,
            key,
            ExtraArgs={
                'ContentType': content_type
            }
        )
        
        logger.info(f"Successfully uploaded {key} to R2 bucket {bucket}")
        
        # Build public URL
        # If you have a custom domain in env, use it; otherwise use endpoint-based URL
        public_base = os.environ.get("R2_PUBLIC_BASE_URL")
        
        if public_base:
            url = f"{public_base.rstrip('/')}/{key}"
        else:
            # S3-style URL (requires public bucket or signed URLs for access)
            url = f"{endpoint.rstrip('/')}/{bucket}/{key}"
        
        print(f">>> R2 upload successful: {url}")
        return url
        
    except KeyError as e:
        error_msg = f"Missing R2 environment variable: {e}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except (ClientError, NoCredentialsError) as e:
        error_msg = f"R2 upload failed: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during R2 upload: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)