"""Unit tests for OFAC SDN CSV parsing functions.

Tests pure parsing logic (no DB, no I/O). These are the most critical ingestion
tests — if parsing is wrong, every entity in the database is wrong.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pipeline.sources.ofac_sdn import (
    _build_entity_dict,
    _clean,
    _normalize_entity_type,
    _parse_csv,
    _parse_dob,
    _parse_identifiers,
    _parse_nationalities,
    _parse_programs,
)

# ── _clean ──────────────────────────────────────────────────────────────────


class TestClean:
    def test_strips_whitespace(self):
        assert _clean("  hello  ") == "hello"

    def test_strips_quotes(self):
        assert _clean('"some value"') == "some value"

    def test_null_sentinel_returns_none(self):
        assert _clean("-0- ") is None

    def test_empty_string_returns_none(self):
        assert _clean("") is None
        assert _clean("   ") is None

    def test_normal_value(self):
        assert _clean("Sberbank") == "Sberbank"


# ── _parse_csv ──────────────────────────────────────────────────────────────


class TestParseCsv:
    def test_parses_basic_csv(self, tmp_path):
        csv_content = (
            '"12345","SBERBANK","Entity","RUSSIA-EO14024","","","","","","","","some remark"\n'
        )
        csv_file = tmp_path / "sdn.csv"
        csv_file.write_text(csv_content)

        from pipeline.sources.ofac_sdn import SDN_COLUMNS

        rows = _parse_csv(csv_file, SDN_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["ent_num"] == "12345"
        assert rows[0]["sdn_name"] == "SBERBANK"
        assert rows[0]["sdn_type"] == "Entity"
        assert rows[0]["remarks"] == "some remark"

    def test_skips_empty_lines(self, tmp_path):
        csv_content = '"12345","TEST","Entity","PROG","","","","","","","",""\n\n'
        csv_file = tmp_path / "sdn.csv"
        csv_file.write_text(csv_content)

        from pipeline.sources.ofac_sdn import SDN_COLUMNS

        rows = _parse_csv(csv_file, SDN_COLUMNS)
        assert len(rows) == 1

    def test_handles_short_rows(self, tmp_path):
        csv_content = '"12345","TEST"\n'
        csv_file = tmp_path / "sdn.csv"
        csv_file.write_text(csv_content)

        from pipeline.sources.ofac_sdn import SDN_COLUMNS

        rows = _parse_csv(csv_file, SDN_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["ent_num"] == "12345"
        assert rows[0]["sdn_name"] == "TEST"
        assert rows[0]["remarks"] is None

    def test_null_sentinel_converted_to_none(self, tmp_path):
        csv_content = '"12345","-0- ","Entity","PROG","","","","","","","",""\n'
        csv_file = tmp_path / "sdn.csv"
        csv_file.write_text(csv_content)

        from pipeline.sources.ofac_sdn import SDN_COLUMNS

        rows = _parse_csv(csv_file, SDN_COLUMNS)
        assert rows[0]["sdn_name"] is None


# ── _parse_dob ──────────────────────────────────────────────────────────────


class TestParseDob:
    def test_full_date(self):
        assert _parse_dob("DOB 15 Mar 1970") == date(1970, 3, 15)

    def test_year_only(self):
        assert _parse_dob("DOB 1985") == date(1985, 1, 1)

    def test_no_dob_returns_none(self):
        assert _parse_dob("nationality Russia") is None

    def test_full_date_in_remarks_context(self):
        remarks = "DOB 03 Nov 1959; POB Moscow, Russia; nationality Russia"
        assert _parse_dob(remarks) == date(1959, 11, 3)

    def test_invalid_date_falls_back_to_year(self):
        assert _parse_dob("DOB 31 Feb 1990; DOB 1990") == date(1990, 1, 1)

    def test_empty_string(self):
        assert _parse_dob("") is None

    def test_multiple_dobs_takes_first(self):
        remarks = "DOB 01 Jan 1980; DOB 15 Jun 1985"
        assert _parse_dob(remarks) == date(1980, 1, 1)


# ── _parse_nationalities ───────────────────────────────────────────────────


class TestParseNationalities:
    def test_single_nationality(self):
        result = _parse_nationalities("nationality Russia")
        assert result == ["Russia"]

    def test_multiple_nationalities(self):
        result = _parse_nationalities("nationality Russia; nationality Ukraine")
        assert result == ["Russia", "Ukraine"]

    def test_no_nationality(self):
        result = _parse_nationalities("DOB 1970; some other remarks")
        assert result == []

    def test_nationality_with_trailing_semicolon(self):
        result = _parse_nationalities("nationality Russia; DOB 1970")
        assert result == ["Russia"]


# ── _parse_programs ─────────────────────────────────────────────────────────


class TestParsePrograms:
    def test_single_program(self):
        assert _parse_programs("RUSSIA-EO14024") == ["RUSSIA-EO14024"]

    def test_multiple_programs(self):
        result = _parse_programs("IRAN] [SDGT] [IRGC")
        assert "IRAN" in result
        assert "SDGT" in result
        assert "IRGC" in result

    def test_none_input(self):
        assert _parse_programs(None) == []

    def test_empty_string(self):
        assert _parse_programs("") == []

    def test_brackets_stripped(self):
        result = _parse_programs("[RUSSIA-EO14024]")
        assert result == ["RUSSIA-EO14024"]


# ── _parse_identifiers ─────────────────────────────────────────────────────


class TestParseIdentifiers:
    def test_passport_extraction(self):
        remarks = "Passport 1234567890 (Russia)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        passport = next(i for i in result if i["id_type"] == "Passport")
        assert passport["id_value"] == "1234567890"
        assert passport["country"] == "Russia"

    def test_tax_id_extraction(self):
        remarks = "Tax ID No. 7710140679 (Russia)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        tax = next(i for i in result if i["id_type"] == "Tax ID")
        assert tax["id_value"] == "7710140679"
        assert tax["country"] == "Russia"

    def test_multiple_identifiers(self):
        remarks = "Passport AB1234 (Russia); Tax ID No. 999888 (Russia)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 2
        types = {i["id_type"] for i in result}
        assert "Passport" in types
        assert "Tax ID" in types

    def test_no_identifiers(self):
        result = _parse_identifiers("DOB 1970; nationality Russia")
        assert result == []

    def test_identifier_without_country(self):
        remarks = "Registration Number ABC123;"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        reg = next(i for i in result if i["id_type"] == "Registration Number")
        assert reg["id_value"] == "ABC123"
        assert reg["country"] is None


# ── _normalize_entity_type ──────────────────────────────────────────────────


class TestNormalizeEntityType:
    def test_individual(self):
        assert _normalize_entity_type("individual") == "individual"
        assert _normalize_entity_type("Individual") == "individual"

    def test_vessel(self):
        assert _normalize_entity_type("vessel") == "vessel"
        assert _normalize_entity_type("Vessel") == "vessel"

    def test_aircraft(self):
        assert _normalize_entity_type("aircraft") == "aircraft"

    def test_entity_for_unknown(self):
        assert _normalize_entity_type("Entity") == "entity"
        assert _normalize_entity_type("organization") == "entity"

    def test_none_defaults_to_entity(self):
        assert _normalize_entity_type(None) == "entity"


# ── _build_entity_dict ──────────────────────────────────────────────────────


class TestBuildEntityDict:
    def _make_sdn_row(self, **overrides) -> dict:
        defaults = {
            "ent_num": "12345",
            "sdn_name": "Test Entity LLC",
            "sdn_type": "Entity",
            "program": "RUSSIA-EO14024",
            "title": None,
            "call_sign": None,
            "vess_type": None,
            "tonnage": None,
            "grt": None,
            "vess_flag": None,
            "vess_owner": None,
            "remarks": None,
        }
        defaults.update(overrides)
        return defaults

    def test_basic_entity(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        result = _build_entity_dict(self._make_sdn_row(), [], [], None, now)

        assert result["source_id"] == "12345"
        assert result["primary_name"] == "Test Entity LLC"
        assert result["entity_type"] == "entity"
        assert result["programs"] == ["RUSSIA-EO14024"]
        assert result["data_vintage"] == now
        assert result["last_updated"] == now

    def test_individual_with_dob_and_nationality(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(
            sdn_type="individual",
            remarks="DOB 03 Nov 1959; nationality Russia",
        )
        result = _build_entity_dict(row, [], [], None, now)

        assert result["entity_type"] == "individual"
        assert result["date_of_birth"] == date(1959, 11, 3)
        assert result["nationality"] == ["Russia"]

    def test_vessel_with_imo(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(
            sdn_name="TANKER ONE",
            sdn_type="vessel",
            vess_type="Crude Oil Tanker",
            vess_flag="Panama",
            tonnage="50000",
            call_sign="ABCD",
            remarks=(
                "Vessel Registration Identification IMO 9876543;"
                " MMSI 123456789; Vessel Year of Build 2005"
            ),
        )
        result = _build_entity_dict(row, [], [], None, now)

        assert result["entity_type"] == "vessel"
        assert result["vessel_data"] is not None
        assert result["vessel_data"]["imo_number"] == "9876543"
        assert result["vessel_data"]["mmsi_number"] == "123456789"
        assert result["vessel_data"]["build_year"] == 2005
        assert result["vessel_data"]["vessel_type"] == "Crude Oil Tanker"
        assert result["vessel_data"]["flag"] == "Panama"
        assert result["vessel_data"]["call_sign"] == "ABCD"

    def test_no_vessel_data_for_non_vessel(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        result = _build_entity_dict(self._make_sdn_row(), [], [], None, now)
        assert result["vessel_data"] is None

    def test_extended_remarks_appended(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="Original remark")
        result = _build_entity_dict(row, [], [], "Extended comment", now)
        assert "Extended comment" in result["remarks"]
        assert "Original remark" in result["remarks"]

    def test_aliases_preserved_in_raw_record(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        aliases = [
            {
                "ent_num": "12345",
                "alt_num": "1",
                "alt_type": "aka",
                "alt_name": "Alias One",
                "alt_remarks": None,
            }
        ]
        result = _build_entity_dict(self._make_sdn_row(), [], aliases, None, now)
        assert result["raw_record"]["aliases"] == aliases
        assert result["parsed_aliases"] == aliases

    def test_addresses_preserved_in_raw_record(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        addresses = [
            {
                "ent_num": "12345",
                "add_num": "1",
                "address": "123 Main St",
                "city_state": "Moscow",
                "country": "Russia",
                "add_remarks": None,
            }
        ]
        result = _build_entity_dict(self._make_sdn_row(), addresses, [], None, now)
        assert result["raw_record"]["addresses"] == addresses
        assert result["parsed_addresses"] == addresses

    def test_identifiers_parsed_from_remarks(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="Passport AB123456 (Russia)")
        result = _build_entity_dict(row, [], [], None, now)
        assert len(result["identifiers"]) >= 1
        assert result["identifiers"][0]["id_type"] == "Passport"

    def test_empty_programs_becomes_none(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(program=None)
        result = _build_entity_dict(row, [], [], None, now)
        assert result["programs"] is None
