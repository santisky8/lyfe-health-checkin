"""Daily amounts and safe upper limits for adults 19-50 (NIH Office of Dietary Supplements).

The ODS API blocks scripts, so this table is typed from the ODS health-professional fact
sheets. Each row links its fact sheet; check a value there before quoting it in the demo.
UL = tolerable upper intake level from all sources unless the note says otherwise.
"""
from common import write_csv

ODS = "https://ods.od.nih.gov/factsheets/{}-HealthProfessional/"

ROWS = [
    # nutrient, unit, rda_men, rda_women, ul, note, fact sheet
    ("Vitamin D", "mcg", 15, 15, 100, "15 mcg = 600 IU; UL 100 mcg = 4,000 IU", "VitaminD"),
    ("Calcium", "mg", 1000, 1000, 2500, "UL 2,000 mg from age 51", "Calcium"),
    ("Iron", "mg", 8, 18, 45, "Women 19-50 need more because of periods", "Iron"),
    ("Magnesium", "mg", 400, 310, 350, "UL applies to supplements and medicines only, not food; RDA rises to 420/320 from age 31", "Magnesium"),
    ("Vitamin B12", "mcg", 2.4, 2.4, None, "No UL set", "VitaminB12"),
    ("Vitamin C", "mg", 90, 75, 2000, "Smokers need 35 mg more", "VitaminC"),
    ("Zinc", "mg", 11, 8, 40, "", "Zinc"),
    ("Iodine", "mcg", 150, 150, 1100, "Pregnancy 220, breastfeeding 290", "Iodine"),
    ("Folate", "mcg DFE", 400, 400, 1000, "UL applies to folic acid from supplements and fortified food", "Folate"),
    ("Vitamin A", "mcg RAE", 900, 700, 3000, "UL applies to preformed vitamin A (retinol)", "VitaminA"),
    ("Potassium", "mg", 3400, 2600, None, "Adequate Intake, not RDA; no UL set", "Potassium"),
]


def main():
    rows = [{
        "nutrient": n, "unit": u, "rda_men": m, "rda_women": w,
        "upper_limit": "" if ul is None else ul, "note": note,
        "url": ODS.format(sheet), "source": "NIH Office of Dietary Supplements (US)",
    } for n, u, m, w, ul, note, sheet in ROWS]
    write_csv("nutrient_limits", rows, list(rows[0]))


if __name__ == "__main__":
    main()
