from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/raw/ccpdf/ccpdf.tsv"
OUTPUT = ROOT / "data/interim/ccpdf_subset.tsv"
TARGET = 60  # документов на язык


def stratified(g, n, seed=42):
    n = min(n, len(g))
    out = []
    for bucket, part in g.groupby("bucket", observed=True):
        k = max(2, round(n * len(part) / len(g)))
        print(bucket, k, len(part), len(g))
        out.append(part.sample(min(k, len(part)), random_state=seed))
    return pd.concat(out).drop_duplicates("id").head(n)


def main():
    df = pd.read_csv(INPUT, sep="\t", low_memory=False)

    needs_ocr = df["needs_ocr"].astype(str).str.lower().isin(["true", "1", "yes"])
    d = df[~needs_ocr]
    d = d[d["lang_detected"].isin(["ru", "en"]) & (d["final_lang_score"] > 0.9)]
    d = d[d["pages_num"] >= 3]
    d = d[d["tokens_num"] / d["pages_num"] >= 150]
    d = d.drop_duplicates("url")
    print("после фильтров:", len(d), dict(d["lang_detected"].value_counts()))

    d = d.groupby("domain", group_keys=False).head(3)

    bins = [2, 5, 10, 20, 10**6]
    labels = ["3-5", "6-10", "11-20", "20+"]
    d = d.assign(bucket=pd.cut(d["pages_num"], bins=bins, labels=labels))
    sub = pd.concat([stratified(d[d["lang_detected"] == lg], TARGET) for lg in ["ru", "en"]])

    print("к скачиванию:", len(sub), dict(sub["lang_detected"].value_counts()))
    print("страниц всего:", sub["pages_num"].sum(), "≈ МБ:", round(sub["disc_size"].sum() / 1e6))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sub.to_csv(OUTPUT, sep="\t", index=False)
    print("записал:", OUTPUT)


if __name__ == "__main__":
    main()
