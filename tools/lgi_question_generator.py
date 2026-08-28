"""
LGI Research Question Generator for Tongyi DeepResearch
========================================================
Generates JSONL evaluation files from a (countries × indicators) matrix.

Usage:
    python lgi_question_generator.py                    # Individual mode (400 questions)
    python lgi_question_generator.py --mode mega        # Mega mode (40 country-level questions)
    python lgi_question_generator.py --mode both        # Generate both files

Configuration:
    Edit the CONFIG section below each month before running.
"""

import json
import argparse
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIG — Edit this section each month
# =============================================================================

# Research window
DATE_START = "1 April 2026"
DATE_END = "24 May 2026"

# The "as of today" date used in the exclusion clause
AS_OF_DATE = "24 May 2026"

# Target month
TARGET_MONTH = "May 2026"

# Comparison month
COMPARISON_MONTH = "April 2026"

# Countries to analyse
COUNTRIES = [
    # Asia-Pacific & Middle East
    "China",
    "Japan",
    "India",
    "South Korea",
    "Australia",
    "Indonesia",
    "Turkey",
    "Saudi Arabia",
    "Taiwan",
    "Thailand",
    "United Arab Emirates",
    "Philippines",
    "Singapore",
    "Malaysia",
    "Hong Kong SAR",
    "Vietnam",
    # Europe
    "Germany",
    "United Kingdom",
    "France",
    "Italy",
    "Russia",
    "Spain",
    "Netherlands",
    "Switzerland",
    "Poland",
    "Sweden",
    "Belgium",
    "Austria",
    "Israel",
    "Norway",
    "Ireland",
    "Denmark",
    # Americas
    "United States",
    "Brazil",
    "Canada",
    "Mexico",
    "Argentina",
    # Africa
    "Nigeria",
    "Egypt",
    "South Africa",
]

# LGI indicators and their phrasing
# Format: (indicator_name, verb_phrase)
# verb_phrase handles grammar: "are likely" vs "is likely"
INDICATORS = [
    ("Business Volume",     "are likely to be"),
    ("Business Sentiment",  "are likely to be"),
    ("Transportation",      "is likely to be"),
    ("Transport Capacity",  "is likely to be"),
    ("Employment",          "is likely to be"),
    ("Logistics Costs",     "are likely to be"),
    ("Warehousing",         "is likely to be"),
    ("Warehouse Capacity",  "is likely to be"),
    ("Inventory",           "is likely to be"),
    ("Goods for Sale",      "are likely to be"),
]

# Excluded sources
EXCLUDED_SOURCES = "RTTNews.com or similar"

# Output directory (relative to script location)
OUTPUT_DIR = Path("eval_data")


# =============================================================================
# TEMPLATE — Individual question (one per indicator per country)
# =============================================================================

INDIVIDUAL_TEMPLATE = (
    "Research and analyse credible company news, reputable media reports, "
    "official economic data, and trade statistics published within "
    "{date_start} to {date_end} to determine whether the {indicator} of "
    "{country} logistics service providers (Global and multinational) for "
    "{target_month} {verb_phrase} Higher, No Change, or Lower compared to "
    "{comparison_month}. All findings must be supported with documented and "
    "verifiable sources (URLs), including publication details, to justify "
    "the analysis. The purpose of this research is to provide an informed "
    "basis for pre-determining the {target_month} Logistics Growth Index "
    "(LGI) for {country}. Note that as of today ({as_of_date}), no official "
    "{target_month} {country} LGI results have been released; therefore, any "
    "claims or data purporting to represent these figures must be strictly "
    "excluded. Additionally, non-credible or low-reliability sources (e.g., "
    "{excluded_sources}) are not permitted."
)


# =============================================================================
# TEMPLATE — Mega question (all indicators for one country in a single query)
# =============================================================================

