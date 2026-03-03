"""
AWS S3 Storage Service for Audio Files

Provides S3 upload, deletion, and presigned URL generation.
Falls back to local storage in development when S3 is not configured.
"""

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.config import settings

logger = logging.getLogger(__name__)


class S3StorageError(Exception):
    """Raised when S3 operations fail."""
    pass


class StorageNotConfiguredError(Exception):
    """Raised when S3 is not properly configured."""
    pass


class S3Storage:
    """AWS S3 storage service for audio files."""
    
    def __init__(self):
        """Initialize S3 client based on environment variables."""
        self.storage_backend = settings.get_storage_backend()
        self.bucket = settings.get_s3_bucket()
        self.access_key = settings.aws_access_key_id
        self.secret_key = settings.aws_secret_access_key
        self.region = settings.aws_region
        
        # Determine if S3 is configured
        self.use_s3 = self.storage_backend == "s3"
        
        if self.use_s3:
            missing = []
            if not self.bucket:
                missing.append("AWS_S3_BUCKET")
            if not self.access_key:
                missing.append("AWS_ACCESS_KEY_ID")
            if not self.secret_key:
                missing.append("AWS_SECRET_ACCESS_KEY")
            if not self.region:
                missing.append("AWS_REGION")
            if missing:
                raise StorageNotConfiguredError(
                    f"S3 backend selected but missing environment variables: {', '.join(missing)}"
                )
            self._init_s3_client()
            logger.info("Storage backend: s3 (bucket=%s, region=%s)", self.bucket, self.region)
        else:
            self._init_local_storage()
            logger.info("Storage backend: local")
    
    def _init_s3_client(self):
        """Initialize boto3 S3 client."""
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
            
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(signature_version='s3v4')
            )
            
            # Store ClientError for exception handling
            self.ClientError = ClientError
            
            logger.info("S3 client initialized successfully")
        except ImportError as e:
            logger.error("boto3 not installed. Install with: pip install boto3")
            raise StorageNotConfiguredError(
                "boto3 library not installed. Run: pip install boto3"
            ) from e
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise StorageNotConfiguredError(f"S3 initialization failed: {e}") from e
    
    def _init_local_storage(self):
        """Initialize local file storage as fallback."""
        self.upload_dir = Path("uploads")
        self.upload_dir.mkdir(exist_ok=True)
        logger.info(f"Local storage directory: {self.upload_dir.absolute()}")
    
    def upload_file(
        self,
        file_bytes: bytes,
        content_type: str,
        key: str
    ) -> str:
        """
        Upload a file to S3 or local storage.
        
        Args:
            file_bytes: Raw file bytes to upload
            content_type: MIME type (e.g., "audio/wav", "audio/mpeg")
            key: S3 key path (e.g., "uploads/abc123.wav")
        
        Returns:
            The S3 key (same as input key)
        
        Raises:
            S3StorageError: If upload fails
            StorageNotConfiguredError: If S3 is not configured (in production)
        """
        if self.use_s3:
            return self._upload_to_s3(file_bytes, content_type, key)
        else:
            return self._upload_to_local(file_bytes, key)
    
    def _upload_to_s3(self, file_bytes: bytes, content_type: str, key: str) -> str:
        """Upload file to S3."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
                ServerSideEncryption='AES256'  # Encrypt at rest
            )
            logger.info(f"✅ Uploaded to S3: s3://{self.bucket}/{key}")
            return key
        except self.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"S3 upload failed [{error_code}]: {error_msg}")
            raise S3StorageError(f"Failed to upload to S3: {error_msg}") from e
        except Exception as e:
            logger.error(f"Unexpected error during S3 upload: {e}")
            raise S3StorageError(f"Upload failed: {e}") from e
    
    def _upload_to_local(self, file_bytes: bytes, key: str) -> str:
        """Upload file to local storage (development fallback)."""
        try:
            # Extract filename from key (e.g., "uploads/file.wav" -> "file.wav")
            filename = key.split("/")[-1]
            file_path = self.upload_dir / filename
            
            # Diagnostic logging
            abs_path = file_path.absolute()
            logger.info(f"📝 Writing {len(file_bytes)} bytes to: {abs_path}")
            
            file_path.write_bytes(file_bytes)
            
            # Immediate verification
            if file_path.exists():
                actual_size = file_path.stat().st_size
                logger.info(f"✅ File written successfully: {actual_size} bytes at {abs_path}")
            else:
                logger.error(f"❌ CRITICAL: write_bytes() succeeded but file doesn't exist at {abs_path}")
            
            return key  # Return the same key format for consistency
        except Exception as e:
            logger.error(f"Local upload failed: {e}", exc_info=True)
            raise S3StorageError(f"Local upload failed: {e}") from e
    
    def delete_file(self, key: str) -> None:
        """
        Delete a file from S3 or local storage.
        
        Args:
            key: S3 key path (e.g., "uploads/abc123.wav")
        
        Raises:
            S3StorageError: If deletion fails (but not if file doesn't exist)
        """
        if self.use_s3:
            self._delete_from_s3(key)
        else:
            self._delete_from_local(key)
    
    def _delete_from_s3(self, key: str) -> None:
        """Delete file from S3."""
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket,
                Key=key
            )
            logger.info(f"🗑️ Deleted from S3: s3://{self.bucket}/{key}")
        except self.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            # Ignore 404 errors (file already deleted)
            if error_code == 'NoSuchKey':
                logger.warning(f"File already deleted: {key}")
                return
            
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"S3 delete failed [{error_code}]: {error_msg}")
            raise S3StorageError(f"Failed to delete from S3: {error_msg}") from e
        except Exception as e:
            logger.error(f"Unexpected error during S3 delete: {e}")
            raise S3StorageError(f"Delete failed: {e}") from e
    
    def _delete_from_local(self, key: str) -> None:
        """Delete file from local storage."""
        try:
            filename = key.split("/")[-1]
            file_path = self.upload_dir / filename
            
            if file_path.exists():
                file_path.unlink()
                logger.info(f"🗑️ Deleted locally: {file_path}")
            else:
                logger.warning(f"File not found for deletion: {file_path}")
        except Exception as e:
            logger.error(f"Local delete failed: {e}")
            raise S3StorageError(f"Local delete failed: {e}") from e
    
    def create_presigned_get_url(
        self,
        key: str,
        expires_seconds: int = 3600,
        download_filename: Optional[str] = None
    ) -> str:
        """
        Generate a presigned GET URL for downloading a file.
        
        Args:
            key: S3 key path (e.g., "uploads/abc123.wav")
            expires_seconds: URL expiration time in seconds (default: 3600 = 1 hour)
            download_filename: Optional filename for Content-Disposition header
                              (forces browser to download with this name)
        
        Returns:
            Presigned URL string (for S3) or local URL path (for local storage)
        
        Raises:
            S3StorageError: If presigned URL generation fails
        """
        if self.use_s3:
            return self._generate_s3_presigned_url(key, expires_seconds, download_filename)
        else:
            return self._generate_local_url(key)
    
    def _generate_s3_presigned_url(
        self,
        key: str,
        expires_seconds: int,
        download_filename: Optional[str]
    ) -> str:
        """Generate presigned S3 URL."""
        try:
            params = {
                'Bucket': self.bucket,
                'Key': key
            }
            
            # Add Content-Disposition for download with custom filename
            if download_filename:
                # URL-encode the filename for special characters
                encoded_filename = quote(download_filename)
                params['ResponseContentDisposition'] = f'attachment; filename="{encoded_filename}"'
            
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expires_seconds
            )
            
            logger.info(f"🔗 Generated presigned URL for: {key} (expires in {expires_seconds}s)")
            return url
        except self.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"Presigned URL generation failed [{error_code}]: {error_msg}")
            raise S3StorageError(f"Failed to generate presigned URL: {error_msg}") from e
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {e}")
            raise S3StorageError(f"Presigned URL generation failed: {e}") from e
    
    def _generate_local_url(self, key: str) -> str:
        """Generate local file URL (development fallback)."""
        # Extract filename from key
        filename = key.split("/")[-1]
        return f"/uploads/{filename}"
    
    def file_exists(self, key: str) -> bool:
        """
        Check if a file exists in storage.
        
        Args:
            key: S3 key path
        
        Returns:
            True if file exists, False otherwise
        """
        if self.use_s3:
            return self._s3_file_exists(key)
        else:
            return self._local_file_exists(key)
    
    def _s3_file_exists(self, key: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.s3_client.head_object(
                Bucket=self.bucket,
                Key=key
            )
            return True
        except self.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404' or error_code == 'NoSuchKey':
                return False
            # Re-raise other errors
            logger.error(f"Error checking file existence: {e}")
            raise
        except Exception:
            return False
    
    def _local_file_exists(self, key: str) -> bool:
        """Check if file exists locally."""
        filename = key.split("/")[-1]
        file_path = self.upload_dir / filename
        return file_path.exists()


# Global storage instance
storage = S3Storage()
