"""Unit tests for relationship extraction from OFAC remarks.

Tests the regex extraction logic and alias deduplication in upsert.
No database or I/O required -- pure parsing logic.
"""

from __future__ import annotations

from pipeline.relationships import LINKED_TO_RE, extract_linked_names

# ── Regex pattern tests ────────────────────────────────────────────────────


class TestLinkedToRegex:
    """Test LINKED_TO_RE regex directly against individual patterns."""

    def test_period_terminated(self):
        text = "Linked To: VTB BANK PUBLIC JOINT STOCK COMPANY."
        matches = LINKED_TO_RE.findall(text)
        assert matches == ["VTB BANK PUBLIC JOINT STOCK COMPANY"]

    def test_semicolon_terminated(self):
        text = "Linked To: SOME ENTITY NAME;"
        matches = LINKED_TO_RE.findall(text)
        assert matches == ["SOME ENTITY NAME"]

    def test_source_id_stripped(self):
        text = "Linked To: SOME ENTITY, source_id 12345."
        matches = LINKED_TO_RE.findall(text)
        assert matches == ["SOME ENTITY"]

    def test_end_of_string(self):
        text = "Linked To: FINAL ENTITY"
        matches = LINKED_TO_RE.findall(text)
        assert matches == ["FINAL ENTITY"]

    def test_no_match(self):
        text = "No relationship info here"
        matches = LINKED_TO_RE.findall(text)
        assert matches == []


# ── extract_linked_names tests ─────────────────────────────────────────────


class TestExtractLinkedNames:
    def test_single_link_period(self):
        remarks = "Linked To: VTB BANK PUBLIC JOINT STOCK COMPANY."
        assert extract_linked_names(remarks) == ["VTB BANK PUBLIC JOINT STOCK COMPANY"]

    def test_multiple_links(self):
        remarks = "Linked To: ENTITY ONE; Linked To: ENTITY TWO."
        result = extract_linked_names(remarks)
        assert result == ["ENTITY ONE", "ENTITY TWO"]

    def test_source_id_stripped(self):
        remarks = "Linked To: SOME ENTITY, source_id 12345."
        assert extract_linked_names(remarks) == ["SOME ENTITY"]

    def test_no_linked_to(self):
        remarks = "No relationship info here"
        assert extract_linked_names(remarks) == []

    def test_empty_string(self):
        assert extract_linked_names("") == []

    def test_mixed_terminators(self):
        remarks = (
            "Some preamble. Linked To: ALPHA CORP; "
            "Linked To: BETA LLC, source_id 999. "
            "Linked To: GAMMA INC."
        )
        result = extract_linked_names(remarks)
        assert result == ["ALPHA CORP", "BETA LLC", "GAMMA INC"]

    def test_whitespace_stripped(self):
        remarks = "Linked To:   PADDED NAME  ."
        result = extract_linked_names(remarks)
        assert result == ["PADDED NAME"]


# ── Alias deduplication tests (pure logic, no DB) ─────────────────────────


class TestAliasDeduplication:
    """Test the deduplication logic used in upsert.py for aliases.

    Verifies the set-based dedup approach: (alias_name.lower(), alias_type).
    """

    @staticmethod
    def _deduplicate(aliases: list[dict]) -> list[dict]:
        """Replicate the deduplication logic from upsert.py."""
        seen: set[tuple[str, str | None]] = set()
        result = []
        for alias in aliases:
            alias_name = alias.get("alias_name")
            if alias_name:
                key = (alias_name.lower(), alias.get("alias_type"))
                if key not in seen:
                    seen.add(key)
                    result.append(alias)
        return result

    def test_exact_duplicates_removed(self):
        aliases = [
            {"alias_name": "ALPHA CORP", "alias_type": "aka"},
            {"alias_name": "ALPHA CORP", "alias_type": "aka"},
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 1
        assert result[0]["alias_name"] == "ALPHA CORP"

    def test_case_insensitive_dedup(self):
        aliases = [
            {"alias_name": "Alpha Corp", "alias_type": "aka"},
            {"alias_name": "ALPHA CORP", "alias_type": "aka"},
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 1
        # First occurrence wins
        assert result[0]["alias_name"] == "Alpha Corp"

    def test_different_types_kept(self):
        aliases = [
            {"alias_name": "ALPHA CORP", "alias_type": "aka"},
            {"alias_name": "ALPHA CORP", "alias_type": "fka"},
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 2

    def test_none_type_dedup(self):
        aliases = [
            {"alias_name": "ALPHA CORP", "alias_type": None},
            {"alias_name": "ALPHA CORP", "alias_type": None},
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 1

    def test_empty_name_skipped(self):
        aliases = [
            {"alias_name": "", "alias_type": "aka"},
            {"alias_name": "REAL NAME", "alias_type": "aka"},
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 1
        assert result[0]["alias_name"] == "REAL NAME"

    def test_none_name_skipped(self):
        aliases = [
            {"alias_type": "aka"},
            {"alias_name": None, "alias_type": "aka"},
            {"alias_name": "REAL NAME", "alias_type": "aka"},
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 1

    def test_mixed_duplicates_and_unique(self):
        aliases = [
            {"alias_name": "ALPHA", "alias_type": "aka"},
            {"alias_name": "BETA", "alias_type": "aka"},
            {"alias_name": "alpha", "alias_type": "aka"},  # duplicate of ALPHA
            {"alias_name": "GAMMA", "alias_type": "fka"},
            {"alias_name": "BETA", "alias_type": "fka"},  # different type, kept
        ]
        result = self._deduplicate(aliases)
        assert len(result) == 4
        names = [a["alias_name"] for a in result]
        assert names == ["ALPHA", "BETA", "GAMMA", "BETA"]
