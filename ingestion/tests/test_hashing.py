"""Unit tests for the hashing module (change detection).

Tests pure functions and the HashStore file-based persistence.
No DB or external services needed.
"""

from __future__ import annotations

from datetime import UTC

from pipeline.hashing import HashStore, compute_file_hash, compute_record_hash, compute_source_hash


class TestComputeRecordHash:
    def test_deterministic(self):
        record = {"name": "Sberbank", "source": "ofac_sdn"}
        assert compute_record_hash(record) == compute_record_hash(record)

    def test_key_order_independent(self):
        r1 = {"a": 1, "b": 2}
        r2 = {"b": 2, "a": 1}
        assert compute_record_hash(r1) == compute_record_hash(r2)

    def test_different_records_different_hashes(self):
        r1 = {"name": "Sberbank"}
        r2 = {"name": "Gazprombank"}
        assert compute_record_hash(r1) != compute_record_hash(r2)

    def test_handles_non_string_values(self):
        from datetime import datetime

        record = {"ts": datetime(2026, 1, 1, tzinfo=UTC), "count": 42}
        h = compute_record_hash(record)
        assert isinstance(h, str)
        assert len(h) == 64


class TestComputeFileHash:
    def test_hashes_file_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = compute_file_hash(f)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("same content")
        f2.write_text("same content")
        assert compute_file_hash(f1) == compute_file_hash(f2)


class TestComputeSourceHash:
    def test_combines_file_hashes(self, tmp_path):
        subdir = tmp_path / "ofac_sdn"
        subdir.mkdir()
        (subdir / "sdn.csv").write_text("data1")
        (subdir / "add.csv").write_text("data2")

        h = compute_source_hash(tmp_path, ["ofac_sdn/*.csv"])
        assert isinstance(h, str)
        assert len(h) == 64

    def test_changes_when_file_changes(self, tmp_path):
        subdir = tmp_path / "ofac_sdn"
        subdir.mkdir()
        f = subdir / "sdn.csv"
        f.write_text("version1")

        h1 = compute_source_hash(tmp_path, ["ofac_sdn/*.csv"])

        f.write_text("version2")
        h2 = compute_source_hash(tmp_path, ["ofac_sdn/*.csv"])

        assert h1 != h2

    def test_empty_when_no_files_match(self, tmp_path):
        h = compute_source_hash(tmp_path, ["nonexistent/*.csv"])
        assert isinstance(h, str)


class TestHashStore:
    def test_new_source_is_changed(self, tmp_path):
        store = HashStore(tmp_path / "hashes.json")
        assert store.has_changed("ofac_sdn", "abc123")

    def test_same_hash_is_unchanged(self, tmp_path):
        store = HashStore(tmp_path / "hashes.json")
        store.update("ofac_sdn", "abc123")
        assert not store.has_changed("ofac_sdn", "abc123")

    def test_different_hash_is_changed(self, tmp_path):
        store = HashStore(tmp_path / "hashes.json")
        store.update("ofac_sdn", "abc123")
        assert store.has_changed("ofac_sdn", "def456")

    def test_persists_to_disk(self, tmp_path):
        store_path = tmp_path / "hashes.json"
        store1 = HashStore(store_path)
        store1.update("ofac_sdn", "abc123")

        store2 = HashStore(store_path)
        assert not store2.has_changed("ofac_sdn", "abc123")

    def test_handles_missing_file(self, tmp_path):
        store = HashStore(tmp_path / "nonexistent" / "hashes.json")
        assert store.has_changed("ofac_sdn", "abc123")

    def test_multiple_sources_independent(self, tmp_path):
        store = HashStore(tmp_path / "hashes.json")
        store.update("ofac_sdn", "hash1")
        store.update("eu_consolidated", "hash2")

        assert not store.has_changed("ofac_sdn", "hash1")
        assert not store.has_changed("eu_consolidated", "hash2")
        assert store.has_changed("ofac_sdn", "different")
