---
name: data-acquisition-patterns
description: >
  Use this skill whenever downloading, fetching, or crawling data from external sources
  for the ingestion pipeline. Triggers on: downloading files from government websites
  (OFAC, EU, Bundesbank), crawling index pages for document links, extracting content
  from HTML pages, uploading raw files to S3, implementing hash-based change detection,
  or any work in the acquisition/download layer of the ingestion pipeline. This skill
  covers how data gets FROM the internet TO S3. The ingestion-pipeline-patterns skill
  covers what happens AFTER it's in S3.
---

# Data Acquisition Patterns

This skill standardizes how source data is fetched from the web, versioned in S3, and
handed off to parsers. All project data comes from government websites with stable URLs.
This is structured downloading with light index crawling — not web scraping.

---

## Three Acquisition Categories

Every data source falls into exactly one category:

### Category 1 — Direct Download
Known stable URL → fetch file → save to S3.

**Sources in this category:**
- OFAC SDN CSV files (`sdn.csv`, `add.csv`, `alt.csv`, `sdn_comments.csv`)
- EU Consolidated List XML
- OFAC Non-SDN list
- OFAC Compliance Framework PDF
- OFAC 50% Rule guidance PDF
- Reg. 833/2014 consolidated HTML from EUR-Lex
- Bundesbank guidance PDFs

**Pattern:**
```
fetch(url) → compare hash with last S3 version → if changed: upload to S3, return metadata
                                                → if unchanged: return skipped
```

### Category 2 — Index Crawl + Download
Fetch an HTML index page → extract document links → download each linked document.

**Sources in this category:**
- OFAC enforcement actions (~293 PDFs linked from an index page)
- OFAC General Licenses (listed on a program page)
- EU Commission FAQs (~30+ PDFs linked from a topic page)
- German Ministry FAQ documents

**Pattern:**
```
fetch(index_url) → parse HTML for document links → compare against previous manifest
  → for each new/changed link: download file → upload to S3
  → save updated manifest to S3
```

### Category 3 — HTML Content Extraction
Download an HTML page and parse it AS content (not as an index of links).

**Sources in this category:**
- OFAC FAQs (one large HTML page with 1,200+ Q&A pairs)
- EUR-Lex regulation text (HTML with article structure)

**Pattern:**
```
fetch(url) → save raw HTML to S3 → parse content structure (Q&A pairs, articles)
  → the parsed structure feeds into the ingestion pipeline's chunking step
```

---

## Standard Function Signature

Every acquisition function follows this pattern:

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AcquisitionResult:
    source_name: str
    local_path: Path | None          # Path to downloaded file (None if skipped)
    s3_key: str | None               # S3 location of uploaded file
    fetch_timestamp: datetime         # When the fetch was performed
    source_vintage: datetime | None   # Timestamp of the source data itself
                                      # (e.g., OFAC "last updated" date, not fetch time)
    file_hash: str | None             # SHA-256 hash of the downloaded file
    changed: bool                     # True if new/changed, False if unchanged
    files_discovered: int             # For index crawls: total links found
    files_downloaded: int             # For index crawls: new/changed files downloaded


async def acquire_ofac_sdn(
    s3_client: S3Client,
    config: AcquisitionConfig,
) -> AcquisitionResult:
    """Download OFAC SDN CSV files from Treasury.gov and upload to S3."""
    ...
```

---

## Implementation Rules

### HTTP Client
- Use `httpx` (async) for all HTTP requests. Never `requests` (sync).
- Create a shared `httpx.AsyncClient` with sensible defaults:
  ```python
  async with httpx.AsyncClient(
      timeout=httpx.Timeout(30.0, connect=10.0),
      follow_redirects=True,
      headers={"User-Agent": "SanctionsScreeningAssistant/1.0 (compliance-research-tool)"},
  ) as client:
      ...
  ```

### User-Agent
- Set a descriptive `User-Agent` header. Government sites may block default Python user agents.
- Format: `SanctionsScreeningAssistant/1.0 (compliance-research-tool)`
- Never use the default httpx/Python user agent string.

### Rate Limiting
- Minimum 1 second between requests to the same domain.
- Government websites are not CDNs. Be respectful.
- Use `asyncio.sleep(1.0)` between requests in a loop.

### Retry Logic
- 3 attempts with exponential backoff: 2s → 4s → 8s.
- Log each retry via structlog:
  ```python
  logger.warning("download_retry", url=url, attempt=attempt, delay=delay, status_code=response.status_code)
  ```
- After 3 failures, log error and return a failed AcquisitionResult — do not crash the pipeline.

### S3 Organization
Prefix structure: `raw/{category}/{source_name}/{YYYY-MM-DD}/{filename}`

Examples:
```
raw/structured/ofac_sdn/2026-05-14/sdn.csv
raw/structured/ofac_sdn/2026-05-14/add.csv
raw/structured/ofac_sdn/2026-05-14/alt.csv
raw/structured/eu_consolidated/2026-05-14/eu_sanctions_list.xml
raw/enforcement/ofac_enforcement/2026-05-14/bnp_paribas_settlement.pdf
raw/enforcement/ofac_enforcement/2026-05-14/commerzbank_settlement.pdf
raw/regulations/eu_833_2014/2026-05-14/reg_833_2014_consolidated.html
raw/guidance/ofac_compliance_framework/2026-05-14/framework.pdf
```

This structure enables version history by date. Every day's download is preserved.
Never overwrite previous versions — write to a new date prefix.

### Hash-Based Change Detection
Before uploading to S3, compare the SHA-256 hash of the downloaded file against the hash
of the most recent version in S3:

```python
import hashlib

