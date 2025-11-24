import csv
import json
import os
import time
from pathlib import Path
from typing import Optional

import requests
from requests.exceptions import RequestException
from tqdm import tqdm


"""
Download all ICLR 2025 PDFs listed in 2025_iclr_pdfs_urls.csv and parse them
with a running Grobid server, saving per-paper folders under ICLR2025_papers.

Usage (from repo root, with Grobid running on localhost:8070):

    conda activate llm-abm
    python 00_download_PDFs/01_get_and_parse_PDF.py

You can override the Grobid URL with the GROBID_URL environment variable, e.g.:

    GROBID_URL=http://localhost:8071 python 00_download_PDFs/01_get_and_parse_PDF.py
"""


GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")
# Optional throttle between Grobid calls (in seconds)
GROBID_SLEEP = float(os.environ.get("GROBID_SLEEP", "0.2"))
# Optional batch control: process only a slice of the CSV
BATCH_START = int(os.environ.get("GROBID_BATCH_START", "0"))  # 0-based index
BATCH_SIZE = os.environ.get("GROBID_BATCH_SIZE")
if BATCH_SIZE is not None:
    BATCH_SIZE = int(BATCH_SIZE)

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent

CSV_PATH = THIS_DIR / "2025_iclr_pdfs_urls.csv"
OUTPUT_ROOT = REPO_ROOT / "ICLR2025_papers"


