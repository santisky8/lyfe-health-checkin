"""PubMed evidence: recent reviews per topic (NCBI E-utilities). No key, 3 requests a second."""
import time
import xml.etree.ElementTree as ET

from common import TOPICS, get, get_json, write_csv

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def main():
    rows = []
    for topic in TOPICS:
        term = f"({topic}[Title]) AND (systematic review[pt] OR meta-analysis[pt]) AND humans[mh]"
        ids = get_json(f"{EUTILS}/esearch.fcgi",
                       {"db": "pubmed", "term": term, "retmax": 5, "sort": "relevance",
                        "retmode": "json"})["esearchresult"]["idlist"]
        time.sleep(0.4)
        if not ids:
            continue
        root = ET.fromstring(get(f"{EUTILS}/efetch.fcgi",
                                 {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}))
        time.sleep(0.4)
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//PMID")
            abstract = " ".join("".join(a.itertext()) for a in art.iter("AbstractText"))
            rows.append({
                "doc_id": f"pm-{pmid}",
                "topic": topic,
                "title": "".join(art.find(".//ArticleTitle").itertext()),
                "journal": art.findtext(".//Journal/Title") or "",
                "year": art.findtext(".//PubDate/Year") or "",
                "text": abstract,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source": "PubMed (NCBI)",
            })
    write_csv("pubmed", rows, ["doc_id", "topic", "title", "journal", "year", "text", "url", "source"])


if __name__ == "__main__":
    main()
