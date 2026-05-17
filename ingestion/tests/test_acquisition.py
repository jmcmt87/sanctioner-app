"""Unit tests for the data acquisition module.

Tests download logic, hash-based change detection, and audit trail
archiving. Uses httpx mock transport to avoid real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pipeline.acquisition import (
    _acquire_source_files,
    _archive_file,
    acquire_all_sources,
    acquire_eu_sanctions,
    acquire_ofac_nonsdn,
    acquire_ofac_sdn,
)
from pipeline.hashing import HashStore


class TestArchiveFile:
    def test_creates_timestamped_copy(self, tmp_path):
        from datetime import UTC, datetime

        source = tmp_path / "sdn.csv"
        source.write_text("entity data")
        archive_dir = tmp_path / "archive"

        ts = datetime(2026, 5, 14, 10, 30, 0, tzinfo=UTC)
        result = _archive_file(source, archive_dir, ts)

        assert result.exists()
        assert result.name == "20260514T103000Z_sdn.csv"
        assert result.read_text() == "entity data"

    def test_creates_archive_directory(self, tmp_path):
        from datetime import UTC, datetime

        source = tmp_path / "data.xml"
        source.write_text("<xml/>")
        archive_dir = tmp_path / "nested" / "archive"

        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = _archive_file(source, archive_dir, ts)

        assert archive_dir.exists()
        assert result.exists()


class TestAcquireSourceFiles:
    @pytest.fixture()
    def hash_store(self, tmp_path) -> HashStore:
        return HashStore(tmp_path / "hashes.json")

    async def test_downloads_all_files(self, tmp_path, hash_store):
        dest = tmp_path / "source"
        files = {
            "file1.csv": "http://example.com/file1.csv",
            "file2.csv": "http://example.com/file2.csv",
        }

        import pipeline.acquisition as acq

        responses = {"file1.csv": b"data1", "file2.csv": b"data2"}

        async def mock_download(client, url, max_retries=3):
            for suffix, content in responses.items():
                if suffix in url:
                    return content
            raise httpx.HTTPStatusError(
                "Not Found",
                request=httpx.Request("GET", url),
                response=httpx.Response(404),
            )

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _acquire_source_files("test_source", files, dest, hash_store)

        assert result.changed is True
        assert result.files_downloaded == 2
        assert (dest / "file1.csv").read_bytes() == b"data1"
        assert (dest / "file2.csv").read_bytes() == b"data2"

    async def test_unchanged_source_is_noop(self, tmp_path, hash_store):
        dest = tmp_path / "source"
        dest.mkdir()
        files = {"file1.csv": "http://example.com/file1.csv"}

        import pipeline.acquisition as acq

        async def mock_download(client, url, max_retries=3):
            return b"same_content"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            # First run: new source
            result1 = await _acquire_source_files("test", files, dest, hash_store)
            assert result1.changed is True

            # Second run: same content
            result2 = await _acquire_source_files("test", files, dest, hash_store)
            assert result2.changed is False

    async def test_partial_failure_still_downloads_others(self, tmp_path, hash_store):
        dest = tmp_path / "source"
        files = {
            "good.csv": "http://example.com/good.csv",
            "bad.csv": "http://example.com/bad.csv",
        }

        import pipeline.acquisition as acq

        call_count = 0

        async def mock_download(client, url, max_retries=3):
            nonlocal call_count
            call_count += 1
            if "bad.csv" in url:
                raise httpx.HTTPStatusError(
                    "Not Found",
                    request=httpx.Request("GET", url),
                    response=httpx.Response(404),
                )
            return b"good_data"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _acquire_source_files("test", files, dest, hash_store)

        assert result.files_downloaded == 1
        assert result.changed is True
        assert (dest / "good.csv").read_bytes() == b"good_data"

    async def test_all_failures_returns_unchanged(self, tmp_path, hash_store):
        dest = tmp_path / "source"
        files = {"bad.csv": "http://example.com/bad.csv"}

        import pipeline.acquisition as acq

        async def mock_download(client, url, max_retries=3):
            raise httpx.ConnectTimeout("timeout")

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _acquire_source_files("test", files, dest, hash_store)

        assert result.changed is False
        assert result.files_downloaded == 0

    async def test_archive_copies_created(self, tmp_path, hash_store):
        dest = tmp_path / "source"
        files = {"data.csv": "http://example.com/data.csv"}

        import pipeline.acquisition as acq

        async def mock_download(client, url, max_retries=3):
            return b"csv_data"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            await _acquire_source_files("test", files, dest, hash_store)

        archive_dir = dest / "archive"
        assert archive_dir.exists()
        archived_files = list(archive_dir.iterdir())
        assert len(archived_files) == 1
        assert archived_files[0].name.endswith("_data.csv")
        assert archived_files[0].read_bytes() == b"csv_data"


class TestAcquireSpecificSources:
    """Test the public source-specific functions pass correct parameters."""

    async def test_acquire_ofac_sdn_uses_correct_dir(self, tmp_path):
        import pipeline.acquisition as acq

        hash_store = HashStore(tmp_path / "h.json")

        async def mock_download(client, url, max_retries=3):
            return b"sdn_data"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await acquire_ofac_sdn(tmp_path, hash_store)

        assert result.source_name == "ofac_sdn"
        assert result.files_discovered == 4
        assert (tmp_path / "ofac_sdn" / "sdn.csv").exists()

    async def test_acquire_ofac_nonsdn_uses_correct_dir(self, tmp_path):
        import pipeline.acquisition as acq

        hash_store = HashStore(tmp_path / "h.json")

        async def mock_download(client, url, max_retries=3):
            return b"nonsdn_data"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await acquire_ofac_nonsdn(tmp_path, hash_store)

        assert result.source_name == "ofac_nonsdn"
        assert result.files_discovered == 4
        assert (tmp_path / "ofac_nonsdn" / "cons_prim.csv").exists()

    async def test_acquire_eu_sanctions_uses_correct_dir(self, tmp_path):
        import pipeline.acquisition as acq

        hash_store = HashStore(tmp_path / "h.json")

        async def mock_download(client, url, max_retries=3):
            return b"<xml>eu data</xml>"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await acquire_eu_sanctions(tmp_path, hash_store)

        assert result.source_name == "eu_consolidated"
        assert result.files_discovered == 1
        assert (tmp_path / "eu_consolidated" / "eu_sanctions_list.xml").exists()


class TestAcquireAllSources:
    async def test_acquires_all_three_sources(self, tmp_path):
        import pipeline.acquisition as acq

        async def mock_download(client, url, max_retries=3):
            return b"mock_data"

        with (
            patch.object(acq, "_download_with_retry", side_effect=mock_download),
            patch("pipeline.acquisition.asyncio.sleep", new_callable=AsyncMock),
            patch("pipeline.acquisition.httpx.AsyncClient") as mock_cls,
            patch.object(acq, "config", create=True),
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            results = await acquire_all_sources(tmp_path)

        assert len(results) == 3
        source_names = {r.source_name for r in results}
        assert source_names == {"ofac_sdn", "ofac_nonsdn", "eu_consolidated"}
        assert all(r.changed for r in results)