def compute_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

async def has_changed(s3_client, bucket, prefix, new_hash) -> bool:
    """Check if the file has changed since the last download."""
    # List objects under prefix, get most recent
    # Read its hash from metadata (stored as x-amz-meta-sha256 on upload)
    # Return True if hashes differ or no previous version exists
    ...
```

- Store the hash as S3 object metadata (`x-amz-meta-sha256`) on upload.
- If unchanged, skip upload and return `AcquisitionResult(changed=False)`.
- This prevents unnecessary re-processing when source data hasn't been updated.

### Source Vintage vs. Fetch Timestamp
These are two different things. Both must be tracked.

- **`fetch_timestamp`**: When YOU downloaded the file. `datetime.now(UTC)`.
- **`source_vintage`**: When THE SOURCE last updated their data.
  - For OFAC SDN: The "last updated" date from the OFAC website or the CSV header.
  - For EU list: The publication date from the XML metadata.
  - For EUR-Lex regulations: The "last consolidated" date on the page.
  - If the source doesn't provide a date, use `fetch_timestamp` as a fallback and log a warning.

---

## Index Crawling (Category 2)

### HTML Parsing
- Use BeautifulSoup with `lxml` parser. No headless browser — government pages are static HTML.
- Extract links matching a pattern:
  ```python
  from bs4 import BeautifulSoup

  soup = BeautifulSoup(html, "lxml")
  pdf_links = [
      urljoin(base_url, a["href"])
      for a in soup.find_all("a", href=True)
      if a["href"].lower().endswith(".pdf")
  ]
  ```

### Manifest Tracking
Store a manifest of discovered URLs alongside the downloads in S3:

```
raw/enforcement/ofac_enforcement/2026-05-14/manifest.json
```

Manifest format:
```json
{
  "crawl_timestamp": "2026-05-14T10:30:00Z",
  "index_url": "https://ofac.treasury.gov/civil-penalties-and-enforcement-information",
  "documents": [
    {
      "url": "https://ofac.treasury.gov/.../bnp_paribas.pdf",
      "filename": "bnp_paribas_settlement.pdf",
      "file_hash": "abc123...",
      "first_seen": "2026-03-01T00:00:00Z",
      "last_downloaded": "2026-05-14T10:31:00Z"
    }
  ]
}
```

On subsequent runs, compare discovered URLs against the previous manifest to detect:
- **New documents**: URL not in previous manifest → download.
- **Changed documents**: URL exists but hash differs → re-download.
- **Removed documents**: URL in previous manifest but no longer on page → log warning, don't delete from S3.

---

## HTML Content Extraction (Category 3)

### OFAC FAQs
The OFAC FAQ page is a single large HTML page with 1,200+ Q&A pairs.

- Download the full HTML page and save raw to S3 before parsing.
- **Inspect the actual page structure** before writing the parser. The structure typically uses
  consistent HTML patterns (e.g., `<strong>` or `<h4>` for questions, following `<p>` tags
  for answers). Do not assume the structure — fetch the page and examine it first.
- Each Q&A pair becomes a separate item passed to the ingestion pipeline.
- Tag each Q&A with any topic/category information visible in the HTML structure.

### EUR-Lex Regulations
EUR-Lex serves regulation text as structured HTML with identifiable article boundaries.

- Download the consolidated version of the regulation (not the original 2014 text).
- Save raw HTML to S3.
- Parse article structure using CSS classes or element patterns specific to EUR-Lex.
- Each article (or sub-article for long articles) becomes a separate item.
- Preserve cross-reference metadata: which articles reference which other articles.
- This feeds into the regulation_chunker in the ingestion pipeline (structure-aware chunking).

---

## What This Skill Does NOT Cover

- JavaScript-rendered pages (not needed — all sources are static HTML)
- Authentication or session management (all sources are public)
- CAPTCHA handling (not applicable)
- Parsing file contents into entities or chunks — that's the ingestion-pipeline-patterns skill
- Embedding generation — that's the ingestion pipeline
- Database writes — that's the ingestion pipeline

**The boundary is clear:** This skill gets files from the internet to S3.
The ingestion-pipeline-patterns skill gets data from S3 to PostgreSQL.
