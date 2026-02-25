"""
Storage service for handling file uploads and downloads.

Automatically detects environment and uses:
- Local file system in development
- AWS S3 in production (when configured)
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)


class StorageService:
    """Unified storage service supporting local and S3 backends."""

    def __init__(self):
        """Initialize storage service based on environment."""
        self.use_s3 = self._should_use_s3()
        
        if self.use_s3:
            self._init_s3()
        else:
            self._init_local()

    def _should_use_s3(self) -> bool:
        """Determine if S3 should be used based on environment variables."""
        bucket = os.getenv("AWS_S3_BUCKET")
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        
        # Use S3 if all required variables are present
        has_s3_config = all([bucket, access_key, secret_key])
        
        if has_s3_config:
            logger.info("✅ AWS S3 storage configured")
        else:
            logger.info("📁 Using local file storage")
        
        return has_s3_config

    def _init_s3(self):
        """Initialize S3 client."""
        try:
            import boto3
            from botocore.config import Config
            
            self.bucket_name = os.getenv("AWS_S3_BUCKET")
            self.region = os.getenv("AWS_REGION", "us-east-1")
            
            # Create S3 client with signature version v4
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=self.region,
                config=Config(signature_version='s3v4')
            )
            
            logger.info(f"S3 client initialized for bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to initialize S3: {e}")
            raise

    def _init_local(self):
        """Initialize local file storage."""
        self.upload_dir = Path("uploads")
        self.upload_dir.mkdir(exist_ok=True)
        logger.info(f"Local storage initialized at: {self.upload_dir}")

    def upload_file(
        self, 
        file_content: bytes, 
        filename: str, 
        content_type: str = "audio/wav"
    ) -> str:
        """
        Upload a file to storage.

        Args:
            file_content: Raw file bytes
            filename: Desired filename (should include extension)
            content_type: MIME type of the file

        Returns:
            File key/path that can be used for downloads

        Raises:
            Exception: If upload fails
        """
        if self.use_s3:
            return self._upload_to_s3(file_content, filename, content_type)
        else:
            return self._upload_to_local(file_content, filename)

    def _upload_to_s3(
        self, 
        file_content: bytes, 
        filename: str, 
        content_type: str
    ) -> str:
        """Upload file to S3."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=filename,
                Body=file_content,
                ContentType=content_type,
                ServerSideEncryption='AES256'  # Encrypt at rest
            )
            
            logger.info(f"Uploaded to S3: {filename}")
            return filename  # S3 key
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    def _upload_to_local(self, file_content: bytes, filename: str) -> str:
        """Upload file to local storage."""
        try:
            file_path = self.upload_dir / filename
            file_path.write_bytes(file_content)
            
            logger.info(f"Uploaded locally: {filename}")
            return f"/uploads/{filename}"  # URL path
        except Exception as e:
            logger.error(f"Local upload failed: {e}")
            raise

    def generate_download_url(
        self, 
        file_key: str, 
        expiration: int = 3600
    ) -> str:
        """
        Generate a download URL for a file.

        Args:
            file_key: File key/path returned from upload_file
            expiration: Seconds until URL expires (S3 only)

        Returns:
            Download URL (signed for S3, direct path for local)
        """
        if self.use_s3:
            return self._generate_s3_url(file_key, expiration)
        else:
            return self._generate_local_url(file_key)

    def _generate_s3_url(self, file_key: str, expiration: int) -> str:
        """Generate presigned S3 URL."""
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': file_key
                },
                ExpiresIn=expiration
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate S3 URL: {e}")
            raise

    def _generate_local_url(self, file_key: str) -> str:
        """Generate local file URL."""
        # If already a URL path, return as-is
        if file_key.startswith("/uploads/"):
            return file_key
        
        # If it's just a filename, prepend /uploads/
        filename = file_key.split("/")[-1]
        return f"/uploads/{filename}"

    def delete_file(self, file_key: str) -> bool:
        """
        Delete a file from storage.

        Args:
            file_key: File key/path to delete

        Returns:
            True if successful, False otherwise
        """
        if self.use_s3:
            return self._delete_from_s3(file_key)
        else:
            return self._delete_from_local(file_key)

    def _delete_from_s3(self, file_key: str) -> bool:
        """Delete file from S3."""
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            logger.info(f"Deleted from S3: {file_key}")
            return True
        except Exception as e:
            logger.error(f"S3 delete failed: {e}")
            return False

    def _delete_from_local(self, file_key: str) -> bool:
        """Delete file from local storage."""
        try:
            # Extract filename from URL path if needed
            filename = file_key.replace("/uploads/", "")
            file_path = self.upload_dir / filename
            
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Deleted locally: {filename}")
                return True
            else:
                logger.warning(f"File not found: {filename}")
                return False
        except Exception as e:
            logger.error(f"Local delete failed: {e}")
            return False

    def file_exists(self, file_key: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            file_key: File key/path to check

        Returns:
            True if file exists, False otherwise
        """
        if self.use_s3:
            return self._s3_file_exists(file_key)
        else:
            return self._local_file_exists(file_key)

    def _s3_file_exists(self, file_key: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            return True
        except:
            return False

    def _local_file_exists(self, file_key: str) -> bool:
        """Check if file exists locally."""
        filename = file_key.replace("/uploads/", "")
        file_path = self.upload_dir / filename
        return file_path.exists()

    def get_file_path(self, file_key: str) -> Optional[Path]:
        """
        Get local file path (local storage only).

        Args:
            file_key: File key/path

        Returns:
            Path object if local storage, None if S3
        """
        if self.use_s3:
            return None
        
        filename = file_key.replace("/uploads/", "")
        return self.upload_dir / filename

    def get_file_stream(self, file_key: str):
        """
        Get a file stream for audio streaming.

        Args:
            file_key: File key/path

        Returns:
            File-like object for streaming

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: For S3 errors
        """
        if self.use_s3:
            return self._get_s3_stream(file_key)
        else:
            return self._get_local_stream(file_key)

    def _get_s3_stream(self, file_key: str):
        """Get streaming object from S3."""
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            return response['Body']
        except Exception as e:
            logger.error(f"Failed to get S3 stream: {e}")
            raise

    def _get_local_stream(self, file_key: str):
        """Get streaming object from local file."""
        filename = file_key.replace("/uploads/", "")
        file_path = self.upload_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filename}")
        
        return open(file_path, 'rb')


# Global storage service instance
storage_service = StorageService()
