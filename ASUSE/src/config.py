from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


CLIENT_COLUMNS = [
    "Survey_ID", "Survey_NAME", "Survey_GROUP_ID", "GROUP_NAME",
    "SUB_GROUP_ID", "SUB_GROUP_NAME", "Year", "FREQ_DESC", "State_ID",
    "State_Name", "District_ID", "District_Name", "Sector_code", "Sector",
    "Published_date", "Extracted_Date", "Col_ID", "COL_DESC",
    "DATA", "Unit", "Source",
]

SUBGROUPS = {
    1: ("No. of Unincorporated Establishments (UE)", ["Total", "Manufacturing", "Trade", "Other Services"], "Number"),
    2: ("Ownership Pattern of UE", ["Proprietary", "Partnership", "SHG", "Others", "Total"], "Number"),
    3: ("No. of Workers Employed in UE", ["Total", "Manufacturing", "Trade", "Other Services"], "Number"),
    4: ("Annual Emoluments per Hired Worker in UE", ["Total", "Manufacturing", "Trade", "Other Services"], "Rupees per hired worker per year"),
    5: ("Average Value of Fixed Assets Owned by a UE", ["Total", "Manufacturing", "Trade", "Other Services"], "Rupees per UE"),
    6: ("Outstanding Loan per UE", ["Total", "Manufacturing", "Trade", "Other Services"], "Rupees per UE"),
    7: ("Share of Sectors in GVA as Percentage of Total GVA of UE", ["Total", "Manufacturing", "Trade", "Other Services"], "Percent"),
    8: ("Percentage of UE by Status of Registration", [
        "Total - Unregistered", "Total - Registered",
        "Manufacturing - Unregistered", "Manufacturing - Registered",
        "Trade - Unregistered", "Trade - Registered",
        "Other Services - Unregistered", "Other Services - Registered",
    ], "Percent"),
}


@dataclass(frozen=True)
class PipelineConfig:
    root: Path
    survey_year: int = 2025
    survey_id: int = 8
    survey_name: str = "ASUSE"
    group_id: int = 1
    group_name: str = "Annual Survey of Unincorporated Sector Enterprises"
    published_date: str = "06-May-26"
    extracted_date: str = "05-Aug-26"
    source_url: str = "https://microdata.gov.in/NADA/index.php/catalog/293"
    # Four independently rounded ownership components can differ from their
    # independently rounded total by two units.
    tolerance: float = 2.0

    @property
    def input_dir(self) -> Path:
        for name in ("INPUT", "Input", "input"):
            p = self.root / name
            if p.is_dir():
                return p
        return self.root / "INPUT"

    @property
    def run_date(self) -> str:
        return date.today().strftime("%d-%b-%y")
