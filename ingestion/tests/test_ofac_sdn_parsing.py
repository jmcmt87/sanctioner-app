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
    _parse_inline_aliases,
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

    def test_curp_extraction(self):
        remarks = "C.U.R.P. BOFH701002MBCRGL02 (Mexico)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        curp = next(i for i in result if i["id_type"] == "C.U.R.P.")
        assert curp["id_value"] == "BOFH701002MBCRGL02"
        assert curp["country"] == "Mexico"

    def test_rfc_extraction(self):
        remarks = "R.F.C. BOFH701002XYZ (Mexico)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        rfc = next(i for i in result if i["id_type"] == "R.F.C.")
        assert rfc["id_value"] == "BOFH701002XYZ"
        assert rfc["country"] == "Mexico"

    def test_swift_bic_extraction(self):
        remarks = "SWIFT/BIC VTBRRUMM; alt. SWIFT/BIC SABRRUMM"
        result = _parse_identifiers(remarks)
        swift_ids = [i for i in result if i["id_type"] == "SWIFT/BIC"]
        assert len(swift_ids) == 2
        values = {i["id_value"] for i in swift_ids}
        assert "VTBRRUMM" in values
        assert "SABRRUMM" in values

    def test_uscc_extraction(self):
        remarks = "Unified Social Credit Code (USCC) 913307230927997015 (China)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        uscc = next(i for i in result if i["id_type"] == "USCC")
        assert uscc["id_value"] == "913307230927997015"
        assert uscc["country"] == "China"

    def test_trade_license_extraction(self):
        remarks = "Trade License No. 12345 (Dubai)"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        tl = next(i for i in result if i["id_type"] == "Trade License")
        assert tl["id_value"] == "12345"
        assert tl["country"] == "Dubai"

    def test_digital_currency_address_extraction(self):
        remarks = "Digital Currency Address - XBT bc1qwa6xyz123;"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        dca = next(i for i in result if i["id_type"] == "Digital Currency Address - XBT")
        assert dca["id_value"] == "bc1qwa6xyz123"
        assert dca["country"] is None

    def test_duns_extraction(self):
        remarks = "D-U-N-S Number 123456789;"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        duns = next(i for i in result if i["id_type"] == "D-U-N-S")
        assert duns["id_value"] == "123456789"

    def test_bik_extraction(self):
        remarks = "BIK 044525411 (RU);"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        bik = next(i for i in result if i["id_type"] == "BIK")
        assert bik["id_value"] == "044525411"

    def test_phone_number_extraction(self):
        remarks = "Phone Number +7-495-1234567;"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        phone = next(i for i in result if i["id_type"] == "Phone Number")
        assert phone["id_value"] == "+7-495-1234567"

    def test_license_extraction(self):
        remarks = "License LIC-001 (Syria);"
        result = _parse_identifiers(remarks)
        assert len(result) >= 1
        lic = next(i for i in result if i["id_type"] == "License")
        assert lic["id_value"] == "LIC-001"
        assert lic["country"] == "Syria"


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
        assert len(result["vessels"]) == 1
        vessel = result["vessels"][0]
        assert vessel["imo_number"] == "9876543"
        assert vessel["mmsi_number"] == "123456789"
        assert vessel["build_year"] == 2005
        assert vessel["vessel_type"] == "Crude Oil Tanker"
        assert vessel["flag"] == "Panama"
        assert vessel["call_sign"] == "ABCD"

    def test_no_vessel_data_for_non_vessel(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        result = _build_entity_dict(self._make_sdn_row(), [], [], None, now)
        assert result["vessels"] == []

    def test_extended_remarks_appended(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="Original remark")
        result = _build_entity_dict(row, [], [], "Extended comment", now)
        assert "Extended comment" in result["remarks"]
        assert "Original remark" in result["remarks"]

    def test_aliases_normalized_and_raw_preserved(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        raw_aliases = [
            {
                "ent_num": "12345",
                "alt_num": "1",
                "alt_type": "aka",
                "alt_name": "Alias One",
                "alt_remarks": None,
            }
        ]
        result = _build_entity_dict(self._make_sdn_row(), [], raw_aliases, None, now)
        assert result["raw_record"]["aliases"] == raw_aliases
        assert len(result["aliases"]) == 1
        assert result["aliases"][0]["alias_name"] == "Alias One"
        assert result["aliases"][0]["alias_type"] == "aka"

    def test_addresses_normalized_and_raw_preserved(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        raw_addresses = [
            {
                "ent_num": "12345",
                "add_num": "1",
                "address": "123 Main St",
                "city_state": "Moscow",
                "country": "Russia",
                "add_remarks": None,
            }
        ]
        result = _build_entity_dict(self._make_sdn_row(), raw_addresses, [], None, now)
        assert result["raw_record"]["addresses"] == raw_addresses
        assert len(result["addresses"]) == 1
        assert result["addresses"][0]["address"] == "123 Main St"
        assert result["addresses"][0]["city"] == "Moscow"
        assert result["addresses"][0]["country"] == "Russia"

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

    def test_country_of_registration_extracted(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(
            remarks="Nationality of Registration Russia; Tax ID No. 1234 (Russia)"
        )
        result = _build_entity_dict(row, [], [], None, now)
        assert result["country_of_registration"] == "Russia"

    def test_country_of_registration_none_for_individual(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(
            sdn_type="individual",
            remarks="Nationality of Registration Russia",
        )
        result = _build_entity_dict(row, [], [], None, now)
        assert result["country_of_registration"] is None

    def test_country_of_registration_none_when_absent(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="some other remark")
        result = _build_entity_dict(row, [], [], None, now)
        assert result["country_of_registration"] is None

    def test_inline_aliases_merged_with_alt_csv(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="a.k.a. 'HYDRA'; a.k.a. 'SHADOW'")
        alt_csv_aliases = [
            {
                "ent_num": "12345",
                "alt_num": "1",
                "alt_type": "aka",
                "alt_name": "Alias One",
                "alt_remarks": None,
            }
        ]
        result = _build_entity_dict(row, [], alt_csv_aliases, None, now)
        alias_names = [a["alias_name"] for a in result["aliases"]]
        assert "Alias One" in alias_names
        assert "HYDRA" in alias_names
        assert "SHADOW" in alias_names
        assert len(result["aliases"]) == 3

    def test_inline_aliases_deduplicated_against_alt_csv(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="a.k.a. 'Alias One'; a.k.a. 'HYDRA'")
        alt_csv_aliases = [
            {
                "ent_num": "12345",
                "alt_num": "1",
                "alt_type": "aka",
                "alt_name": "Alias One",
                "alt_remarks": None,
            }
        ]
        result = _build_entity_dict(row, [], alt_csv_aliases, None, now)
        alias_names = [a["alias_name"] for a in result["aliases"]]
        # "Alias One" should appear only once (from alt.csv), "HYDRA" added from inline
        assert alias_names.count("Alias One") == 1
        assert "HYDRA" in alias_names
        assert len(result["aliases"]) == 2

    def test_inline_aliases_case_insensitive_dedup(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        row = self._make_sdn_row(remarks="a.k.a. 'alias one'")
        alt_csv_aliases = [
            {
                "ent_num": "12345",
                "alt_num": "1",
                "alt_type": "aka",
                "alt_name": "Alias One",
                "alt_remarks": None,
            }
        ]
        result = _build_entity_dict(row, [], alt_csv_aliases, None, now)
        # Case-insensitive dedup: "alias one" matches "Alias One"
        assert len(result["aliases"]) == 1


# ── _parse_inline_aliases ──────────────────────────────────────────────────


class TestParseInlineAliases:
    def test_single_aka(self):
        result = _parse_inline_aliases("a.k.a. 'HYDRA'")
        assert len(result) == 1
        assert result[0]["alias_name"] == "HYDRA"
        assert result[0]["alias_type"] == "aka"
        assert result[0]["is_primary"] is False

    def test_fka_and_aka(self):
        result = _parse_inline_aliases("f.k.a. 'OLD NAME'; a.k.a. 'NEW NAME'")
        assert len(result) == 2
        fka = next(a for a in result if a["alias_type"] == "fka")
        aka = next(a for a in result if a["alias_type"] == "aka")
        assert fka["alias_name"] == "OLD NAME"
        assert aka["alias_name"] == "NEW NAME"

    def test_empty_remarks(self):
        assert _parse_inline_aliases("") == []

    def test_no_aliases_in_remarks(self):
        assert _parse_inline_aliases("DOB 1970; nationality Russia") == []

    def test_multiple_akas(self):
        result = _parse_inline_aliases("a.k.a. 'NAME1'; a.k.a. 'NAME2'; a.k.a. 'NAME3'")
        assert len(result) == 3
        names = [a["alias_name"] for a in result]
        assert names == ["NAME1", "NAME2", "NAME3"]
