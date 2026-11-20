# AIDIS

All India Debt and Investment Survey processing code for the 2003, 2013, and 2019 rounds.

Raw microdata, source archives, caches, and client deliverables stay on the local machine and must not be committed.

## Layout

| Path | Role |
|---|---|
| `build_aidis_delivery.py` | 77th round (2019) delivery builder |
| `filter_maharashtra.py` | Maharashtra extract from the 2019 delivery |
| `AIDIS_2003_All_India_Pipeline/` | 2003 source modules and locked methodology config |
| `AIDIS_2013_All_India_Pipeline/` | 2013 source modules, codebooks, and step locks |
| `AIDIS_2019_All_India_Pipeline/` | 2019 source modules and state/district masters |

Each year folder keeps runnable modules in `src/` and methodology locks in `config/`. Put that year's raw inputs in a local `input/` folder before running. Numbered scripts in `src/` run in filename order.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`build_aidis_delivery.py` expects the 77th-round workbooks and DDI under the input path set at the top of the script. The year pipelines read their own `config/` locks and local `input/` folders.
