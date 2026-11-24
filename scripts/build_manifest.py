import csv
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "data/raw/ccpdf/pdfs"
SUBSET = ROOT / "data/interim/ccpdf_subset.tsv"
VALID = ROOT / "data/interim/ccpdf_subset_validation.csv"
CACHE = ROOT / "data/processed/docling"
OUT = ROOT / "manifest"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 0

TOL = 1.0  # pt, допуск для bbox
TYPE_MAP = {
    "title": "heading",
    "section_header": "heading",
    "text": "text",
    "paragraph": "text",
    "list_item": "list",
    "table": "table",
    "picture": "picture",
    "formula": "formula",
    "code": "code",
    "caption": "caption",
    "document_index": "index",
    "page_header": "furniture",
    "page_footer": "furniture",
}
TEXT_TYPES = {"text", "heading", "list", "caption"}

logging.getLogger("docling").setLevel(logging.ERROR)
logging.getLogger("pypdf").setLevel(logging.ERROR)


def make_converter():
    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True
    options.do_formula_enrichment = False
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def load_document(converter, pdf, doc_id):
    cache = CACHE / f"{doc_id}.json"
    if cache.exists():
        return DoclingDocument.load_from_json(cache), 0.0, True
    started = time.perf_counter()
    doc = converter.convert(str(pdf)).document
    elapsed = time.perf_counter() - started
    CACHE.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(cache)
    return doc, elapsed, False


def block_text(item, doc):
    name = item.__class__.__name__
    if name == "TableItem":
        try:
            return item.export_to_markdown(doc=doc)
        except Exception:
            try:
                return item.export_to_html(doc=doc)
            except Exception:
                return ""
    if name == "PictureItem":
        texts = []
        for caption in getattr(item, "captions", None) or []:
            try:
                texts.append(caption.resolve(doc).text or "")
            except Exception:
                pass
        return "\n".join(t for t in texts if t)
    return getattr(item, "text", "") or ""


def extract_blocks(doc, doc_id):
    rows = []
    per_page = {}
    for order, (item, level) in enumerate(doc.iterate_items()):
        prov = getattr(item, "prov", None) or []
        if not prov:
            continue
        first = prov[0]
        page_no = int(first.page_no)
        size = doc.pages[page_no].size
        width, height = float(size.width), float(size.height)
        bbox = first.bbox
        index = per_page.get(page_no, 0)
        per_page[page_no] = index + 1

        label = str(item.label)
        text = block_text(item, doc)
        charspan = list(getattr(first, "charspan", None) or [])
        rows.append(
            {
                "block_id": f"{doc_id}:p{page_no:04d}:b{index:03d}",
                "doc_id": doc_id,
                "page": page_no,
                "reading_order": order,
                "type": TYPE_MAP.get(label, label),
                "label": label,
                "level": int(level),
                "bbox_l": round(float(bbox.l), 2),
                "bbox_t": round(height - float(bbox.t), 2),
                "bbox_r": round(float(bbox.r), 2),
                "bbox_b": round(height - float(bbox.b), 2),
                "page_w": round(width, 2),
                "page_h": round(height, 2),
                "text": text,
                "text_len": len(text),
                "charspan_start": int(charspan[0]) if len(charspan) > 0 else -1,
                "charspan_end": int(charspan[1]) if len(charspan) > 1 else -1,
                "self_ref": str(getattr(item, "self_ref", "")),
            }
        )
    return rows


def check_blocks(rows):
    problems = []
    order = [r["reading_order"] for r in rows]
    if order != list(range(len(rows))):
        problems.append("reading_order_not_contiguous")
    for r in rows:
        if not (
            -TOL <= r["bbox_l"] <= r["bbox_r"] <= r["page_w"] + TOL
            and -TOL <= r["bbox_t"] <= r["bbox_b"] <= r["page_h"] + TOL
        ):
            problems.append(f"bbox_out_of_page:{r['block_id']}")
            break
    return problems


def main():
    subset = pd.read_csv(SUBSET, sep="\t")
    valid = pd.read_csv(VALID)
    docs = subset.merge(valid[valid["ok"]][["id", "pages"]], left_on="id", right_on="id")
    if LIMIT:
        docs = docs.head(LIMIT)

    converter = make_converter()
    block_rows, doc_rows, rejected = [], [], []
    started_all = time.perf_counter()

    for done, (_, row) in enumerate(docs.iterrows(), start=1):
        doc_id = row["id"]
        pdf = PDF_DIR / f"{doc_id}.pdf"
        try:
            doc, elapsed, cached = load_document(converter, pdf, doc_id)
        except Exception as e:
            rejected.append({"doc_id": doc_id, "reason": f"parse:{type(e).__name__}: {e}"[:160]})
            print(f"[{done}/{len(docs)}] {doc_id} FAIL {type(e).__name__}")
            continue

        blocks = extract_blocks(doc, doc_id)
        if not blocks:
            rejected.append({"doc_id": doc_id, "reason": "no_blocks"})
            print(f"[{done}/{len(docs)}] {doc_id} пусто")
            continue

        problems = check_blocks(blocks)
        if problems:
            rejected.append({"doc_id": doc_id, "reason": ";".join(problems)})

        by_type = {}
        for b in blocks:
            by_type[b["type"]] = by_type.get(b["type"], 0) + 1
        text_blocks = [b for b in blocks if b["type"] in TEXT_TYPES]
        empty = sum(1 for b in text_blocks if not b["text"].strip())

        doc_rows.append(
            {
                "doc_id": doc_id,
                "domain": row["domain"],
                "url": row["url"],
                "lang": row["lang_detected"],
                "pages_num": len(doc.pages),
                "n_blocks": len(blocks),
                "n_text_blocks": len(text_blocks),
                "n_empty_text": empty,
                "by_type": json.dumps(by_type, ensure_ascii=False, sort_keys=True),
                "split": "",
                "parser": "docling-2.152.0",
                "ocr": False,
                "formula_enrichment": False,
                "cached": cached,
                "elapsed_s": round(elapsed, 1),
                "s_per_page": round(elapsed / max(len(doc.pages), 1), 2),
            }
        )
        block_rows.extend(blocks)
        print(
            f"[{done}/{len(docs)}] {doc_id} стр={len(doc.pages)} блоков={len(blocks)} "
            f"пусто={empty} {'(кэш)' if cached else f'{elapsed:.0f}с'} {problems or ''}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(doc_rows)
    blocks = pd.DataFrame(block_rows)
    documents.to_parquet(OUT / "documents.parquet", index=False)
    blocks.to_parquet(OUT / "blocks.parquet", index=False)
    with open(OUT / "rejected.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "reason"])
        w.writeheader()
        w.writerows(rejected)

    total_pages = int(documents["pages_num"].sum()) if len(documents) else 0
    text_total = int(documents["n_text_blocks"].sum()) if len(documents) else 0
    empty_total = int(documents["n_empty_text"].sum()) if len(documents) else 0
    print(f"\nдокументов: {len(documents)}, блоков: {len(blocks)}, страниц: {total_pages}")
    print(f"пустых текстовых блоков: {empty_total} из {text_total} "
          f"({100 * empty_total / max(text_total, 1):.1f}%)")
    if len(blocks):
        print("по типам:", dict(blocks["type"].value_counts()))
    print(f"отклонено: {len(rejected)}, за {time.perf_counter() - started_all:.0f} с")
    print("записал:", OUT)


if __name__ == "__main__":
    main()
