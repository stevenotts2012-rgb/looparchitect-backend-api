import os
import boto3
from botocore.config import Config

def get_r2_client():
    """Creates a reusable R2 client."""
    r2_access_key_id = os.getenv('R2_ACCESS_KEY_ID')
    r2_access_key = os.getenv('R2_ACCESS_KEY')
    r2_endpoint = os.getenv('R2_ENDPOINT')

    return boto3.client(
        's3',
        aws_access_key_id=r2_access_key_id,
        aws_secret_access_key=r2_access_key,
        endpoint_url=r2_endpoint,
        config=Config(signature_version='s3v4', region_name='auto')
    )

def upload_fileobj_to_r2(fileobj, bucket, key, content_type):
    """Uploads a file object to the R2 bucket and returns the public URL."""
    client = get_r2_client()
    client.upload_fileobj(fileobj, bucket, key, ExtraArgs={'ContentType': content_type})
    return build_public_r2_url(bucket, key)

def build_public_r2_url(bucket, key):
    """Constructs the public URL for the R2 object."""
    return f'https://{bucket}.{os.getenv('R2_ENDPOINT')}/{key}'
