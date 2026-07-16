"""Object storage: S3-compatible or local filesystem fallback."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger("storage")


class StorageError(AppError):
    pass


class ObjectStorage:
    """Unified put/get/delete for S3 or local disk."""

    def __init__(self) -> None:
        self.backend = settings.storage_backend
        self._client = None
        if self.backend == "s3":
            try:
                import boto3
                from botocore.client import Config

                kwargs = {
                    "service_name": "s3",
                    "aws_access_key_id": settings.s3_access_key_id,
                    "aws_secret_access_key": settings.s3_secret_access_key,
                    "region_name": settings.s3_region or "auto",
                }
                if settings.s3_endpoint_url.strip():
                    kwargs["endpoint_url"] = settings.s3_endpoint_url.strip()
                    kwargs["config"] = Config(signature_version="s3v4")
                self._client = boto3.client(**kwargs)
                self.bucket = settings.s3_bucket_name
            except Exception as exc:  # noqa: BLE001
                raise StorageError(f"Failed to init S3 client: {exc}") from exc
        else:
            self.root = Path(settings.local_storage_dir).resolve()
            self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        key = key.lstrip("/")
        if self.backend == "s3":
            try:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
            except Exception as exc:  # noqa: BLE001
                raise StorageError(f"S3 put failed: {exc}") from exc
            logger.info("s3 put key=%s bytes=%s", key, len(data))
            return key

        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info("local put key=%s bytes=%s", key, len(data))
        return key

    def get_bytes(self, key: str) -> bytes:
        key = key.lstrip("/")
        if self.backend == "s3":
            try:
                obj = self._client.get_object(Bucket=self.bucket, Key=key)
                return obj["Body"].read()
            except Exception as exc:  # noqa: BLE001
                raise StorageError(f"S3 get failed: {exc}") from exc

        path = self.root / key
        if not path.exists():
            raise StorageError(f"File not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        key = key.lstrip("/")
        if self.backend == "s3":
            try:
                self._client.delete_object(Bucket=self.bucket, Key=key)
            except Exception as exc:  # noqa: BLE001
                raise StorageError(f"S3 delete failed: {exc}") from exc
            return
        path = self.root / key
        if path.exists():
            path.unlink()

    def health_check(self) -> bool:
        try:
            if self.backend == "s3":
                self._client.head_bucket(Bucket=self.bucket)
                return True
            self.root.mkdir(parents=True, exist_ok=True)
            return self.root.exists()
        except Exception as exc:  # noqa: BLE001
            logger.warning("storage health failed: %s", exc)
            return False


def get_storage() -> ObjectStorage:
    return ObjectStorage()
