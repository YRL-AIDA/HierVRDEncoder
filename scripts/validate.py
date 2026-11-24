import csv
import logging
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = (
    Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/raw/ccpdf/pdfs"
)
OUT = (
    Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/interim/ccpdf_subset_validation.csv"
)

logging.getLogger("pypdf").setLevel(logging.ERROR)


def check(path):
    try:
        pages = len(PdfReader(str(path)).pages)
        return True, pages, ""
    except Exception as e:
        return False, "", f"{type(e).__name__}: {e}"[:120]


def write_validation(pdf_dir=PDF_DIR, out=OUT):
    rows = []
    for p in sorted(Path(pdf_dir).glob("*.pdf")):
        ok, pages, err = check(p)
        rows.append(
            {
                "id": p.stem,
                "ok": ok,
                "pages": pages if ok else "",
                "size_mb": round(p.stat().st_size / 1e6, 2),
                "error": err,
            }
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "ok", "pages", "size_mb", "error"])
        w.writeheader()
        w.writerows(rows)

    good = [r for r in rows if r["ok"]]
    print(f"файлов: {len(rows)}, валидных: {len(good)}, страниц: {sum(r['pages'] for r in good)}")
    for r in rows:
        if not r["ok"]:
            print("битый:", r["id"], r["size_mb"], "МБ |", r["error"])
    print("записал:", out)


if __name__ == "__main__":
    write_validation()
