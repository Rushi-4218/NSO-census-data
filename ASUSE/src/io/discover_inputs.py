from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile


@dataclass(frozen=True)
class Inputs:
    zip_file: Path
    ddi_file: Path
    template_file: Path
    layout_file: Path
    census_file: Path
    volume_i_file: Path


def _one(files: list[Path], label: str) -> Path:
    if len(files) != 1:
        raise RuntimeError(f"Expected exactly one {label}; found {len(files)}: {[p.name for p in files]}")
    return files[0]


def discover(input_dir: Path) -> Inputs:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    files = [p for p in input_dir.rglob("*") if p.is_file()]
    zip_file = _one([
        p for p in files if p.suffix.lower() == ".zip" and "2025" in p.name.lower() and "official_docs" not in p.name.lower()
    ], "2025 raw ASUSE ZIP")
    ddi_file = _one([
        p for p in files if p.suffix.lower() == ".xlsx" and "dictionary" in p.name.lower() and "2025" in p.name.lower()
    ], "2025 DDI workbook")
    template_file = _one([p for p in files if p.suffix.lower() == ".csv" and "maharashtra" in p.name.lower()], "Maharashtra template")
    layouts = [p for p in files if p.suffix.lower() == ".xlsx" and "layout" in p.name.lower() and "2025" in p.name.lower()]
    censuses = [p for p in files if p.name.lower() == "pc11_tv_dir.xlsx"]
    volume_i = [p for p in files if p.suffix.lower() == ".pdf" and "2025_vol_i." in p.name.lower()]
    if not layouts or not censuses or not volume_i:
        raise RuntimeError(
            "Official layout/geography resources are required. Place NSS_ASUSE_2025_Layout_mult_post.xlsx "
            ", ASUSE_2025_Vol_I.pdf, and PC11_TV_DIR.xlsx under INPUT/official_docs. They are available from the official ASUSE "
            "catalog and Census 2011 Location Code Directory."
        )
    return Inputs(zip_file, ddi_file, template_file, layouts[0], censuses[0], volume_i[0])


def extract_raw(zip_file: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    existing = list(destination.rglob("asuse_2025_esu_l*.*"))
    if len(existing) >= 16:
        return existing[0].parent
    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(destination)
    files = list(destination.rglob("asuse_2025_esu_l*.*"))
    if len(files) != 16:
        raise RuntimeError(f"Expected L01-L16 after extraction; found {len(files)}")
    return files[0].parent
