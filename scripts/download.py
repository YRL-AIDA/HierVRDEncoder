import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from validate import check, write_validation

ROOT = Path(__file__).resolve().parents[1]
INPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/interim/ccpdf_subset.tsv"
OUT_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/raw/ccpdf/pdfs"
REPORT = INPUT.parent / f"{INPUT.stem}_download_report.csv"

DIRECT_WORKERS = 8
ARCHIVE_WORKERS = 4
TIMEOUT = (10, 60)
ATTEMPTS = 2
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) HierVRDEncoder/0.1"}


def target(doc_id):
    return OUT_DIR / f"{doc_id}.pdf"


def is_valid(path):
    ok, pages, _ = check(path)
    return ok and pages > 0


def is_pdf(data):
    return data[:5] == b"%PDF-"


def fetch(url):
    r = requests.get(url, timeout=TIMEOUT, headers=UA, allow_redirects=True)
    r.raise_for_status()
    return r.content


def save(doc_id, data):
    dst = target(doc_id)
    dst.write_bytes(data)
    if is_valid(dst):
        return True
    dst.unlink(missing_ok=True)
    return False


def from_web(item):
    doc_id, url = item["id"], item["url"]
    dst = target(doc_id)
    if dst.exists() and is_valid(dst):
        return doc_id, "cached", "web"
    err = ""
    for _ in range(ATTEMPTS):
        try:
            data = fetch(url)
        except Exception as e:
            err = type(e).__name__
            continue
        if not is_pdf(data):
            return doc_id, "not_pdf", "web"
        if save(doc_id, data):
            return doc_id, "ok", "web"
        return doc_id, "invalid_pdf", "web"
    return doc_id, f"fail:{err}", "web"


def archive_timestamp(url):
    api = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={url}&output=txt&limit=1&filter=statuscode:200"
    )
    r = requests.get(api, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    lines = [line for line in r.text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    parts = lines[0].split(" ")
    return parts[1] if len(parts) > 1 else None


def from_archive(item):
    doc_id, url = item["id"], item["url"]
    dst = target(doc_id)
    if dst.exists() and is_valid(dst):
        return doc_id, "cached", "archive.org"
    try:
        timestamp = archive_timestamp(url)
    except Exception as e:
        return doc_id, f"cdx_fail:{type(e).__name__}", "archive.org"
    if not timestamp:
        return doc_id, "not_in_archive", "archive.org"

    for candidate in (
        f"https://web.archive.org/web/{timestamp}id_/{url}",
        f"https://web.archive.org/web/{timestamp}/{url}",
    ):
        try:
            data = fetch(candidate)
        except Exception:
            continue
        if not is_pdf(data):
            continue
        if save(doc_id, data):
            return doc_id, "ok", "archive.org"
    return doc_id, "fail", "archive.org"


def succeeded(status, doc_id):
    return status.get(doc_id, {}).get("result") in ("ok", "cached")


def record(status, doc_id, name, result, source):
    state = status.setdefault(doc_id, {"result": "", "source": "", "history": []})
    state["history"].append(f"{name}:{result}")
    if state["result"] not in ("ok", "cached"):
        state["result"] = result
        state["source"] = source


def run_pass(name, fn, workers, items, status):
    todo = [item for item in items if not succeeded(status, item["id"])]
    if not todo:
        print(f"[{name}] нечего делать")
        return
    print(f"[{name}] документов: {len(todo)}")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for doc_id, result, source in pool.map(fn, todo):
            record(status, doc_id, name, result, source)
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(todo)}")


def main():
    df = pd.read_csv(INPUT, sep="\t")
    items = df.to_dict("records")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"в списке: {len(items)}, уже на диске: {sum(1 for i in items if target(i['id']).exists())}")

    status = {}
    run_pass("web", from_web, DIRECT_WORKERS, items, status)
    run_pass("archive.org", from_archive, ARCHIVE_WORKERS, items, status)
    run_pass("web (retry)", from_web, DIRECT_WORKERS, items, status)

    with open(REPORT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "url", "result", "source", "history"])
        for item in items:
            state = status.get(item["id"], {"result": "not_attempted", "source": "", "history": []})
            w.writerow(
                [item["id"], item["url"], state["result"], state["source"], " | ".join(state["history"])]
            )

    write_validation(OUT_DIR, INPUT.parent / f"{INPUT.stem}_validation.csv")

    good = [k for k, v in status.items() if v["result"] in ("ok", "cached")]
    print(f"итог: живых {len(good)} из {len(items)}")
    print("отчёт:", REPORT)


if __name__ == "__main__":
    main()
