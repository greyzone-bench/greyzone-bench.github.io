#!/usr/bin/env python3
"""Refresh assets/paper-first-page.png from the latest arXiv version of the paper.

data/paper.json records the arXiv id and the version the thumbnail was
rendered from. The script asks the arXiv API for the latest version and only
when it is newer (or the thumbnail is missing, or --force) downloads that
version's PDF and renders page 1 with pdftoppm (poppler-utils). Runs daily in
CI (.github/workflows/paper-thumbnail.yml); safe to run locally.

Usage:
    python3 scripts/update_paper_thumbnail.py [--force]
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER_PATH = ROOT / "data" / "paper.json"
THUMB_PATH = ROOT / "assets" / "paper-first-page.png"
THUMB_WIDTH = 1080
ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "greyzone-bench.github.io paper-thumbnail sync"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()


def latest_version(arxiv_id: str) -> int:
    feed = ET.fromstring(fetch(f"https://export.arxiv.org/api/query?id_list={arxiv_id}"))
    entry_id = feed.findtext(f"{ATOM}entry/{ATOM}id", "")
    m = re.search(rf"{re.escape(arxiv_id)}v(\d+)$", entry_id)
    if not m:
        raise SystemExit(f"arXiv API returned no entry for {arxiv_id} (got {entry_id!r})")
    return int(m[1])


def render_first_page(pdf: bytes, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "paper.pdf"
        src.write_bytes(pdf)
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile",
                        "-scale-to-x", str(THUMB_WIDTH), "-scale-to-y", "-1",
                        str(src), str(Path(tmp) / "page")], check=True)
        out.write_bytes((Path(tmp) / "page.png").read_bytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-render even if the recorded version is the latest")
    args = ap.parse_args()

    paper = json.loads(PAPER_PATH.read_text())
    arxiv_id, current = paper["arxivId"], paper.get("thumbnailVersion")
    latest = latest_version(arxiv_id)
    if latest == current and THUMB_PATH.is_file() and not args.force:
        print(f"thumbnail up to date ({arxiv_id}v{latest})")
        return 0

    pdf = fetch(f"https://arxiv.org/pdf/{arxiv_id}v{latest}")
    if not pdf.startswith(b"%PDF"):
        raise SystemExit(f"https://arxiv.org/pdf/{arxiv_id}v{latest} did not return a PDF")
    render_first_page(pdf, THUMB_PATH)
    paper["thumbnailVersion"] = latest
    PAPER_PATH.write_text(json.dumps(paper, indent=2) + "\n")
    print(f"rendered {THUMB_PATH.relative_to(ROOT)} from {arxiv_id}v{latest} (was {current or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
