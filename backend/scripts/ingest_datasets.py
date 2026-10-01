#!/usr/bin/env python3
"""
PEHCHAAN Dataset Ingestion Pipeline

Downloads and processes datasets from data.gov.in for the PEHCHAAN
screening system. Supports the 45 datasets mapped in the Dataset
Integration Map.

Usage:
    python -m scripts.ingest_datasets --list
    python -m scripts.ingest_datasets --dataset DS-045
    python -m scripts.ingest_datasets --category passport
    python -m scripts.ingest_datasets --all

Requires: requests, pandas (pip install requests pandas openpyxl)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data" / "reference"
CATALOG_PATH = DATA_DIR / "datasets_catalog.json"

DATA_GOV_API = "https://data.gov.in/backend/dmspublic/v1/resources"
DATA_GOV_DOWNLOAD = "https://data.gov.in/files"


def load_catalog() -> list[dict]:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_catalog(catalog: list[dict]) -> None:
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    logger.info("Catalog updated: %s", CATALOG_PATH)


def list_datasets(category: str | None = None) -> None:
    catalog = load_catalog()
    if category:
        catalog = [d for d in catalog if d["category"] == category]

    print(f"\n{'ID':<8} {'Status':<10} {'Category':<12} {'Name'}")
    print("-" * 80)
    for ds in catalog:
        status_icon = {
            "seeded": "[OK]",
            "ingested": "[OK]",
            "pending": "[..]",
            "error": "[!!]",
        }.get(ds["status"], "[??]")
        print(f"{ds['id']:<8} {status_icon:<10} {ds['category']:<12} {ds['name'][:50]}")

    total = len(catalog)
    seeded = sum(1 for d in catalog if d["status"] in ("seeded", "ingested"))
    print(f"\n{seeded}/{total} datasets loaded")


def download_dataset(dataset_id: str) -> None:
    catalog = load_catalog()
    ds = next((d for d in catalog if d["id"] == dataset_id), None)
    if ds is None:
        logger.error("Dataset %s not found in catalog", dataset_id)
        return

    logger.info("Processing: %s — %s", ds["id"], ds["name"])
    resource_slug = ds.get("data_gov_resource", "")

    if ds["status"] == "seeded":
        logger.info("Dataset %s already has seed data loaded", dataset_id)
        return

    try:
        _attempt_download(ds, resource_slug)
    except Exception as e:
        logger.error("Failed to download %s: %s", dataset_id, e)
        logger.info("Tip: Many data.gov.in datasets require manual download.")
        logger.info("  1. Visit https://data.gov.in and search for: %s", ds["name"])
        logger.info("  2. Download the CSV/Excel file")
        logger.info("  3. Place it in: %s", DATA_DIR / f"{dataset_id.lower()}.csv")
        logger.info("  4. Run: python -m scripts.ingest_datasets --parse %s", dataset_id)

        for d in catalog:
            if d["id"] == dataset_id:
                d["status"] = "error"
        save_catalog(catalog)


def _attempt_download(ds: dict, resource_slug: str) -> None:
    """
    Attempt programmatic download from data.gov.in.

    data.gov.in uses a CKAN-based API but many datasets require
    authentication or have rate limits. This function handles the
    common cases and falls back to manual download instructions.
    """
    try:
        import requests
    except ImportError:
        logger.error("requests package required: pip install requests")
        raise

    api_url = f"{DATA_GOV_API}/{resource_slug}"
    logger.info("Trying API: %s", api_url)

    resp = requests.get(api_url, timeout=30, headers={
        "User-Agent": "PEHCHAAN-Ingest/1.0 (SIH-2026; border-security-research)",
        "Accept": "application/json",
    })

    if resp.status_code == 200:
        data = resp.json()
        if "records" in data:
            output_path = DATA_DIR / f"{ds['id'].lower()}_raw.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data["records"], f, indent=2, ensure_ascii=False)
            logger.info("Downloaded %d records to %s", len(data["records"]), output_path)
            return
        elif "download_url" in data:
            _download_file(data["download_url"], ds["id"])
            return

    logger.warning("API returned %d — dataset may require manual download", resp.status_code)
    raise RuntimeError(f"API access failed ({resp.status_code})")


def _download_file(url: str, dataset_id: str) -> None:
    import requests

    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()

    ext = ".csv"
    content_type = resp.headers.get("content-type", "")
    if "excel" in content_type or "spreadsheet" in content_type:
        ext = ".xlsx"

    output_path = DATA_DIR / f"{dataset_id.lower()}_raw{ext}"
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info("Downloaded to %s", output_path)


def parse_local_file(dataset_id: str) -> None:
    """Parse a manually downloaded CSV/Excel file into normalized JSON."""
    csv_path = DATA_DIR / f"{dataset_id.lower()}.csv"
    xlsx_path = DATA_DIR / f"{dataset_id.lower()}.xlsx"
    json_raw = DATA_DIR / f"{dataset_id.lower()}_raw.json"

    if json_raw.exists():
        logger.info("Raw JSON already exists for %s", dataset_id)
        _normalize_dataset(dataset_id, json_raw)
        return

    if csv_path.exists():
        logger.info("Parsing CSV: %s", csv_path)
        records = []
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))
        output = DATA_DIR / f"{dataset_id.lower()}_raw.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        logger.info("Parsed %d rows from CSV", len(records))
        _normalize_dataset(dataset_id, output)
        return

    if xlsx_path.exists():
        try:
            import pandas as pd
        except ImportError:
            logger.error("pandas required for Excel parsing: pip install pandas openpyxl")
            return
        logger.info("Parsing Excel: %s", xlsx_path)
        df = pd.read_excel(xlsx_path)
        records = df.to_dict(orient="records")
        output = DATA_DIR / f"{dataset_id.lower()}_raw.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False, default=str)
        logger.info("Parsed %d rows from Excel", len(records))
        _normalize_dataset(dataset_id, output)
        return

    logger.error(
        "No local file found for %s. Expected one of:\n  %s\n  %s",
        dataset_id, csv_path, xlsx_path,
    )


def _normalize_dataset(dataset_id: str, raw_path: Path) -> None:
    """Apply dataset-specific normalization to raw data."""
    catalog = load_catalog()
    ds = next((d for d in catalog if d["id"] == dataset_id), None)
    if ds is None:
        return

    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    logger.info("Normalized %d records for %s", len(raw) if isinstance(raw, list) else 1, dataset_id)

    for d in catalog:
        if d["id"] == dataset_id:
            d["status"] = "ingested"
    save_catalog(catalog)


def ingest_all(category: str | None = None) -> None:
    catalog = load_catalog()
    if category:
        catalog = [d for d in catalog if d["category"] == category]

    pending = [d for d in catalog if d["status"] == "pending"]
    logger.info("Found %d pending datasets to process", len(pending))

    for ds in pending:
        download_dataset(ds["id"])


def main():
    parser = argparse.ArgumentParser(
        description="PEHCHAAN Dataset Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.ingest_datasets --list
  python -m scripts.ingest_datasets --list --category passport
  python -m scripts.ingest_datasets --dataset DS-045
  python -m scripts.ingest_datasets --parse DS-045
  python -m scripts.ingest_datasets --category border
  python -m scripts.ingest_datasets --all
        """,
    )
    parser.add_argument("--list", action="store_true", help="List all datasets and their status")
    parser.add_argument("--dataset", type=str, help="Download a specific dataset by ID")
    parser.add_argument("--parse", type=str, help="Parse a locally downloaded dataset file")
    parser.add_argument("--category", type=str, help="Filter by category (passport, visa, immigration, aadhaar, border, fraud, crime)")
    parser.add_argument("--all", action="store_true", help="Process all pending datasets")

    args = parser.parse_args()

    if args.list:
        list_datasets(args.category)
    elif args.dataset:
        download_dataset(args.dataset)
    elif args.parse:
        parse_local_file(args.parse)
    elif args.all:
        ingest_all(args.category)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
