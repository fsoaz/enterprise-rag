"""S3 / MinIO object storage helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from uuid import UUID

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError


@lru_cache(maxsize=1)
def _client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )


def bucket_name() -> str:
    return os.environ.get("S3_BUCKET", "enterprise-rag")


def storage_key(*, tenant_id: UUID, document_id: UUID, version_id: UUID, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_") or "blob"
    return f"{tenant_id}/{document_id}/{version_id}/{safe_name}"


def put_object(*, key: str, body: bytes, content_type: str) -> None:
    _client().put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def get_object_bytes(*, key: str) -> bytes:
    try:
        response: dict[str, Any] = _client().get_object(Bucket=bucket_name(), Key=key)
    except ClientError as exc:
        msg = f"object not found: {key}"
        raise FileNotFoundError(msg) from exc
    return bytes(response["Body"].read())


def ensure_bucket() -> None:
    client = _client()
    name = bucket_name()
    try:
        client.head_bucket(Bucket=name)
    except ClientError:
        client.create_bucket(Bucket=name)
