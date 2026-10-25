"""MyHealthfinder (US ODPHP): plain-language prevention advice. Public domain, no key."""
from common import TOPICS, get_json, strip_html, write_csv

API = "https://odphp.health.gov/myhealthfinder/api/v4/topicsearch.json"


def main():
    rows, seen = [], set()
    for topic in TOPICS:
        res = get_json(API, {"keyword": topic}).get("Result", {})
        for item in (res.get("Resources") or {}).get("Resource", []) or []:
            if item["Id"] in seen:
                continue
            seen.add(item["Id"])
            for i, sec in enumerate(item["Sections"]["section"]):
                rows.append({
                    "doc_id": f"mhf-{item['Id']}-{i}",
                    "topic": topic,
                    "title": item["Title"],
                    "section": sec.get("Title") or "",
                    "text": strip_html(sec.get("Content")),
                    "url": item["AccessibleVersion"],
                    "source": "MyHealthfinder (ODPHP, US)",
                    "updated": item.get("LastUpdate", ""),
                })
    write_csv("myhealthfinder", rows,
              ["doc_id", "topic", "title", "section", "text", "url", "source", "updated"])


if __name__ == "__main__":
    main()