MEGA_TEMPLATE = (
    "Research and analyse credible company news, reputable media reports, "
    "official economic data, and trade statistics published within "
    "{date_start} to {date_end} to assess the {target_month} outlook for "
    "{country}'s logistics sector (Global and multinational service providers) "
    "compared to {comparison_month}.\n\n"
    "For EACH of the following 10 Logistics Growth Index (LGI) indicators, "
    "determine whether the indicator is likely to be Higher, No Change, or "
    "Lower compared to {comparison_month}. Provide your assessment with "
    "supporting evidence and source URLs for each:\n\n"
    "{indicator_list}\n\n"
    "Requirements:\n"
    "- All findings must be supported with documented and verifiable sources "
    "(URLs), including publication details.\n"
    "- The purpose is to provide an informed basis for pre-determining the "
    "{target_month} LGI for {country}.\n"
    "- As of today ({as_of_date}), no official {target_month} {country} LGI "
    "results have been released; any claims or data purporting to represent "
    "these figures must be strictly excluded.\n"
    "- Non-credible or low-reliability sources (e.g., {excluded_sources}) "
    "are not permitted.\n\n"
    "Format your response with a clear verdict (Higher / No Change / Lower) "
    "for each indicator, followed by the supporting evidence and source URLs."
)


# =============================================================================
# GENERATOR FUNCTIONS
# =============================================================================

def generate_individual_questions() -> list[dict]:
    """Generate one question per (country, indicator) pair."""
    questions = []
    for country in COUNTRIES:
        for indicator, verb_phrase in INDICATORS:
            question_text = INDIVIDUAL_TEMPLATE.format(
                date_start=DATE_START,
                date_end=DATE_END,
                indicator=indicator,
                country=country,
                target_month=TARGET_MONTH,
                verb_phrase=verb_phrase,
                comparison_month=COMPARISON_MONTH,
                as_of_date=AS_OF_DATE,
                excluded_sources=EXCLUDED_SOURCES,
            )
            questions.append({"question": question_text, "answer": ""})
    return questions


def generate_mega_questions() -> list[dict]:
    """Generate one question per country covering all 10 indicators."""
    questions = []
    for country in COUNTRIES:
        # Build numbered indicator list
        indicator_lines = []
        for i, (indicator, _) in enumerate(INDICATORS, 1):
            indicator_lines.append(f"{i}. {indicator}")
        indicator_list = "\n".join(indicator_lines)

        question_text = MEGA_TEMPLATE.format(
            date_start=DATE_START,
            date_end=DATE_END,
            country=country,
            target_month=TARGET_MONTH,
            comparison_month=COMPARISON_MONTH,
            indicator_list=indicator_list,
            as_of_date=AS_OF_DATE,
            excluded_sources=EXCLUDED_SOURCES,
        )
        questions.append({"question": question_text, "answer": ""})
    return questions


def write_jsonl(questions: list[dict], filepath: Path):
    """Write questions to JSONL file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"  ✓ {len(questions)} questions → {filepath}")


def generate_summary(questions: list[dict], mode: str):
    """Print a summary of what was generated."""
    print(f"\n{'='*60}")
    print(f"  LGI Question Generator — {mode.upper()} mode")
    print(f"{'='*60}")
    print(f"  Target:      {TARGET_MONTH} vs {COMPARISON_MONTH}")
    print(f"  Window:      {DATE_START} to {DATE_END}")
    print(f"  Countries:   {len(COUNTRIES)}")
    print(f"  Indicators:  {len(INDICATORS)}")
    print(f"  Questions:   {len(questions)}")
    print(f"{'='*60}\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate LGI research questions for Tongyi DeepResearch"
    )
    parser.add_argument(
        "--mode",
        choices=["individual", "mega", "both"],
        default="individual",
        help="individual = 1 question per indicator × country, "
             "mega = 1 question per country (all indicators), "
             "both = generate both files"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})"
    )
    args = parser.parse_args()

    # Generate a filename-friendly date stamp
    stamp = TARGET_MONTH.replace(" ", "_").lower()

    if args.mode in ("individual", "both"):
        questions = generate_individual_questions()
        generate_summary(questions, "individual")
        write_jsonl(questions, args.output_dir / f"lgi_{stamp}_individual.jsonl")

    if args.mode in ("mega", "both"):
        questions = generate_mega_questions()
        generate_summary(questions, "mega")
        write_jsonl(questions, args.output_dir / f"lgi_{stamp}_mega.jsonl")

    print("\nDone. Copy the JSONL file to your DeepResearch eval_data/ folder.")
    print("Then update DATASET in your .env or run_react_infer.sh accordingly.\n")


if __name__ == "__main__":
    main()