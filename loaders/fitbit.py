"""User habit log: real Fitbit data from 30 people (Furberg et al., Zenodo 53894, CC BY 4.0).

Joins daily activity and sleep into one row per person per day.
"""
import csv
from datetime import datetime

from common import RAW, write_csv


def day(text):
    return datetime.strptime(text.split(" ")[0], "%m/%d/%Y").date().isoformat()


def main():
    sleep = {}
    with (RAW / "sleepDay_merged.csv").open() as f:
        for r in csv.DictReader(f):
            sleep[(r["Id"], day(r["SleepDay"]))] = r
    rows = []
    with (RAW / "dailyActivity_merged.csv").open() as f:
        for r in csv.DictReader(f):
            key = (r["Id"], day(r["ActivityDate"]))
            s = sleep.get(key, {})
            rows.append({
                "user_id": r["Id"],
                "day": key[1],
                "steps": r["TotalSteps"],
                "active_minutes": int(r["VeryActiveMinutes"]) + int(r["FairlyActiveMinutes"]),
                "light_minutes": r["LightlyActiveMinutes"],
                "sedentary_minutes": r["SedentaryMinutes"],
                "calories": r["Calories"],
                "minutes_asleep": s.get("TotalMinutesAsleep", ""),
                "minutes_in_bed": s.get("TotalTimeInBed", ""),
            })
    write_csv("user_log", rows, list(rows[0]))


if __name__ == "__main__":
    main()
