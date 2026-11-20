from __future__ import annotations
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"src"))
from hces_pipeline.runner import run_year

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--survey",required=True,choices=["2011-12","2022-23","2023-24","all"]); ap.add_argument("--validate-only",action="store_true"); args=ap.parse_args()
    years=["2011-12","2022-23","2023-24"] if args.survey=="all" else [args.survey]
    for y in years:
        print(f"\n=== HCES {y} ==="); run_year(ROOT,y,args.validate_only); print("DONE")
if __name__=="__main__": main()
