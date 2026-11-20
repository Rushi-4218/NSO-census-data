import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import pandas as pd
from hces_pipeline.estimation import aggregate_all
from hces_pipeline.utils import weighted_mean,weighted_gini

def test_weighted_mean():
    assert weighted_mean(pd.Series([1,3]),pd.Series([1,1]))==2

def test_gini_equal():
    assert abs(weighted_gini([5,5,5],[1,2,3]))<1e-12

def test_component_shares_use_a_common_complete_universe():
    hh=pd.DataFrame({
        "HH_KEY":["a","b"], "State":["01","01"], "District_ID":["0101","0101"],
        "Sector_Name":["rural","rural"], "FINAL_WEIGHT":[1.0,1.0], "PERSON_WEIGHT":[1.0,1.0],
        "MPCE_TOTAL":[100.0,1000.0], "MPCE_FOOD":[40.0,float("nan")],
        "MPCE_NONFOOD":[60.0,float("nan")], "MPCE_CEREAL":[10.0,20.0],
    })
    all_india=aggregate_all(hh).query("geo_level == 'All India' and Sector_Name == 'total'").iloc[0]
    assert all_india.avg_mpce_total == 550.0
    assert all_india.share_food == 40.0
    assert all_india.share_nonfood == 60.0
