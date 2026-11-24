# HierVRDEncoder

Иерархические представления PDF (page → section → document) с учётом layout, SSL на
multi-positive InfoNCE.

## Запуск

Python ≥ 3.10.

Linux:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/sources/ccpdf_subset.py   # -> data/interim/ccpdf_subset.tsv
python scripts/download.py               # -> data/raw/ccpdf/pdfs/<doc_id>.pdf
python scripts/validate.py               # -> data/interim/ccpdf_subset_validation.csv
```

Windows (PowerShell) — то же самое:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
python scripts\sources\ccpdf_subset.py
python scripts\download.py
python scripts\validate.py
```

`download.py` идемпотентен: уже валидные файлы не перекачивает. Аргументы опциональны:
`python scripts/download.py <list.tsv> <out_dir>` — так же качается любой другой источник.
Отчёт и валидация кладутся рядом со списком с его префиксом.

## Данные

Корпус **CCpdf**: https://github.com/applicaai/CCpdf, файл `ccpdf.tsv` в
`data/raw/ccpdf/ccpdf.tsv`.

Что появляется после прогона:

| файл | содержимое |
|---|---|
| `data/interim/ccpdf_subset.tsv` | выборка: 120 документов (60 ru / 60 en) |
| `data/raw/ccpdf/pdfs/<doc_id>.pdf` | скачанные PDF, имя = `id` из `ccpdf.tsv` |
| `data/interim/ccpdf_subset_validation.csv` | `id, ok, pages, size_mb, error` |
| `data/interim/ccpdf_subset_download_report.csv` | `id, url, result, source, history` |

`download.py` пробует по очереди: прямой URL → `web.archive.org` → повтор прямого URL.
Файл принимается, если начинается с `%PDF-` и `pypdf` читает хотя бы одну страницу.

**Для шага `archive.org` нужен VPN:** без него `web.archive.org` не отвечает, и в отчёте
будет `cdx_fail` (прямые URL из корпуса работают без VPN).

## Парсер: Docling 2.152.0

Версия зафиксирована в `requirements.txt`: имена полей между версиями менялись, поэтому
`scripts/recon_docling.py` держим как проверку API (`python scripts/recon_docling.py <pdf>`).

Что реально приходит (проверено на `28042b15ea145e9c3285189dabb7a506.pdf`, 5 стр.):

| что | как |
|---|---|
| документ | `DocumentConverter().convert(path).document` |
| элементы в порядке чтения | `doc.iterate_items()` → `(item, level)`; `level` — глубина вложенности (1/2) |
| тип | `item.label`: `text`, `section_header`, `list_item`, `table`, `picture`, ... |
| страница | `item.prov[0].page_no` (int, с 1) |
| bbox | `item.prov[0].bbox` → `l, t, r, b` + `coord_origin = BOTTOMLEFT` (p1: 595.3 × 841.9 pt) |
| символы | `item.prov[0].charspan = [start, end]` |
| таблица | `item.data.table_cells` (текст + `start_row_offset_idx`/`start_col_offset_idx` + spans), `num_rows`, `num_cols`, `export_to_html(doc)` |
| рисунок | `item.image`, `item.captions` |
| ссылки/иерархия | `item.self_ref` (`#/texts/0`), `parent`, `children`, `content_layer` |
| страницы | `doc.pages[no].size` → `width`, `height` |

Скорость: **4.3 с/страница** на CPU (5 стр. за 21.6 с с учётом загрузки весов), то есть
1 493 страницы ≈ 1.8 ч, а не 6-12 ч по первоначальной оценке.

Важно для `build_manifest.py`: у таблиц и рисунков `text` пустой (у таблицы — `data`,
у рисунка — `image`), поэтому «доля пустых блоков» считается только по текстовым меткам.


## Структура

```
configs/topics/       # темы для OpenAlex (en/ru)
scripts/sources/      # по файлу на источник данных
  ccpdf_subset.py     # создание TSV сабсета (id, url, lang, ...)
  openalex.py         # сбор OA-статей из OpenAlex (фаза 2, не в quickstart)
scripts/download.py   # TSV(id, url) → PDF + отчёт
scripts/validate.py   # PDF → validation.csv (pypdf)
data/raw/<source>/    # ccpdf/ccpdf.tsv + ccpdf/pdfs/, openalex/ — слот под второй корпус
data/interim/         # <source>_subset.tsv и производные <source>_*.csv
src/hiervrd/          # model, loss, data
manifest/             # parquet от build_manifest.py
```
## Напоминалка
Правило, чтобы структура не переделывалась: любой источник отдаёт TSV с колонками
`id, url, lang`, `download.py`/`validate.py` безразличны к источнику. OpenAlex на фазе 2
разделится на `openalex_list.py` (только TSV) + общий `download.py`
