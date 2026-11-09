# Document vault convention

Local store for manually supplied source PDFs. Provenance lives in Turso `source_items`; the vault only holds the bytes.

- **Root:** env var `DOCUMENT_VAULT_PATH` (set in `.env`; no default, the ingester refuses to run without it). Keep it outside the git checkout; `psx_document_vault/` is gitignored as a safety net.
- **Layout:** `<root>/<category>/YYYY/MM/<sha256[:12]>_<safe-name>.pdf`, where `category` is `announcements`, `financial_reports` or `other`, and `YYYY/MM` is the document's `--published-date` (or the ingest date if none is given).
- **Database pointer:** `source_items.content_location` = path relative to the root (e.g. `announcements/2026/11/ab12cd34ef56_Board_Meeting.pdf`). Never an absolute path.
- **Identity and dedupe:** `content_sha256` is the SHA-256 of the file; `external_id` = `sha256:<digest>`, so the same file under the same source is never ingested twice.
- **Record fields:** `document_type='pdf'`, `retrieval_method='manual'`, `access_status='permitted'` (the schema's CHECK does not allow `downloaded`), `publication_time_status` = `date_only` when a date is given, else `unknown`. One `collector_runs` row (`job='manual_pdf_ingest'`) per ingest.
- **Immutability:** `source_items` rows are append-only (triggers block UPDATE of provenance fields and DELETE). Vault files are never overwritten or removed once recorded.
- **Terms:** sources whose `access_status` is not `verified_permitted` (e.g. `psx`, `psx_dps`) require `--ack-terms`: the owner confirms they obtained the file themselves, one document at a time, in line with the source's terms. This does not authorise bulk or automated collection.

```
python backend/manual_pdf_ingester.py ~/Downloads/file.pdf --source-id psx \
    --published-date 2026-11-06 --title "..." --ack-terms [--dry-run]
```
