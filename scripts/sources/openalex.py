import hashlib
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

import requests

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
TOPICS = {
    "en": ROOT / "configs/topics/en_topics.txt",
    "ru": ROOT / "configs/topics/ru_topics.txt",
}
OUT = ROOT / "data/raw/openalex/pdfs"
PER_TOPIC = int(os.environ.get("PER_TOPIC", "5"))
MAILTO = os.environ.get("OPENALEX_MAILTO", "anonymous@example.com")
API_KEY = os.environ.get("API_KEY", "")

BLOCKED_HOSTS = (
    "tandfonline.com",
    "wiley.com",
    "oup.com",
    "sciencedirect.com",
    "springer.com",
    "iopscience.iop.org",
    "sagepub.com",
    "cambridge.org",
    "direct.mit.edu",
    "jstor.org",
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": f"HierVRDEncoder/0.1 (mailto:{MAILTO})"})


def openalex_items(topic, limit, lang):
    response = SESSION.get(
        "https://api.openalex.org/works",
        params={
            "filter": f"language:{lang},is_oa:true,type:article,title_and_abstract.search:{topic}",
            "per-page": min(limit, 100),
            "mailto": MAILTO
        },
        timeout=60,
    )
    response.raise_for_status()
    for work in response.json()["results"]:
        locations = [loc for loc in [work.get("best_oa_location")] + work.get("locations", []) if loc]
        locations.sort(key=lambda loc: loc.get("host_type") != "repository")
        urls = []
        for location in locations:
            url = location.get("pdf_url")
            if url and url not in urls:
                urls.append(url)
        if urls:
            yield urls, work.get("doi") or work.get("id")


def slug(text):
    text = text.lower().replace("https://doi.org/", "").replace("http://", "").replace("https://", "")
    return re.sub(r"[^a-z0-9._-]+", "_", text).strip("_")[:80]


def filename(url, hint):
    name = slug(hint) if hint else ""
    if not name:
        parts = [part for part in url.split("?")[0].split("/") if part]
        name = slug(parts[-2] if len(parts) > 1 and parts[-1] == "pdf" else parts[-1])
    digest = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{name or 'doc'}_{digest}.pdf"


def download(urls, hint, folder):
    for url in urls[:3]:
        host = urlparse(url).netloc
        if any(host.endswith(blocked) for blocked in BLOCKED_HOSTS):
            continue
        path = folder / filename(url, hint)
        if path.exists():
            return path
        try:
            response = SESSION.get(url, timeout=20)
        except requests.RequestException:
            continue
        if response.status_code == 200 and response.content[:4] == b"%PDF":
            path.write_bytes(response.content)
            return path
    return None


def main():
    for lang, topics_file in TOPICS.items():
        folder = OUT / lang
        folder.mkdir(parents=True, exist_ok=True)
        for topic in Path(topics_file).read_text(encoding="utf-8").splitlines():
            if not topic.strip():
                continue
            print(f"[{lang}] {topic}")
            for urls, hint in openalex_items(topic, PER_TOPIC, lang):
                path = download(urls, hint, folder)
                print("  ok  " + path.name if path else "  skip")
                time.sleep(0.5)
            time.sleep(1)


if __name__ == "__main__":
    main()
