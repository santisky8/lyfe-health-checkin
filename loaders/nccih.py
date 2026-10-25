"""Herbs, supplements and practices from NCCIH (US National Center for Complementary and
Integrative Health): every "Herbs at a Glance" fact sheet plus a few practice pages
(homeopathy, probiotics, ...). Public domain. Each row is one section of one page, so the
safety and interaction notes stay whole: "What do we know about safety?" is never cut off.
"""
import html as htmllib
import re
import time

from common import get, strip_html, write_csv

BASE = "https://www.nccih.nih.gov"
EXTRA = ["homeopathy", "probiotics-what-you-need-to-know", "using-dietary-supplements-wisely",
         "melatonin-what-you-need-to-know", "omega3-supplements-what-you-need-to-know",
         "aromatherapy"]
SKIP = {"atoz", "espanol", "herbsataglance", "herblist-app", "know-science", "pain", "providers",
        "safety", "tips", "complementary-alternative-or-integrative-health-whats-in-a-name"}


def pages():
    index = get(f"{BASE}/health/herbsataglance")
    slugs = sorted(set(re.findall(r'href="/health/([a-z0-9-]+)"', index)) - SKIP)
    return slugs + [s for s in EXTRA if s not in slugs]


def sections(page_html):
    main = re.search(r"<main.*?</main>", page_html, re.S)
    body = main.group(0) if main else page_html
    title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = strip_html(title.group(1)) if title else ""
    parts = re.split(r"<h2[^>]*>(.*?)</h2>", body, flags=re.S)
    out = []
    for heading, text in zip(parts[1::2], parts[2::2]):
        heading, text = strip_html(heading), strip_html(text)
        if len(text) > 80 and not re.match(r"(For More Information|Key References|Other References|"
                                             r"Acknowledgments|NCCIH Clearinghouse)", heading, re.I):
            out.append((heading, text[:2500]))
    return htmllib.unescape(title), out


def main():
    rows = []
    for slug in pages():
        try:
            title, secs = sections(get(f"{BASE}/health/{slug}"))
        except Exception as e:  # a missing page should not stop the rest
            print(f"skip {slug}: {e}")
            continue
        for i, (heading, text) in enumerate(secs):
            rows.append({"doc_id": f"nccih-{slug}-{i}", "title": title, "section": heading,
                         "text": text, "url": f"{BASE}/health/{slug}",
                         "source": "NCCIH (NIH, US)"})
        time.sleep(0.3)
    write_csv("nccih", rows, ["doc_id", "title", "section", "text", "url", "source"])


if __name__ == "__main__":
    main()
