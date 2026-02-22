import os
import boto3
from botocore.config import Config
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from typing import BinaryIO, Optional

# Environment variables
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("R2_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")

def get_r2_client():
    """Initialize and return an S3 client configured for Cloudflare R2."""
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        raise ValueError(
            "Missing required R2 environment variables. "
            "Please set: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME"
        )
    
    # Configure for R2 compatibility
    config = Config(
        signature_version='s3v4',
        s3={'addressing_style': 'path'}
    )
    
    client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name='auto',
        config=config
    )
    
    return client

def upload_fileobj_to_r2(fileobj: BinaryIO, key: str, content_type: str) -> str:
    """
    Upload a file object to Cloudflare R2.
    
    Args:
        fileobj: File-like object to upload
        key: Object key (path) in the bucket (e.g., "uploads/filename.wav")
        content_type: MIME type of the file
    
    Returns:
        str: Public URL or object key depending on configuration
    
    Raises:
        Exception: If upload fails
    """
    try:
        client = get_r2_client()
        
        # Upload to R2
        client.upload_fileobj(
            fileobj,
            R2_BUCKET_NAME,
            key,
            ExtraArgs={
                'ContentType': content_type
            }
        )
        
        # Return public URL if configured, otherwise return the key
        if R2_PUBLIC_BASE_URL:
            # Ensure no double slashes
            base = R2_PUBLIC_BASE_URL.rstrip('/')
            return f"{base}/{key}"
        else:
            # Return key with a note that it's private
            return f"{key} (private - configure R2_PUBLIC_BASE_URL for public access)"
    
    except (NoCredentialsError, PartialCredentialsError) as e:
        raise Exception(f"R2 credentials error: {str(e)}")
    except ClientError as e:
        raise Exception(f"R2 upload failed: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error during R2 upload: {str(e)}")

def delete_from_r2(key: str) -> bool:
    """
    Delete an object from R2.
    
    Args:
        key: Object key to delete
    
    Returns:
        bool: True if successful
    """
    try:
        client = get_r2_client()
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
        return True
    except Exception as e:
        raise Exception(f"Failed to delete from R2: {str(e)}")