def download_pdf(url: str, dest_path: Path, timeout: int = 120) -> None:
    """Download a single PDF to dest_path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


def grobid_process_fulltext(
    pdf_path: Path,
    output_xml_path: Path,
    *,
    retries: int = 3,
    backoff: float = 5.0,
) -> None:
    """
    Send the PDF to Grobid's processFulltextDocument endpoint and save TEI XML.

    Assumes a Grobid server is running and accessible at GROBID_URL.
    """
    url = f"{GROBID_URL.rstrip('/')}/api/processFulltextDocument"
    output_xml_path.parent.mkdir(parents=True, exist_ok=True)

    last_err: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            with open(pdf_path, "rb") as f:
                files = {"input": (pdf_path.name, f, "application/pdf")}
                data = {
                    # Basic, safe defaults; tune if needed
                    "consolidateHeader": 1,
                    "consolidateCitations": 0,
                }
                resp = requests.post(url, files=files, data=data, timeout=300)

            resp.raise_for_status()

            text = resp.text.strip()
            # Basic sanity check: Grobid should return a TEI XML document
            if not text or "<TEI" not in text:
                raise ValueError("Grobid returned empty or non-TEI response")

            with open(output_xml_path, "w", encoding="utf-8") as out_f:
                out_f.write(text)

            return

        except RequestException as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * attempt)
            else:
                raise


def safe_title(raw_title: str) -> str:
    """Return a filesystem-safe version of the title for metadata only."""
    # Keep this simple; we don't use it for filenames, just JSON.
    return raw_title.strip()


def process_row(row: dict) -> Optional[str]:
    """
    Process a single CSV row: download PDF and run Grobid.

    Returns an error message string on failure, or None on success.
    """
    paper_id = str(row.get("paper_id") or "").strip()
    forum = str(row.get("forum") or "").strip()
    title = str(row.get("title") or "").strip()
    pdf_url = str(row.get("pdf_url") or "").strip()

    if not pdf_url:
        return "missing_pdf_url"

    # Use paper_id if present, otherwise fall back to forum
    folder_name = paper_id or forum
    if not folder_name:
        return "missing_ids"

    paper_dir = OUTPUT_ROOT / folder_name
    pdf_path = paper_dir / f"{folder_name}.pdf"
    tei_path = paper_dir / f"{folder_name}.tei.xml"
    meta_path = paper_dir / "meta.json"

    try:
        # Download PDF if needed
        if not pdf_path.exists():
            download_pdf(pdf_url, pdf_path)

        # Run Grobid if needed
        if not tei_path.exists():
            grobid_process_fulltext(pdf_path, tei_path)

        # Save simple metadata alongside
        if not meta_path.exists():
            meta = {
                "paper_id": paper_id,
                "forum": forum,
                "title": safe_title(title),
                "pdf_url": pdf_url,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        return None

    except Exception as e:  # noqa: BLE001 - top-level script error collection
        return repr(e)


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found at {CSV_PATH}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    print(f"Using Grobid at: {GROBID_URL}")
    print(f"Grobid sleep between calls: {GROBID_SLEEP} seconds")
    print(f"Reading URLs from: {CSV_PATH}")
    print(f"Writing per-paper folders under: {OUTPUT_ROOT}")

    errors_download: list[tuple[int, str, str]] = []
    errors_parse: list[tuple[int, str, str]] = []

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    # Optionally restrict to a batch (useful for debugging or chunked runs)
    if BATCH_SIZE is not None:
        end = BATCH_START + BATCH_SIZE
        rows = all_rows[BATCH_START:end]
        print(f"Processing batch rows [{BATCH_START}:{end}] (total {len(rows)})")
    else:
        rows = all_rows

    # First pass: download all PDFs
    for idx, row in enumerate(tqdm(rows, desc="Downloading PDFs"), start=1):
        paper_id = str(row.get("paper_id") or "").strip()
        forum = str(row.get("forum") or "").strip()
        pdf_url = str(row.get("pdf_url") or "").strip()

        if not pdf_url:
            errors_download.append((idx, paper_id, "missing_pdf_url"))
            continue

        folder_name = paper_id or forum
        if not folder_name:
            errors_download.append((idx, paper_id, "missing_ids"))
            continue

        paper_dir = OUTPUT_ROOT / folder_name
        pdf_path = paper_dir / f"{folder_name}.pdf"

        try:
            if not pdf_path.exists():
                download_pdf(pdf_url, pdf_path)
        except Exception as e:  # noqa: BLE001
            errors_download.append((idx, paper_id, repr(e)))

    # Second pass: run Grobid + write metadata
    for idx, row in enumerate(tqdm(rows, desc="Parsing PDFs with Grobid"), start=1):
        paper_id = str(row.get("paper_id") or "").strip()
        forum = str(row.get("forum") or "").strip()
        title = str(row.get("title") or "").strip()
        pdf_url = str(row.get("pdf_url") or "").strip()

        folder_name = paper_id or forum
        if not folder_name:
            errors_parse.append((idx, paper_id, "missing_ids"))
            continue

        paper_dir = OUTPUT_ROOT / folder_name
        pdf_path = paper_dir / f"{folder_name}.pdf"
        tei_path = paper_dir / f"{folder_name}.tei.xml"
        meta_path = paper_dir / "meta.json"

        if not pdf_path.exists():
            errors_parse.append((idx, paper_id, "pdf_not_downloaded"))
            continue

        try:
            if not tei_path.exists():
                grobid_process_fulltext(pdf_path, tei_path)
                if GROBID_SLEEP > 0:
                    time.sleep(GROBID_SLEEP)

            if not meta_path.exists():
                meta = {
                    "paper_id": paper_id,
                    "forum": forum,
                    "title": safe_title(title),
                    "pdf_url": pdf_url,
                }
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            errors_parse.append((idx, paper_id, repr(e)))

    total_rows = len(rows)
    print(f"\nDone. Total rows: {total_rows}")
    print(f"Download errors: {len(errors_download)}")
    print(f"Parse errors: {len(errors_parse)}")

    if errors_download or errors_parse:
        error_log_path = OUTPUT_ROOT / "grobid_errors.json"
        with open(error_log_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "download_errors": errors_download,
                    "parse_errors": errors_parse,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Error details written to: {error_log_path}")


if __name__ == "__main__":
    main()

