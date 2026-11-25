# HierVRDEncoder

Иерархические представления PDF (page → section → document) с учётом layout, SSL на multi-positive InfoNCE.

Заметки разработки: [docs/NOTES.md](docs/NOTES.md).

## Запуск

Python ≥ 3.10.

Linux:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Дальше команды одинаковые для обеих платформ:

```bash
python scripts/sources/ccpdf_subset.py   # -> data/interim/ccpdf_subset.tsv
python scripts/download.py               # -> data/raw/ccpdf/pdfs/<doc_id>.pdf
python scripts/validate.py               # -> data/interim/ccpdf_subset_validation.csv
python scripts/build_manifest.py         # -> manifest/*.parquet
```

`download.py` идемпотентен: уже валидные файлы не перекачивает. Аргументы опциональны: `python scripts/download.py <list.tsv> <out_dir>` — так же качается любой другой источник.
Отчёт и валидация кладутся рядом со списком с его префиксом.

## Данные

Корпус **CCpdf**: <https://github.com/applicaai/CCpdf>, файл `ccpdf.tsv` в `data/raw/ccpdf/ccpdf.tsv`.

Что появляется после прогона:

| файл | содержимое |
| --- | --- |
| `data/interim/ccpdf_subset.tsv` | выборка: `n` документов (`n/2` ru / `n/2` en) |
| `data/raw/ccpdf/pdfs/<doc_id>.pdf` | скачанные PDF, имя = `id` из `ccpdf.tsv` |
| `data/interim/ccpdf_subset_validation.csv` | `id, ok, pages, size_mb, error` |
| `data/interim/ccpdf_subset_download_report.csv` | `id, url, result, source, history` |

`download.py` пробует по очереди: прямой URL → `web.archive.org` → повтор прямого URL.
Файл принимается, если начинается с `%PDF-` и `pypdf` читает хотя бы одну страницу.

Прямые URL из корпуса работают без прокси; обращение к `web.archive.org` без него не проходит — в отчёте это видно как `cdx_fail`.

## Парсер

Проверено на `28042b15ea145e9c3285189dabb7a506.pdf` (5 стр.).

| что | как |
| --- | --- |
| документ | `DocumentConverter().convert(path).document` |
| элементы в порядке чтения | `doc.iterate_items()` → `(item, level)`; `level` — глубина вложенности (1/2) |
| тип | `item.label`: `text`, `section_header`, `list_item`, `table`, `picture`, ... |
| страница | `item.prov[0].page_no` (int, с 1) |
| bbox | `item.prov[0].bbox` → `l, t, r, b` + `coord_origin = BOTTOMLEFT` |
| символы | `item.prov[0].charspan = [start, end]` |
| таблица | `item.data.table_cells` (текст + `start_row_offset_idx`/`start_col_offset_idx` + spans), `num_rows`, `num_cols`, `export_to_html(doc)` |
| рисунок | `item.image`, `item.captions` |
| ссылки/иерархия | `item.self_ref` (`#/texts/0`), `parent`, `children`, `content_layer` |
| страницы | `doc.pages[no].size` → `width`, `height` |

## Манифест (`build_manifest.py`)

Конфигурация парсера: `do_ocr=False` (обоснование — в NOTES), `do_table_structure=True`, `do_formula_enrichment=False`. JSON каждого документа кэшируется в `data/processed/docling/<doc_id>.json`, повторный запуск не перепарсивает.

Выход: `manifest/documents.parquet`, `manifest/blocks.parquet`, `manifest/rejected.csv`.

| файл | поля |
| --- | --- |
| `documents.parquet` | `doc_id, domain, url, lang, pages_num, n_blocks, n_text_blocks, n_empty_text, by_type, split, parser, ocr, formula_enrichment, cached, elapsed_s, s_per_page` |
| `blocks.parquet` | `block_id, doc_id, page, reading_order, type, label, level, bbox_l/t/r/b, page_w/h, text, text_len, charspan_start/end, self_ref` |

- `block_id = {doc_id}:p{page_no:04d}:b{index:03d}`, `index` — порядок внутри страницы.
- bbox нормализован в Topleft (`t' = H - t`, `b' = H - b`), потому что Docling отдаёт Bottomleft.
- `type` — маппинг `label` в (`heading / text / list / table / picture / formula / caption / code / furniture / index`), `label` — сырой Docling.
- `text` не всегда «текст элемента»: у `table`/`index` это markdown, у `picture` — склеенные подписи, у `formula` до включения  пусто. Поэтому доля пустых блоков считается только по текстовым типам (`TEXT_TYPES`), а подпись рисунка может дублироваться с блоком `caption`.

## Структура

```python
configs/topics/       # темы для OpenAlex (en/ru)
scripts/sources/      # по файлу на источник данных
  ccpdf_subset.py     # создание TSV сабсета (id, url, lang, ...)
  openalex.py         # сбор OA-статей из OpenAlex
scripts/download.py   # TSV(id, url) → PDF + отчёт
scripts/validate.py   # PDF → validation.csv (pypdf)
scripts/build_manifest.py  # PDF → manifest/*.parquet (Docling) + кэш JSON
scripts/recon_docling.py   # печать полей Docling (проверка API при смене версии)
data/raw/<source>/    # ccpdf/ccpdf.tsv + ccpdf/pdfs/, openalex/ — слот под второй корпус
data/interim/         # <source>_subset.tsv и производные <source>_*.csv
data/processed/docling/    # кэш DoclingDocument JSON по doc_id
src/hiervrd/          # model, loss
manifest/             # parquet от build_manifest.py
```
