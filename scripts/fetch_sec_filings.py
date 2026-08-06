#!/usr/bin/env python
"""
Fetch SEC EDGAR company filings by company name or ticker.

Examples:
    python scripts/fetch_sec_filings.py Apple
    python scripts/fetch_sec_filings.py "Microsoft Corporation" --forms 10-K 10-Q
    python scripts/fetch_sec_filings.py NVDA --latest-per-form 2 --output data/sec_filings

SEC requires a descriptive User-Agent. Set one with:
    set SEC_USER_AGENT=Your Name your.email@example.com
or pass:
    --user-agent "Your Name your.email@example.com"
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


SEC_DATA_BASE = "https://data.sec.gov"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

DEFAULT_FORMS = ("10-K", "10-Q")
DEFAULT_OUTPUT_DIR = Path("data/sec_filings")


class SecFetchError(RuntimeError):
    """Raised when SEC filing retrieval fails."""


@dataclass(frozen=True)
class CompanyMatch:
    cik: str
    ticker: str
    title: str
    score: float


@dataclass(frozen=True)
class Filing:
    cik: str
    ticker: str
    company_name: str
    form: str
    filing_date: str
    report_date: str
    accession_number: str
    primary_document: str
    primary_doc_description: str

    @property
    def accession_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def filing_directory_url(self) -> str:
        cik_no_leading_zeroes = str(int(self.cik))
        return f"{SEC_ARCHIVES_BASE}/{cik_no_leading_zeroes}/{self.accession_no_dashes}"

    @property
    def primary_document_url(self) -> str:
        return f"{self.filing_directory_url}/{self.primary_document}"


def build_request(url: str, user_agent: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": urllib.parse.urlparse(url).netloc,
        },
    )


def fetch_json(url: str, user_agent: str) -> Any:
    try:
        with urllib.request.urlopen(build_request(url, user_agent), timeout=30) as response:
            data = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                data = gzip.decompress(data)
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SecFetchError(f"SEC request failed with HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise SecFetchError(f"SEC request failed: {url} ({exc.reason})") from exc


def fetch_bytes(url: str, user_agent: str) -> bytes:
    try:
        with urllib.request.urlopen(build_request(url, user_agent), timeout=60) as response:
            data = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as exc:
        raise SecFetchError(f"SEC filing download failed with HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise SecFetchError(f"SEC filing download failed: {url} ({exc.reason})") from exc


def normalize_query(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def company_score(query: str, ticker: str, title: str) -> float:
    normalized_query = normalize_query(query)
    normalized_ticker = normalize_query(ticker)
    normalized_title = normalize_query(title)

    if normalized_query == normalized_ticker:
        return 1.0
    if normalized_query == normalized_title:
        return 0.98
    if normalized_title.startswith(normalized_query):
        return 0.9
    if normalized_query in normalized_title:
        return 0.82

    title_ratio = SequenceMatcher(None, normalized_query, normalized_title).ratio()
    ticker_ratio = SequenceMatcher(None, normalized_query, normalized_ticker).ratio()
    return max(title_ratio * 0.75, ticker_ratio * 0.9)


def load_companies(user_agent: str) -> list[dict[str, Any]]:
    raw = fetch_json(SEC_COMPANY_TICKERS_URL, user_agent)
    return list(raw.values())


def find_company(query: str, companies: list[dict[str, Any]]) -> CompanyMatch:
    matches: list[CompanyMatch] = []
    for company in companies:
        cik = str(company["cik_str"]).zfill(10)
        ticker = str(company["ticker"]).upper()
        title = str(company["title"])
        score = company_score(query, ticker, title)
        matches.append(CompanyMatch(cik=cik, ticker=ticker, title=title, score=score))

    matches.sort(key=lambda item: item.score, reverse=True)
    best = matches[0]
    if best.score < 0.45:
        raise SecFetchError(f"No confident SEC company match found for: {query}")
    return best


def load_company_submissions(cik: str, user_agent: str) -> dict[str, Any]:
    return fetch_json(f"{SEC_DATA_BASE}/submissions/CIK{cik}.json", user_agent)


def load_all_filing_blocks(submissions: dict[str, Any], user_agent: str) -> list[dict[str, Any]]:
    """Return the main recent filings block plus older archived filing blocks."""
    blocks = [submissions["filings"]["recent"]]
    for file_info in submissions.get("filings", {}).get("files", []):
        name = file_info.get("name")
        if not name:
            continue
        blocks.append(fetch_json(f"{SEC_DATA_BASE}/submissions/{name}", user_agent))
    return blocks


def filing_from_block(block: dict[str, Any], company: CompanyMatch, index: int) -> Filing:
    return Filing(
        cik=company.cik,
        ticker=company.ticker,
        company_name=company.title,
        form=str(block["form"][index]).upper(),
        filing_date=block["filingDate"][index],
        report_date=block["reportDate"][index],
        accession_number=block["accessionNumber"][index],
        primary_document=block["primaryDocument"][index],
        primary_doc_description=block["primaryDocDescription"][index],
    )


def filings_from_submissions(
    submissions: dict[str, Any],
    company: CompanyMatch,
    forms: set[str],
    latest_per_form: int,
) -> list[Filing]:
    recent = submissions["filings"]["recent"]
    results: list[Filing] = []
    counts = {form: 0 for form in forms}

    for index, form in enumerate(recent["form"]):
        normalized_form = str(form).upper()
        if normalized_form not in forms:
            continue
        if counts[normalized_form] >= latest_per_form:
            continue

        results.append(
            filing_from_block(recent, company, index)
        )
        counts[normalized_form] += 1

        if all(count >= latest_per_form for count in counts.values()):
            break

    return results


def quarter_from_date(date_value: str) -> str | None:
    try:
        parsed = date.fromisoformat(date_value)
    except ValueError:
        return None

    if parsed.month <= 3:
        return "Q1"
    if parsed.month <= 6:
        return "Q2"
    if parsed.month <= 9:
        return "Q3"
    return "Q4"


def find_filing_by_period(
    submissions: dict[str, Any],
    company: CompanyMatch,
    user_agent: str,
    form: str,
    year: int,
    quarter: str | None = None,
) -> Filing | None:
    """Find the newest filing whose report period matches year and optional quarter."""
    normalized_form = form.upper()
    normalized_quarter = quarter.upper() if quarter else None
    blocks = load_all_filing_blocks(submissions, user_agent)

    matches: list[Filing] = []
    for block in blocks:
        for index, block_form in enumerate(block["form"]):
            if str(block_form).upper() != normalized_form:
                continue

            report_date = str(block["reportDate"][index])
            if not report_date.startswith(f"{year}-"):
                continue

            if normalized_form == "10-Q" and normalized_quarter:
                filing_date = str(block["filingDate"][index])
                if quarter_from_date(filing_date) != normalized_quarter:
                    continue

            matches.append(filing_from_block(block, company, index))

    matches.sort(key=lambda item: (item.report_date, item.filing_date), reverse=True)
    return matches[0] if matches else None


def safe_path_part(value: str) -> str:
    value = value.strip().replace("/", "-").replace("\\", "-")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value)
    value = re.sub(r"\s+", "_", value)
    return value or "unknown"


def write_filing(filing: Filing, output_dir: Path, user_agent: str) -> dict[str, str]:
    target_dir = (
        output_dir
        / safe_path_part(filing.ticker)
        / safe_path_part(filing.form)
        / f"{filing.filing_date}_{safe_path_part(filing.accession_number)}"
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = target_dir / "metadata.json"
    document_path = target_dir / filing.primary_document

    document_bytes = fetch_bytes(filing.primary_document_url, user_agent)
    document_path.write_bytes(document_bytes)

    metadata = {
        "company_name": filing.company_name,
        "ticker": filing.ticker,
        "cik": filing.cik,
        "form": filing.form,
        "filing_date": filing.filing_date,
        "report_date": filing.report_date,
        "accession_number": filing.accession_number,
        "primary_document": filing.primary_document,
        "primary_doc_description": filing.primary_doc_description,
        "primary_document_url": filing.primary_document_url,
        "filing_directory_url": filing.filing_directory_url,
        "local_document_path": str(document_path),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "form": filing.form,
        "filing_date": filing.filing_date,
        "report_date": filing.report_date,
        "document_path": str(document_path),
        "metadata_path": str(metadata_path),
        "source_url": filing.primary_document_url,
    }


def write_index(output_dir: Path, company: CompanyMatch, saved_filings: list[dict[str, str]]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / safe_path_part(company.ticker) / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "company_match": {
            "company_name": company.title,
            "ticker": company.ticker,
            "cik": company.cik,
            "match_score": company.score,
        },
        "saved_filings": saved_filings,
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch latest SEC 10-K and/or 10-Q filings.")
    parser.add_argument("company", help="Company name or ticker, for example Apple, Microsoft, NVDA.")
    parser.add_argument(
        "--forms",
        nargs="+",
        default=list(DEFAULT_FORMS),
        help="SEC forms to fetch. Default: 10-K 10-Q",
    )
    parser.add_argument(
        "--latest-per-form",
        type=int,
        default=1,
        help="How many recent filings to save per form. Default: 1",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Report period year to fetch, for example 2025.",
    )
    parser.add_argument(
        "--quarter",
        choices=["Q1", "Q2", "Q3", "Q4", "q1", "q2", "q3", "q4"],
        help="Report period quarter for 10-Q. Uses report period end date.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT"),
        help="SEC User-Agent. Or set SEC_USER_AGENT environment variable.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="Delay between filing downloads to be polite to SEC EDGAR. Default: 0.2",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.user_agent:
        print(
            "Missing SEC User-Agent. Set SEC_USER_AGENT or pass --user-agent "
            '"Your Name your.email@example.com".',
            file=sys.stderr,
        )
        return 2

    forms = {str(form).upper() for form in args.forms}
    try:
        companies = load_companies(args.user_agent)
        company = find_company(args.company, companies)
        submissions = load_company_submissions(company.cik, args.user_agent)
        if args.year:
            filings = []
            for form in forms:
                filing = find_filing_by_period(
                    submissions=submissions,
                    company=company,
                    user_agent=args.user_agent,
                    form=form,
                    year=args.year,
                    quarter=args.quarter if form.upper() == "10-Q" else None,
                )
                if filing:
                    filings.append(filing)
        else:
            filings = filings_from_submissions(
                submissions=submissions,
                company=company,
                forms=forms,
                latest_per_form=args.latest_per_form,
            )

        if not filings:
            raise SecFetchError(f"No filings found for {company.title} with forms: {', '.join(sorted(forms))}")

        saved_filings: list[dict[str, str]] = []
        for filing in filings:
            saved_filings.append(write_filing(filing, args.output, args.user_agent))
            time.sleep(args.sleep_seconds)

        index_path = write_index(args.output, company, saved_filings)

    except SecFetchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Matched company: {company.title} ({company.ticker}, CIK {company.cik})")
    print(f"Index: {index_path}")
    for item in saved_filings:
        print(f"- {item['form']} filed {item['filing_date']}: {item['document_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
