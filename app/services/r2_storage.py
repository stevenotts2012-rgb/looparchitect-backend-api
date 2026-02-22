import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

def upload_to_r2(bucket_name, object_name, file_data):
    # Use the Cloudflare R2 endpoint and credentials
    r2_client = boto3.client(
        's3',
        endpoint_url='https://<account-id>.r2.cloudflarestorage.com',  # Replace <account-id> with your Cloudflare Account ID
        aws_access_key_id='<access-key>',  # Replace with your Cloudflare R2 access key
        aws_secret_access_key='<secret-key>'  # Replace with your Cloudflare R2 secret key
    )
    
    try:
        r2_client.put_object(Bucket=bucket_name, Key=object_name, Body=file_data)
        print(f'Successfully uploaded {object_name} to {bucket_name}')
    except (NoCredentialsError, PartialCredentialsError) as e:
        print(f'Credentials error: {e}')
    except Exception as e:
        print(f'Error occurred: {e}')

if __name__ == '__main__':
    # Example usage
    upload_to_r2('your-bucket-name', 'your-object-name', b'file content')
