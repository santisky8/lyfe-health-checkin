"""All MedlinePlus health topics (US National Library of Medicine), about 1,000, public domain.

The bulk XML lives on medlineplus.gov; this uses the NLM search API instead, paging through
wildcard searches and keeping each topic once.
"""
import xml.etree.ElementTree as ET

from common import get, strip_html, write_csv

API = "https://wsearch.nlm.nih.gov/ws/query"
PAGE = 500


def fields(doc):
    out = {}
    for c in doc.findall("content"):
        name, text = c.get("name"), strip_html(c.text)
        out.setdefault(name, []).append(text)
    return out


def main():
    rows, seen = [], set()
    for term in ["a*", "e*", "i*", "o*", "s*", "t*"]:
        start = 0
        while True:
            root = ET.fromstring(get(API, {"db": "healthTopics", "term": term,
                                           "retmax": PAGE, "retstart": start}))
            docs = list(root.iter("document"))
            for doc in docs:
                url = doc.get("url")
                if url in seen or "/spanish/" in url:
                    continue
                seen.add(url)
                f = fields(doc)
                rows.append({
                    "doc_id": f"mlp-{len(rows)}",
                    "title": f.get("title", [""])[0],
                    "also_called": "; ".join(f.get("altTitle", [])),
                    "groups": "; ".join(f.get("groupName", [])),
                    "text": f.get("FullSummary", [""])[0],
                    "url": url,
                    "source": "MedlinePlus (NLM, US)",
                })
            start += PAGE
            if len(docs) < PAGE:
                break
    write_csv("medlineplus_topics", rows,
              ["doc_id", "title", "also_called", "groups", "text", "url", "source"])


if __name__ == "__main__":
    main()
