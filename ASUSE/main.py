import argparse

from src.multiyear_pipeline import run_multiyear


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASUSE multi-round state/district client pipeline")
    parser.add_argument("--years", nargs="+", default=["2022-2023", "2023-2024"])
    args = parser.parse_args()
    run_multiyear(survey_rounds=args.years)
