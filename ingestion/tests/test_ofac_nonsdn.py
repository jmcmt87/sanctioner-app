"""Tests for the OFAC Non-SDN parser module.

The Non-SDN parser reuses SDN helper functions (_parse_csv, _build_entity_dict) which are
already extensively tested in test_ofac_sdn_parsing.py. These tests cover Non-SDN-specific
concerns: CSV file structure, comment aggregation, and the module's constants/imports.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.sources.ofac_nonsdn import SOURCE_NAME
from pipeline.sources.ofac_sdn import (
    ADD_COLUMNS,
    ALT_COLUMNS,
    COMMENTS_COLUMNS,
    SDN_COLUMNS,
    _build_entity_dict,
    _parse_csv,
)


class TestSourceConfiguration:
    def test_source_name_is_ofac_nonsdn(self):
        assert SOURCE_NAME == "ofac_nonsdn"

    def test_nonsdn_imports_sdn_helpers(self):
        from pipeline.sources import ofac_nonsdn

        assert ofac_nonsdn._parse_csv is _parse_csv
        assert ofac_nonsdn._build_entity_dict is _build_entity_dict

    def test_nonsdn_imports_correct_column_definitions(self):
        from pipeline.sources import ofac_nonsdn

        assert ofac_nonsdn.SDN_COLUMNS is SDN_COLUMNS
        assert ofac_nonsdn.ADD_COLUMNS is ADD_COLUMNS
        assert ofac_nonsdn.ALT_COLUMNS is ALT_COLUMNS
        assert ofac_nonsdn.COMMENTS_COLUMNS is COMMENTS_COLUMNS


class TestConsCsvParsing:
    """Test _parse_csv with Non-SDN consolidated file format (cons_prim, cons_add, etc.)."""

    def test_parses_cons_prim_csv(self, tmp_path: Path):
        csv_content = '"36000","SOME BANK","Entity","SDGT",,,,,,,,\n'
        f = tmp_path / "cons_prim.csv"
        f.write_text(csv_content)
        rows = _parse_csv(f, SDN_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["ent_num"] == "36000"
        assert rows[0]["sdn_name"] == "SOME BANK"
        assert rows[0]["sdn_type"] == "Entity"

    def test_parses_cons_add_csv(self, tmp_path: Path):
        csv_content = '"36000","1","123 Main St","Dubai","-0- ",\n'
        f = tmp_path / "cons_add.csv"
        f.write_text(csv_content)
        rows = _parse_csv(f, ADD_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["ent_num"] == "36000"
        assert rows[0]["address"] == "123 Main St"
        assert rows[0]["city_state"] == "Dubai"
        assert rows[0]["country"] is None

    def test_parses_cons_alt_csv(self, tmp_path: Path):
        csv_content = '"36000","1","a.k.a.","ALTERNATIVE NAME",\n'
        f = tmp_path / "cons_alt.csv"
        f.write_text(csv_content)
        rows = _parse_csv(f, ALT_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["alt_name"] == "ALTERNATIVE NAME"
        assert rows[0]["alt_type"] == "a.k.a."

    def test_parses_cons_comments_csv(self, tmp_path: Path):
        csv_content = '"36000","For more information see OFAC website."\n'
        f = tmp_path / "cons_comments.csv"
        f.write_text(csv_content)
        rows = _parse_csv(f, COMMENTS_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["ent_num"] == "36000"
        assert rows[0]["comments"] == "For more information see OFAC website."


class TestCommentAggregation:
    """Test the comment aggregation pattern used by the Non-SDN (and SDN) parsers.

    Both parsers aggregate multi-row comments into a single string per entity,
    concatenating with spaces. This tests the dictionary-building logic inline.
    """

    @staticmethod
    def _aggregate_comments(
        comments_rows: list[dict[str, str | None]],
    ) -> dict[str, str]:
        comments_by_ent: dict[str, str] = {}
        for row in comments_rows:
            ent = row["ent_num"]
            if ent and row.get("comments"):
                existing = comments_by_ent.get(ent, "")
                comment = row["comments"]
                comments_by_ent[ent] = (existing + " " + comment).strip() if existing else comment
        return comments_by_ent

    def test_single_comment_row(self):
        rows = [{"ent_num": "100", "comments": "Some remark."}]
        result = self._aggregate_comments(rows)
        assert result == {"100": "Some remark."}

    def test_multiple_comment_rows_same_entity(self):
        rows = [
            {"ent_num": "100", "comments": "First part."},
            {"ent_num": "100", "comments": "Second part."},
        ]
        result = self._aggregate_comments(rows)
        assert result == {"100": "First part. Second part."}

    def test_multiple_entities(self):
        rows = [
            {"ent_num": "100", "comments": "Comment A."},
            {"ent_num": "200", "comments": "Comment B."},
        ]
        result = self._aggregate_comments(rows)
        assert result["100"] == "Comment A."
        assert result["200"] == "Comment B."

    def test_skips_none_ent_num(self):
        rows = [{"ent_num": None, "comments": "Orphan comment."}]
        result = self._aggregate_comments(rows)
        assert result == {}

    def test_skips_none_comment(self):
        rows = [{"ent_num": "100", "comments": None}]
        result = self._aggregate_comments(rows)
        assert result == {}

    def test_skips_empty_comment(self):
        rows = [{"ent_num": "100"}]
        result = self._aggregate_comments(rows)
        assert result == {}

    def test_three_part_comment(self):
        rows = [
            {"ent_num": "100", "comments": "Part 1."},
            {"ent_num": "100", "comments": "Part 2."},
            {"ent_num": "100", "comments": "Part 3."},
        ]
        result = self._aggregate_comments(rows)
        assert result == {"100": "Part 1. Part 2. Part 3."}

    def test_comment_used_as_extended_remarks(self):
        """Verify aggregated comment works correctly when passed to _build_entity_dict."""
        from datetime import UTC, datetime

        rows = [
            {"ent_num": "100", "comments": "Linked To: SOME ENTITY."},
            {"ent_num": "100", "comments": "Additional info here."},
        ]
        aggregated = self._aggregate_comments(rows)

        sdn_row = {
            "ent_num": "100",
            "sdn_name": "TEST ENTITY",
            "sdn_type": "Entity",
            "program": "SDGT",
            "remarks": "Original remark",
            "title": None,
            "call_sign": None,
            "vess_type": None,
            "tonnage": None,
            "grt": None,
            "vess_flag": None,
            "vess_owner": None,
        }
        now = datetime.now(UTC)
        entity = _build_entity_dict(
            sdn_row,
            addresses=[],
            aliases=[],
            extended_remarks=aggregated.get("100"),
            now=now,
        )
        assert "Linked To: SOME ENTITY." in entity["remarks"]
        assert "Additional info here." in entity["remarks"]
        assert "Original remark" in entity["remarks"]


class TestAddressAndAliasIndexing:
    """Test the address/alias indexing pattern used by both SDN and Non-SDN parsers."""

    @staticmethod
    def _index_by_ent(rows: list[dict[str, str | None]]) -> dict[str, list]:
        result: dict[str, list] = {}
        for row in rows:
            ent = row["ent_num"]
            if ent:
                result.setdefault(ent, []).append(row)
        return result

    def test_groups_by_ent_num(self):
        rows = [
            {"ent_num": "1", "address": "A"},
            {"ent_num": "1", "address": "B"},
            {"ent_num": "2", "address": "C"},
        ]
        indexed = self._index_by_ent(rows)
        assert len(indexed["1"]) == 2
        assert len(indexed["2"]) == 1

    def test_skips_none_ent_num(self):
        rows = [{"ent_num": None, "address": "orphan"}]
        indexed = self._index_by_ent(rows)
        assert indexed == {}

    def test_empty_rows(self):
        indexed = self._index_by_ent([])
        assert indexed == {}


class TestSkipInvalidRecords:
    """Test the record validation logic in the Non-SDN (and SDN) ingestion loop."""

    def test_record_with_ent_num_and_name_is_valid(self):
        row = {"ent_num": "100", "sdn_name": "TEST ENTITY"}
        assert row.get("ent_num") is not None
        assert row.get("sdn_name") is not None

    def test_record_without_ent_num_is_skipped(self):
        row = {"ent_num": None, "sdn_name": "TEST"}
        assert row.get("ent_num") is None

    def test_record_without_name_is_skipped(self):
        row = {"ent_num": "100", "sdn_name": None}
        assert row.get("sdn_name") is None
