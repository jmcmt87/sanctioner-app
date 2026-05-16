"""Unit tests for EU Consolidated Financial Sanctions List XML parsing.

Tests pure parsing logic (no DB, no I/O). Verifies correct extraction
of entities, names, dates, addresses, identifiers, and regulations
from the EU XML format.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from lxml import etree

from pipeline.sources.eu_sanctions import (
    _attr,
    _build_entity_dict,
    _extract_addresses,
    _extract_birthdate,
    _extract_citizenships,
    _extract_identifications,
    _extract_primary_name,
    _extract_regulations,
    _extract_remarks,
    _normalize_entity_type,
    _parse_date,
    _parse_xml,
)

NS = "http://eu.europa.ec/fpi/fsd/export"
NS_MAP = {"ns": NS}


def _el(
    tag: str,
    attribs: dict | None = None,
    children: list | None = None,
    text: str | None = None,
) -> etree._Element:
    """Helper to build namespaced XML elements for tests."""
    el = etree.Element(f"{{{NS}}}{tag}", attrib=attribs or {})
    if text:
        el.text = text
    for child in children or []:
        el.append(child)
    return el


# ── _attr ───────────────────────────────────────────────────────────────────


class TestAttr:
    def test_returns_value(self):
        el = etree.Element("test", attrib={"name": "hello"})
        assert _attr(el, "name") == "hello"

    def test_returns_none_for_missing(self):
        el = etree.Element("test")
        assert _attr(el, "name") is None

    def test_returns_none_for_empty(self):
        el = etree.Element("test", attrib={"name": ""})
        assert _attr(el, "name") is None

    def test_strips_whitespace(self):
        el = etree.Element("test", attrib={"name": "  hello  "})
        assert _attr(el, "name") == "hello"


# ── _normalize_entity_type ──────────────────────────────────────────────────


class TestNormalizeEntityType:
    def test_person_becomes_individual(self):
        assert _normalize_entity_type("person") == "individual"
        assert _normalize_entity_type("Person") == "individual"
        assert _normalize_entity_type("PERSON") == "individual"

    def test_enterprise_becomes_entity(self):
        assert _normalize_entity_type("enterprise") == "entity"

    def test_none_defaults_to_entity(self):
        assert _normalize_entity_type(None) == "entity"


# ── _parse_date ─────────────────────────────────────────────────────────────


class TestParseDate:
    def test_valid_iso_date(self):
        assert _parse_date("2022-03-15") == date(2022, 3, 15)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_invalid_date_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None


# ── _extract_primary_name ───────────────────────────────────────────────────


class TestExtractPrimaryName:
    def test_prefers_english_strong_name(self):
        ru = {"wholeName": "Сбербанк", "nameLanguage": "RU", "strong": "true", "logicalId": "1"}
        en = {"wholeName": "Sberbank", "nameLanguage": "EN", "strong": "true", "logicalId": "2"}
        aliases = [_el("nameAlias", ru), _el("nameAlias", en)]
        primary, others = _extract_primary_name(aliases)
        assert primary == "Sberbank"
        assert len(others) == 1

    def test_falls_back_to_any_strong_name(self):
        ru = {"wholeName": "Сбербанк", "nameLanguage": "RU", "strong": "true", "logicalId": "1"}
        de = {"wholeName": "Sberbank DE", "nameLanguage": "DE", "strong": "false", "logicalId": "2"}
        aliases = [_el("nameAlias", ru), _el("nameAlias", de)]
        primary, others = _extract_primary_name(aliases)
        assert primary == "Сбербанк"

    def test_falls_back_to_first_available(self):
        attrs = {
            "wholeName": "Some Name",
            "nameLanguage": "FR",
            "strong": "false",
            "logicalId": "1",
        }
        aliases = [_el("nameAlias", attrs)]
        primary, others = _extract_primary_name(aliases)
        assert primary == "Some Name"
        assert others == []

    def test_returns_none_for_empty(self):
        primary, others = _extract_primary_name([])
        assert primary is None
        assert others == []

    def test_skips_aliases_without_wholename(self):
        no_name = {"nameLanguage": "EN", "strong": "true", "logicalId": "1"}
        with_name = {
            "wholeName": "Real Name",
            "nameLanguage": "EN",
            "strong": "false",
            "logicalId": "2",
        }
        aliases = [_el("nameAlias", no_name), _el("nameAlias", with_name)]
        primary, others = _extract_primary_name(aliases)
        assert primary == "Real Name"


# ── _extract_citizenships ──────────────────────────────────────────────────


class TestExtractCitizenships:
    def test_extracts_citizenships(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("citizenship", {"countryDescription": "Russia"}),
                _el("citizenship", {"countryDescription": "Ukraine"}),
            ],
        )
        result = _extract_citizenships(entity)
        assert result == ["Russia", "Ukraine"]

    def test_deduplicates(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("citizenship", {"countryDescription": "Russia"}),
                _el("citizenship", {"countryDescription": "Russia"}),
            ],
        )
        result = _extract_citizenships(entity)
        assert result == ["Russia"]

    def test_empty_when_none(self):
        entity = _el("sanctionEntity")
        result = _extract_citizenships(entity)
        assert result == []


# ── _extract_birthdate ─────────────────────────────────────────────────────


class TestExtractBirthdate:
    def test_full_birthdate_attribute(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"birthdate": "1960-05-10"}),
            ],
        )
        assert _extract_birthdate(entity) == date(1960, 5, 10)

    def test_component_birthdate(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"year": "1975", "monthOfYear": "3", "dayOfMonth": "22"}),
            ],
        )
        assert _extract_birthdate(entity) == date(1975, 3, 22)

    def test_year_only_defaults_month_day(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"year": "1980"}),
            ],
        )
        assert _extract_birthdate(entity) == date(1980, 1, 1)

    def test_returns_none_when_absent(self):
        entity = _el("sanctionEntity")
        assert _extract_birthdate(entity) is None

    def test_first_valid_date_wins(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"birthdate": "1960-01-15"}),
                _el("birthdate", {"birthdate": "1970-06-20"}),
            ],
        )
        assert _extract_birthdate(entity) == date(1960, 1, 15)

    def test_skips_solar_hijri_year_takes_gregorian(self):
        """Solar Hijri year (1340) should be skipped; Gregorian equivalent used."""
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"year": "1340"}),
                _el("birthdate", {"birthdate": "1961-03-15"}),
            ],
        )
        assert _extract_birthdate(entity) == date(1961, 3, 15)

    def test_solar_hijri_only_returns_none(self):
        """When only a Solar Hijri date is available (no Gregorian), return None."""
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"year": "1340"}),
            ],
        )
        assert _extract_birthdate(entity) is None

    def test_skips_solar_hijri_full_date_attribute(self):
        """Solar Hijri date via the full birthdate attribute should also be skipped."""
        entity = _el(
            "sanctionEntity",
            children=[
                _el("birthdate", {"birthdate": "1352-06-01"}),
                _el("birthdate", {"birthdate": "1973-08-23"}),
            ],
        )
        assert _extract_birthdate(entity) == date(1973, 8, 23)


# ── _extract_addresses ─────────────────────────────────────────────────────


class TestExtractAddresses:
    def test_extracts_full_address(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el(
                    "address",
                    {
                        "street": "Vavilova Street 19",
                        "city": "Moscow",
                        "countryDescription": "Russia",
                        "zipCode": "117997",
                        "region": "Moscow Oblast",
                    },
                ),
            ],
        )
        result = _extract_addresses(entity)
        assert len(result) == 1
        assert result[0]["city"] == "Moscow"
        assert result[0]["country"] == "Russia"
        assert result[0]["postal_code"] == "117997"
        assert "Vavilova Street 19" in result[0]["address"]
        assert "Moscow Oblast" in result[0]["address"]

    def test_skips_empty_addresses(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("address", {}),
            ],
        )
        result = _extract_addresses(entity)
        assert result == []

    def test_address_with_only_country(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("address", {"countryDescription": "Russia"}),
            ],
        )
        result = _extract_addresses(entity)
        assert len(result) == 1
        assert result[0]["country"] == "Russia"


# ── _extract_identifications ───────────────────────────────────────────────


class TestExtractIdentifications:
    def test_extracts_passport(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el(
                    "identification",
                    {
                        "number": "AB1234567",
                        "identificationTypeDescription": "Passport",
                        "countryDescription": "Russia",
                    },
                ),
            ],
        )
        result = _extract_identifications(entity)
        assert len(result) == 1
        assert result[0]["id_type"] == "Passport"
        assert result[0]["id_value"] == "AB1234567"
        assert result[0]["country"] == "Russia"

    def test_skips_without_number(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("identification", {"identificationTypeDescription": "Passport"}),
            ],
        )
        result = _extract_identifications(entity)
        assert result == []

    def test_falls_back_to_type_code(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("identification", {"number": "123", "identificationTypeCode": "passport"}),
            ],
        )
        result = _extract_identifications(entity)
        assert result[0]["id_type"] == "passport"

    def test_unknown_type_when_both_missing(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("identification", {"number": "123"}),
            ],
        )
        result = _extract_identifications(entity)
        assert result[0]["id_type"] == "Unknown"


# ── _extract_regulations ───────────────────────────────────────────────────


class TestExtractRegulations:
    def test_extracts_legal_basis(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el(
                    "regulation",
                    {
                        "numberTitle": "269/2014 (OJ L78)",
                        "programme": "UKR",
                    },
                ),
            ],
        )
        legal_basis, programmes, earliest = _extract_regulations(entity)
        assert "Reg. 269/2014" in legal_basis
        assert "UKR" in programmes

    def test_multiple_regulations(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("regulation", {"numberTitle": "269/2014 (OJ L78)", "programme": "UKR"}),
                _el("regulation", {"numberTitle": "833/2014 (OJ L229)", "programme": "RUS"}),
            ],
        )
        legal_basis, programmes, _ = _extract_regulations(entity)
        assert "Reg. 269/2014" in legal_basis
        assert "Reg. 833/2014" in legal_basis
        assert len(programmes) == 2

    def test_deduplicates_regulations(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("regulation", {"numberTitle": "269/2014 (OJ L78)", "programme": "UKR"}),
                _el("regulation", {"numberTitle": "269/2014 (OJ L78)", "programme": "UKR"}),
            ],
        )
        legal_basis, programmes, _ = _extract_regulations(entity)
        assert legal_basis.count("Reg. 269/2014") == 1

    def test_tracks_earliest_publication_date(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("regulation", {"numberTitle": "269/2014", "publicationDate": "2022-03-15"}),
                _el("regulation", {"numberTitle": "833/2014", "publicationDate": "2014-07-31"}),
            ],
        )
        _, _, earliest = _extract_regulations(entity)
        assert earliest == date(2014, 7, 31)

    def test_regulation_with_short_year(self):
        """Regulation numbers with fewer than 4 digits after the slash (e.g. 2025/44)."""
        entity = _el(
            "sanctionEntity",
            children=[
                _el("regulation", {"numberTitle": "2020/716 (OJ L260)"}),
                _el("regulation", {"numberTitle": "2025/44 (OJ L12)"}),
                _el("regulation", {"numberTitle": "36/2011 (OJ L56)"}),
            ],
        )
        legal_basis, _, _ = _extract_regulations(entity)
        assert "Reg. 2020/716" in legal_basis
        assert "Reg. 2025/44" in legal_basis
        assert "Reg. 36/2011" in legal_basis

    def test_empty_regulations(self):
        entity = _el("sanctionEntity")
        legal_basis, programmes, earliest = _extract_regulations(entity)
        assert legal_basis == []
        assert programmes == []
        assert earliest is None


# ── _extract_remarks ────────────────────────────────────────────────────────


class TestExtractRemarks:
    def test_concatenates_remarks(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("remark", text="First remark."),
                _el("remark", text="Second remark."),
            ],
        )
        result = _extract_remarks(entity)
        assert result == "First remark.; Second remark."

    def test_none_when_no_remarks(self):
        entity = _el("sanctionEntity")
        assert _extract_remarks(entity) is None

    def test_skips_empty_remarks(self):
        entity = _el(
            "sanctionEntity",
            children=[
                _el("remark", text="  "),
                _el("remark", text="Valid remark."),
            ],
        )
        result = _extract_remarks(entity)
        assert result == "Valid remark."


# ── _build_entity_dict (EU) ────────────────────────────────────────────────


class TestBuildEntityDictEU:
    def _make_entity_el(
        self, eu_ref: str = "EU.12345.67", subject_code: str = "person"
    ) -> etree._Element:
        """Build a minimal valid sanctionEntity element."""
        entity = _el(
            "sanctionEntity",
            {
                "euReferenceNumber": eu_ref,
                "designationDate": "2022-03-15",
            },
            children=[
                _el("subjectType", {"code": subject_code}),
                _el(
                    "nameAlias",
                    {
                        "wholeName": "Test Person",
                        "nameLanguage": "EN",
                        "strong": "true",
                        "logicalId": "1",
                    },
                ),
                _el(
                    "regulation",
                    {
                        "numberTitle": "269/2014 (OJ L78)",
                        "programme": "UKR",
                        "publicationDate": "2022-03-15",
                    },
                ),
            ],
        )
        return entity

    def test_basic_individual(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        result = _build_entity_dict(el, now)

        assert result["source_id"] == "EU.12345.67"
        assert result["entity_type"] == "individual"
        assert result["primary_name"] == "Test Person"
        assert "Reg. 269/2014" in result["legal_basis"]
        assert result["data_vintage"] == now
        assert result["list_date"] == date(2022, 3, 15)

    def test_entity_type(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el(subject_code="enterprise")
        result = _build_entity_dict(el, now)
        assert result["entity_type"] == "entity"

    def test_raises_without_eu_reference(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        na = {"wholeName": "Test", "nameLanguage": "EN", "strong": "true", "logicalId": "1"}
        el = _el("sanctionEntity", children=[_el("nameAlias", na)])
        with pytest.raises(ValueError, match="Missing euReferenceNumber"):
            _build_entity_dict(el, now)

    def test_raises_without_name(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = _el(
            "sanctionEntity",
            {"euReferenceNumber": "EU.1"},
            children=[
                _el("subjectType", {"code": "person"}),
            ],
        )
        with pytest.raises(ValueError, match="No name found"):
            _build_entity_dict(el, now)

    def test_individual_with_citizenship_and_dob(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        el.append(_el("citizenship", {"countryDescription": "Russia"}))
        el.append(_el("birthdate", {"birthdate": "1960-05-10"}))

        result = _build_entity_dict(el, now)
        assert result["nationality"] == ["Russia"]
        assert result["date_of_birth"] == date(1960, 5, 10)

    def test_non_individual_skips_citizenship_and_dob(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el(subject_code="enterprise")
        el.append(_el("citizenship", {"countryDescription": "Russia"}))
        el.append(_el("birthdate", {"birthdate": "1960-05-10"}))

        result = _build_entity_dict(el, now)
        assert result["nationality"] is None
        assert result["date_of_birth"] is None

    def test_addresses_extracted(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        addr = {"street": "Main St", "city": "Moscow", "countryDescription": "Russia"}
        el.append(_el("address", addr))

        result = _build_entity_dict(el, now)
        assert len(result["addresses"]) == 1
        assert result["addresses"][0]["city"] == "Moscow"

    def test_identifiers_extracted(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        ident = {"number": "AB123", "identificationTypeDescription": "Passport"}
        el.append(_el("identification", ident))

        result = _build_entity_dict(el, now)
        assert len(result["identifiers"]) == 1
        assert result["identifiers"][0]["id_type"] == "Passport"

    def test_aliases_normalized(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        el.append(
            _el(
                "nameAlias",
                {
                    "wholeName": "Тест Персон",
                    "nameLanguage": "RU",
                    "strong": "false",
                    "logicalId": "2",
                },
            )
        )
        result = _build_entity_dict(el, now)
        assert len(result["aliases"]) == 1
        assert result["aliases"][0]["alias_name"] == "Тест Персон"
        assert result["aliases"][0]["alias_type"] == "aka (RU)"

    def test_vessels_empty_for_persons(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        result = _build_entity_dict(el, now)
        assert result["vessels"] == []

    def test_raw_record_preserved(self):
        now = datetime(2026, 5, 15, tzinfo=UTC)
        el = self._make_entity_el()
        result = _build_entity_dict(el, now)
        assert "eu_reference_number" in result["raw_record"]
        assert "name_aliases" in result["raw_record"]


# ── _parse_xml ──────────────────────────────────────────────────────────────


class TestParseXml:
    def test_parses_xml_file(self, tmp_path):
        xml_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<export xmlns="{NS}" generationDate="2026-05-14T10:00:00">
  <sanctionEntity euReferenceNumber="EU.1.1" logicalId="1">
    <subjectType code="person"/>
    <nameAlias wholeName="Test Person" nameLanguage="EN" strong="true" logicalId="1"/>
    <regulation numberTitle="269/2014" programme="UKR"/>
  </sanctionEntity>
</export>"""
        xml_file = tmp_path / "eu_sanctions_list.xml"
        xml_file.write_text(xml_content)

        entities, gen_date = _parse_xml(xml_file)
        assert len(entities) == 1
        assert gen_date is not None
        assert gen_date.year == 2026

    def test_handles_missing_generation_date(self, tmp_path):
        xml_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<export xmlns="{NS}">
</export>"""
        xml_file = tmp_path / "eu_sanctions_list.xml"
        xml_file.write_text(xml_content)

        entities, gen_date = _parse_xml(xml_file)
        assert len(entities) == 0
        assert gen_date is None
