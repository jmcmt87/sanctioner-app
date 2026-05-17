---
name: enforcement-baseline-2026-05-17
description: Enforcement document_chunks baseline from 2026-05-17 DQR. 207 chunks from 20 PDFs. CRITICAL: 9 of 20 PDFs downloaded wrong content due to stale OFAC media URLs.
metadata:
  type: project
---

Enforcement action document chunks baseline as of 2026-05-17.

**Record counts:** 207 chunks across 20 source documents, 325K total characters, avg 1,571 chars/chunk.

**CRITICAL — 9 of 20 PDFs contain wrong content:**
The OFAC `media/NNNNN/download` URLs in the enforcement manifest (`ingestion/pipeline/sources/enforcement.py`) are stale. OFAC restructured their website and the media IDs now point to different documents. Affected files and what they actually contain:

| File | Expected | Actually Contains |
|------|----------|-------------------|
| `apollo_aviation_2019.pdf` | Apollo Aviation Group settlement | Aviation Services International (ASI) / BIS+OFAC joint settlement |
| `bittrex_2022.pdf` | Bittrex Inc. settlement | Binance Holdings Ltd. $968M settlement (Nov 2023) |
| `deutsche_bank_2015.pdf` | Deutsche Bank AG settlement | PanAmerican Seed / Ball Horticultural settlement |
| `exxonmobil_2017.pdf` | ExxonMobil settlement | Batch enforcement release (June 6, 2008) with BlueStar Canada, Confi-Dental, Z.A.S. |
| `societe_generale_2018.pdf` | Societe Generale settlement | Sinaloa Cartel OFAC designation chart (narcotics, not enforcement) |
| `standard_chartered_2019.pdf` | Standard Chartered settlement | TSRA Licensing Activity Report |
| `unicredit_2019.pdf` | UniCredit Group settlement | TSRA Licensing Activity Report (Apr-Jun 2006) |
| `zhongxing_2017.pdf` | ZTE/Zhongxing settlement | HTML page scrape (not even a PDF) |
| `credit_suisse_2009.pdf` | Credit Suisse settlement | Correct content BUT 697 non-breaking spaces (char 160) causing search failures |

**Why:** The progress log (Session 12) notes that 14 OFAC URLs were researched and corrected after initially breaking. The replacements appear to point to the wrong documents. The `media/NNNNN/download` pattern is fragile -- OFAC can change what a media ID points to at any time.

**How to apply:** All 9 files need URL corrections in the manifest. After fixing, delete existing `data/enforcement/*.pdf` files and re-run ingestion. Consider adding a content validation step to the enforcement parser that checks whether the PDF mentions the expected entity name.

**Field completeness (all 207 chunks):**
- content: 100% populated, 0 empty
- embedding: 100% populated, all 1024-dim (bge-m3)
- source_document: 100%
- source_title: 100%
- jurisdiction: 100% (all 'US')
- document_type: 100% (all 'enforcement')
- data_vintage: 100%
- ingestion_timestamp: 100%
- published_date: 100%
- article_reference: 0% (expected for enforcement docs)
- metadata: 100% present as column but all values are JSON `null` (no useful metadata stored)
- chunk_index: 100%, no gaps in sequence

**OCR artifacts in correctly-sourced documents:**
- BNP Paribas: "ZOZZO" (for 20220 ZIP code), "intemal" (rn->m OCR error) in 5 chunks
- Commerzbank: "Agreemenf", "Agreetaent" in 2 chunks
- JP Morgan: "govemment" (rn->m) in 4 chunks
- Apollo/ASI: "Intemaf/Intemat" in 8 chunks, "Govemment" in 6 chunks
- Barclays: "intemal" in 1 chunk

**Non-breaking space issue:**
- credit_suisse_2009.pdf: 697 instances of char 160 (non-breaking space) -- causes full-text search failures
- zhongxing_2017.pdf: 4 instances (moot since content is wrong anyway)

Related memories: [[ofac-parser-gaps]]
