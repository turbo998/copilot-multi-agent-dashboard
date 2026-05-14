"""Blob snapshot cache with ETag-based change detection.

Supports two modes:
  - Azure Blob Storage via DefaultAzureCredential (account_url=https://...)
  - Local filesystem (account_url=file:///path/to/dir) for tests/dev
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


class BlobSnapshotCache:
    def __init__(
        self,
        account_url: str,
        container: str,
        cache_dir: str = '/tmp/agentdash-cache',
    ) -> None:
        self.account_url = account_url
        self.container = container
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._local_mode = account_url.startswith('file://')

        if self._local_mode:
            parsed = urlparse(account_url)
            # file:///abs/path -> parsed.path = /abs/path
            base = Path(parsed.path)
            self._local_root = base / container
            self._local_root.mkdir(parents=True, exist_ok=True)
            self._container_client = None
        else:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient

            self._credential = DefaultAzureCredential()
            self._service_client = BlobServiceClient(
                account_url=account_url, credential=self._credential
            )
            self._container_client = self._service_client.get_container_client(container)

    # ---- internal helpers ----
    def _local_path(self, blob_path: str) -> Path:
        return self._local_root / blob_path

    def _etag_path(self, local_filename: str) -> Path:
        return self.cache_dir / f"{local_filename}.etag.txt"

    # ---- public API ----
    def download_if_changed(self, blob_path: str, local_filename: str) -> Path:
        """Download blob to cache_dir/local_filename only if ETag changed.

        Returns the local cached path (may or may not exist if blob missing).
        """
        local = self.cache_dir / local_filename
        etag_file = self._etag_path(local_filename)
        prev_etag = etag_file.read_text().strip() if etag_file.exists() else None

        if self._local_mode:
            src = self._local_path(blob_path)
            if not src.exists():
                return local
            try:
                stat = src.stat()
                cur_etag = f"{stat.st_mtime_ns}-{stat.st_size}"
                if prev_etag == cur_etag and local.exists():
                    return local
                tmp = local.with_suffix(local.suffix + '.tmp')
                shutil.copyfile(src, tmp)
                os.replace(tmp, local)
                etag_file.write_text(cur_etag)
                return local
            except Exception as e:
                raise RuntimeError(f"local download failed for {blob_path}: {e}") from e

        # Azure mode
        try:
            blob_client = self._container_client.get_blob_client(blob_path)
            props = blob_client.get_blob_properties()
            cur_etag = props.etag
            if prev_etag == cur_etag and local.exists():
                return local
            tmp = local.with_suffix(local.suffix + '.tmp')
            with open(tmp, 'wb') as f:
                stream = blob_client.download_blob()
                f.write(stream.readall())
            os.replace(tmp, local)
            etag_file.write_text(cur_etag or '')
            return local
        except Exception as e:
            raise RuntimeError(f"blob download failed for {blob_path}: {e}") from e

    def upload(
        self,
        blob_path: str,
        content: bytes,
        content_type: str = 'application/json',
    ) -> None:
        if self._local_mode:
            try:
                dest = self._local_path(blob_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + '.tmp')
                with open(tmp, 'wb') as f:
                    f.write(content)
                os.replace(tmp, dest)
            except Exception as e:
                raise RuntimeError(f"local upload failed for {blob_path}: {e}") from e
            return

        try:
            from azure.storage.blob import ContentSettings

            blob_client = self._container_client.get_blob_client(blob_path)
            blob_client.upload_blob(
                content,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
        except Exception as e:
            raise RuntimeError(f"blob upload failed for {blob_path}: {e}") from e

    def read_text(self, blob_path: str) -> str:
        if self._local_mode:
            src = self._local_path(blob_path)
            if not src.exists():
                raise FileNotFoundError(f"missing blob {blob_path}")
            try:
                return src.read_text(encoding='utf-8')
            except Exception as e:
                raise RuntimeError(f"local read failed for {blob_path}: {e}") from e
        try:
            blob_client = self._container_client.get_blob_client(blob_path)
            data = blob_client.download_blob().readall()
            return data.decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"blob read failed for {blob_path}: {e}") from e

    def write_text(self, blob_path: str, text: str) -> None:
        self.upload(blob_path, text.encode('utf-8'), content_type='text/plain')

    def list_blobs(self, prefix: str = '') -> list[str]:
        """Return blob names under prefix."""
        if self._local_mode:
            root = self._local_root
            if prefix:
                base = root / prefix
                if not base.exists():
                    return []
                return [str(p.relative_to(root)) for p in base.rglob('*') if p.is_file()]
            return [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()]
        try:
            return [b.name for b in self._container_client.list_blobs(name_starts_with=prefix)]
        except Exception as e:
            raise RuntimeError(f"list_blobs failed for {prefix}: {e}") from e

    def exists(self, blob_path: str) -> bool:
        if self._local_mode:
            return self._local_path(blob_path).exists()
        try:
            return self._container_client.get_blob_client(blob_path).exists()
        except Exception:
            return False
