#!/bin/sh
# Pull every source into data/clean, then build the local SQLite stand-in.
set -e
cd "$(dirname "$0")"
for s in fitbit nutrient_limits myhealthfinder medlineplus medlineplus_all pubmed nccih; do
  python3 loaders/$s.py
done
python3 agent/store.py
