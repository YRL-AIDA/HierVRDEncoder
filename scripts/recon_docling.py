import sys
import time
from collections import Counter
from pathlib import Path

from docling.document_converter import DocumentConverter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "data/raw/ccpdf/pdfs/28042b15ea145e9c3285189dabb7a506.pdf"
PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 6


def main():
    import docling

    print("docling:", getattr(docling, "__version__", "?"), "| файл:", PDF.name)
    started = time.perf_counter()
    result = DocumentConverter().convert(str(PDF))
    elapsed = time.perf_counter() - started
    doc = result.document
    n_pages = len(doc.pages)
    print(f"время: {elapsed:.1f} с, страниц: {n_pages}, с/страница: {elapsed / n_pages:.1f}")

    print("\n== страницы: size и origin bbox ==")
    for no, page in sorted(doc.pages.items())[:2]:
        print(f"  p{no}: width={page.size.width:.1f} height={page.size.height:.1f}")

    items = list(doc.iterate_items())
    labels = Counter(str(item.label) for item, _ in items)
    print("\n== элементов:", len(items), "==")
    print("метки:", dict(labels))
    print("уровни (level из iterate_items):", dict(Counter(level for _, level in items)))

    print("\n== первые", LIMIT, "элементов ==")
    for idx, (item, level) in enumerate(items[:LIMIT]):
        prov = getattr(item, "prov", None) or []
        first = prov[0] if prov else None
        bbox = getattr(first, "bbox", None)
        print(
            f"[{idx:02d}] {item.__class__.__name__} label={item.label} level={level} "
            f"page={getattr(first, 'page_no', None)} self_ref={getattr(item, 'self_ref', None)}"
        )
        if bbox is not None:
            print(
                f"     bbox l={bbox.l:.1f} t={bbox.t:.1f} r={bbox.r:.1f} b={bbox.b:.1f} "
                f"origin={bbox.coord_origin}"
            )
        text = getattr(item, "text", "") or ""
        if text:
            print(f"     text({len(text)}): {text[:80]!r}")

    tables = [item for item, _ in items if item.__class__.__name__ == "TableItem"]
    print("\n== таблицы:", len(tables), "==")
    for t in tables[:2]:
        data = t.data
        print(
            f"  cells={len(data.table_cells)} rows={len(data.grid)} "
            f"num_rows={data.num_rows} num_cols={data.num_cols}"
        )
        for cell in data.table_cells[:3]:
            print(
                f"    cell text={cell.text[:40]!r} row={cell.start_row_offset_idx} "
                f"col={cell.start_col_offset_idx} span=({cell.row_span},{cell.col_span})"
            )
        html = t.export_to_html(doc=doc)
        print(f"  html: {len(html)} символов, начало: {html[:80]!r}")

    pictures = [item for item, _ in items if item.__class__.__name__ == "PictureItem"]
    print("\n== рисунки:", len(pictures), "==")
    for p in pictures[:2]:
        caps = getattr(p, "captions", None) or []
        print(f"  image={p.image.size if getattr(p, 'image', None) else None} captions={len(caps)}")

    data = doc.export_to_dict()
    print("\n== export_to_dict ==")
    print("верхний уровень:", list(data.keys()))
    print("поля элемента:", list((data.get("texts") or [{}])[0].keys()))
    print("prov элемента:", (data.get("texts") or [{}])[0].get("prov"))
    pages = data.get("pages") or {}
    print("pages: тип", type(pages).__name__, "ключи", list(pages)[:3])
    if pages:
        print("поля страницы:", list(next(iter(pages.values())).keys()))

    empty = sum(1 for item, _ in items if not (getattr(item, "text", "") or "").strip())
    print(f"\nэлементов с пустым text: {empty} из {len(items)}")


if __name__ == "__main__":
    main()
