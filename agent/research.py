"""Live research: PubMed reviews for the topics a question matched (NCBI E-utilities, no key).

Searched at question time so the evidence is current. Only titles, journals, years, short
abstract excerpts and links are kept; the full abstracts stay on PubMed.
"""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UA = {"User-Agent": "lyfe-health-checkin/0.1 (Open Agent Hackathon 2026)"}


def _get(path, params):
    url = f"{EUTILS}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8")


def reviews(terms, top_n=3, context=None):
    """Recent systematic reviews and meta-analyses on any of the terms, most relevant first.
    With `context` (a condition), only papers that also mention it in the title or abstract."""
    terms = [t for t in dict.fromkeys(terms) if t][:3]
    if not terms:
        return []
    topic = " OR ".join(f'"{t}"[ti]' for t in terms)
    if context:
        topic = f'({topic}) AND "{context}"[tiab]'
    # Strongest evidence first; widen only when a rare topic has no systematic review.
    ids = []
    for kind in ("(systematic review[pt] OR meta-analysis[pt])", "review[pt]", ""):
        query = (f"({topic}) {'AND ' + kind if kind else ''} AND humans[mh] AND english[la] "
                 f"AND 2005:3000[dp] NOT retracted publication[pt] NOT withdrawn[ti]")
        ids = json.loads(_get("esearch.fcgi", {"db": "pubmed", "term": query, "retmax": top_n,
                                               "sort": "relevance", "retmode": "json"})
                         )["esearchresult"]["idlist"]
        if ids:
            break
        time.sleep(0.35)
    if not ids:
        return []
    time.sleep(0.35)  # stay under 3 requests a second without a key
    root = ET.fromstring(_get("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids),
                                              "retmode": "xml"}))
    out = []
    for art in root.iter("PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = "".join(art.find(".//ArticleTitle").itertext()).strip()
        if title.upper().startswith(("WITHDRAWN", "RETRACTED")):
            continue
        parts = []
        for a in art.iter("AbstractText"):
            label = a.get("Label")
            if label and label.upper() in ("RESULTS", "CONCLUSIONS", "CONCLUSION",
                                           "MAIN RESULTS", "AUTHORS' CONCLUSIONS"):
                parts.append(f"{label.title()}: " + "".join(a.itertext()))
        if not parts:  # unstructured abstract: keep the end, where the findings usually are
            parts = ["".join(a.itertext()) for a in art.iter("AbstractText")][-1:]
        out.append({
            "title": title,
            "text": " ".join(parts)[:900],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source": f"PubMed: {art.findtext('.//Journal/ISOAbbreviation') or art.findtext('.//Journal/Title')}, "
                      f"{art.findtext('.//PubDate/Year') or art.findtext('.//PubDate/MedlineDate', '')[:4]}",
        })
    return out


if __name__ == "__main__":
    import sys
    for r in reviews(sys.argv[1:]):
        print(r["source"], "|", r["title"][:90])
