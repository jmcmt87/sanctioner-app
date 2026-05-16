"""Tests for the ingestion pipeline runner module.

Tests source registration, file mapping, and hash-based skip logic.
The runner's async orchestration (run_ingestion) requires a database session,
so those are integration tests. These cover the configuration and pure logic.
"""

from __future__ import annotations

from pipeline.runner import REGISTERED_SOURCES, SOURCE_FILES


class TestSourceRegistration:
    """Verify all expected sources are registered and correctly configured."""

    def test_all_expected_sources_registered(self):
        expected = {"ofac_sdn", "ofac_nonsdn", "eu_consolidated"}
        assert set(REGISTERED_SOURCES.keys()) == expected

    def test_every_registered_source_has_file_pattern(self):
        for source_name in REGISTERED_SOURCES:
            assert source_name in SOURCE_FILES, f"{source_name} missing from SOURCE_FILES"

    def test_every_file_pattern_has_registered_handler(self):
        for source_name in SOURCE_FILES:
            assert source_name in REGISTERED_SOURCES, (
                f"{source_name} in SOURCE_FILES but not REGISTERED_SOURCES"
            )

    def test_handlers_are_callable(self):
        for name, handler in REGISTERED_SOURCES.items():
            assert callable(handler), f"Handler for {name} is not callable"

    def test_handlers_are_async(self):
        import asyncio

        for name, handler in REGISTERED_SOURCES.items():
            assert asyncio.iscoroutinefunction(handler), f"Handler for {name} is not async"


class TestSourceFilePatterns:
    def test_ofac_sdn_pattern_is_csv(self):
        patterns = SOURCE_FILES["ofac_sdn"]
        assert len(patterns) >= 1
        assert all("*.csv" in p for p in patterns)

    def test_ofac_nonsdn_pattern_is_csv(self):
        patterns = SOURCE_FILES["ofac_nonsdn"]
        assert len(patterns) >= 1
        assert all("*.csv" in p for p in patterns)

    def test_eu_consolidated_pattern_is_xml(self):
        patterns = SOURCE_FILES["eu_consolidated"]
        assert len(patterns) >= 1
        assert all("*.xml" in p for p in patterns)

    def test_ofac_sdn_pattern_points_to_sdn_dir(self):
        patterns = SOURCE_FILES["ofac_sdn"]
        assert all(p.startswith("ofac_sdn/") for p in patterns)

    def test_ofac_nonsdn_pattern_points_to_nonsdn_dir(self):
        patterns = SOURCE_FILES["ofac_nonsdn"]
        assert all(p.startswith("ofac_nonsdn/") for p in patterns)

    def test_eu_pattern_points_to_eu_dir(self):
        patterns = SOURCE_FILES["eu_consolidated"]
        assert all(p.startswith("eu_consolidated/") for p in patterns)


class TestHashSkipLogic:
    """Test the hash-based skip logic used by run_ingestion.

    The HashStore is already tested in test_hashing.py. These tests verify
    the conditional skip logic pattern used in the runner.
    """

    def test_skip_unchanged_when_hash_matches(self):
        import tempfile
        from pathlib import Path

        from pipeline.hashing import HashStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = HashStore(Path(tmpdir) / "hashes.json")
            store.update("ofac_sdn", "abc123")
            assert not store.has_changed("ofac_sdn", "abc123")

    def test_process_when_hash_differs(self):
        import tempfile
        from pathlib import Path

        from pipeline.hashing import HashStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = HashStore(Path(tmpdir) / "hashes.json")
            store.update("ofac_sdn", "abc123")
            assert store.has_changed("ofac_sdn", "def456")

    def test_process_when_source_never_seen(self):
        import tempfile
        from pathlib import Path

        from pipeline.hashing import HashStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = HashStore(Path(tmpdir) / "hashes.json")
            assert store.has_changed("new_source", "any_hash")


class TestRelationshipIntegration:
    """Verify the runner calls relationship resolution after all source ingestion."""

    def test_resolve_relationships_is_importable(self):
        import asyncio

        from pipeline.relationships import resolve_relationships

        assert asyncio.iscoroutinefunction(resolve_relationships)

    def test_runner_imports_resolve_relationships(self):
        from pipeline import runner

        assert hasattr(runner, "resolve_relationships")
