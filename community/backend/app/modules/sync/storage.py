from __future__ import annotations

from functools import lru_cache
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@lru_cache
def client() -> S3Client:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def put_object(stream: SpooledTemporaryFile[bytes], key: str, mime_type: str) -> None:
    settings = get_settings()
    storage = client()
    try:
        storage.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
            raise
        try:
            if settings.s3_region == "us-east-1":
                storage.create_bucket(Bucket=settings.s3_bucket)
            else:
                storage.create_bucket(
                    Bucket=settings.s3_bucket,
                    CreateBucketConfiguration={
                        "LocationConstraint": settings.s3_region,  # type: ignore[typeddict-item]
                    },
                )
        except ClientError as creation_error:
            if creation_error.response.get("Error", {}).get("Code") != "BucketAlreadyOwnedByYou":
                raise
    stream.seek(0)
    storage.upload_fileobj(
        stream,
        settings.s3_bucket,
        key,
        ExtraArgs={"ContentType": mime_type},
    )
