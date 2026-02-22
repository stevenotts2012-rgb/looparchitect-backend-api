import os
import boto3


def get_r2_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_ACCESS_KEY'],
        region_name='auto',
        endpoint_url=os.environ['R2_ENDPOINT'],
        config=boto3.session.Config(signature_version='s3v4')
    )


def upload_fileobj_to_r2(fileobj, key):
    client = get_r2_client()
    bucket_name = os.environ['R2_BUCKET_NAME']
    client.upload_fileobj(fileobj, bucket_name, key)


def build_public_r2_url(key):
    endpoint = os.environ['R2_ENDPOINT']
    bucket_name = os.environ['R2_BUCKET_NAME']
    return f'{endpoint}/{bucket_name}/{key}'
