"""MedlinePlus health topics (US National Library of Medicine). No key."""
import xml.etree.ElementTree as ET

from common import TOPICS, get, strip_html, write_csv

API = "https://wsearch.nlm.nih.gov/ws/query"


def main():
    rows, seen = [], set()
    for topic in TOPICS:
        root = ET.fromstring(get(API, {"db": "healthTopics", "term": topic, "retmax": 3}))
        for doc in root.iter("document"):
            url = doc.get("url")
            if url in seen:
                continue
            seen.add(url)
            fields = {c.get("name"): strip_html(c.text) for c in doc.findall("content")}
            rows.append({
                "doc_id": f"mlp-{len(rows)}",
                "topic": topic,
                "title": fields.get("title", ""),
                "text": fields.get("FullSummary", ""),
                "url": url,
                "source": "MedlinePlus (NLM, US)",
            })
    write_csv("medlineplus", rows, ["doc_id", "topic", "title", "text", "url", "source"])


if __name__ == "__main__":
    main()
