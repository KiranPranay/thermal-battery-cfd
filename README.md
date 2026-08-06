# Thermal-battery CFD: an OpenFOAM conjugate heat-transfer model of a 13-stack LiSi/FeS2 thermal battery

Reproducible OpenFOAM v2412 model of a 13-stack LiSi/FeS₂ thermal battery with LiF-LiCl-LiBr molten-salt electrolyte, plus the extension to five ambient temperatures {−40, −20, 0, +26.85, +50} °C. The reference cell geometry follows Jeong, Cho and Lee (2019, *J. Power Sources* **424**:35–41), doi:[10.1016/j.jpowsour.2019.03.067](https://doi.org/10.1016/j.jpowsour.2019.03.067). This repository is the code, data, and configuration artifact accompanying the manuscript *"Low-temperature activation limits of a thermal battery and the energy cost of a published uniformity remedy"* (P. Pranay Kiran, submitted to *Journal of Power Sources*).

## What is reproducible from this repository

The paper reports twelve run configurations. All twelve are derived from the single reference YAML `configs/jeong_case1_discharge.yaml` by parameter override (ambient temperature, discharge Case, optional rescue-source cellSet, `writeInterval`, `endTime`). The exact override for each of the twelve is tabulated in `configs/PARAMETER_MATRIX.md`. Given this repository plus an OpenFOAM v2412 installation, a user can reproduce:

- All five points of the operability envelope (§4 of the paper, Fig 4): `phase7a_t_neg40`, `_neg20`, `_0`, `_anchor_ctrl`, `_pos50`.
- All three points of the Case 3-1 discharge derating (§5, Fig 5): `phase7b_c31_t_neg20`, `_t_0`, `case_3_1`.
- Both rescue configurations (§6, Fig 7, Fig 8): `phase7c_rescue_depth_t_neg40` (discharge-OFF), `phase7c_depth_disch_t_neg40` (D2, discharge-ON).
- Both fine-cadence validation runs (§3.1, Fig 2): `case1_fine_cadence` (WI = 0.05 s), `case1_ultrafine` (WI = 0.005 s).

Not shipped as separate files: the Phase 6 six-case matrix (Cases 1/2/3/1-1/2-1/3-1 at +26.85 °C, cited in Table 1 for the Fig 5 comparison) — those runs differ from the reference only in the `discharge` field and are generated the same way. See `configs/PARAMETER_MATRIX.md` for the full recipe.

## What is in here

- **`configs/jeong_case1_discharge.yaml`** — reference YAML for the +26.85 °C anchor case; sha `887587fe...`. Every other run configuration is a parameter override on this file.
- **`configs/PARAMETER_MATRIX.md`** — the twelve-case parameter matrix and how to build any of them.
- **`scripts/`** — case-build pipeline (`build_case.py`), OpenFOAM dictionary generators (`generate_blockMeshDict.py`, `generate_controlDict.py`, `generate_fvOptions.py`, `generate_initial_fields.py`, `generate_solver_settings.py`), extraction scripts (`extract_liquid_fraction.py`, `extract_phase2_timeseries.py`), and the config loader.
- **`data/extractions/`** — the JSON extractions cited in the paper's figures and tables. Each file's provenance is in the header comment or the paper's Supplementary Information.
- **`figures/generate_all.py`** — figure-generation code for the eight paper figures. Reads only files from `figures/data/` and `data/extractions/`. No solver run required.
- **`LICENSE`** — Apache-2.0 (source code).
- **`LICENSE-DATA`** — CC-BY-4.0 (data files: `data/`, `figures/data/`).
- **`CITATION.cff`** — machine-readable citation metadata.

## Figure and table reproduction map

| Paper artifact | Data source (this repo) | Regenerates via |
|---|---|---|
| Fig 1 (Geometry) | `configs/jeong_case1_discharge.yaml` | `figures/generate_all.py::fig1_geometry` |
| Fig 2 (Cell-6 components) | `figures/data/phase8_v17_ultrafine.json`, `figures/data/phase8_v16_c6.json` | `figures/generate_all.py::fig2_cell6_components` |
| Fig 3 (Axial peak times) | `data/extractions/phase8_v14.json` | `figures/generate_all.py::fig3_axial_tpeak` |
| Fig 4 (Operability envelope) | `data/extractions/phase8_v17_R_invariance.json` + Phase 7A frozen values | `figures/generate_all.py::fig4_operability_envelope` |
| Fig 5 (Three-basis derating) | Phase 7B frozen table values | `figures/generate_all.py::fig5_derating` |
| Fig 6 (Rescue config) | schematic — derived from `configs/jeong_case1_discharge.yaml` | `figures/generate_all.py::fig6_rescue_config` |
| Fig 7 (Rescue T_min) | `data/extractions/F7_tmin_trajectories.json` | `figures/generate_all.py::fig7_rescue_tmin` |
| Fig 8 (Energy split) | Phase 7C DEPTH ledger values | `figures/generate_all.py::fig8_energy_split` |
| Table 1 (Fig 5 six-case) | `data/extractions/phase8_c9_c3.json`, `data/extractions/phase8_predraft.json` | manual assembly |
| Table 2 (Rescue trajectory) | `data/extractions/phase8_v17_ultrafine.json`, `data/extractions/phase8_d2.json` | manual assembly |
| Table 3 (Rescue energy split) | Phase 7C DEPTH per-region ledger | manual assembly |

To regenerate every figure:

```bash
cd figures
python3 generate_all.py
```

Requires: Python 3.10+, matplotlib, numpy.

## Regenerating raw solver output

The extractions in `data/` are what the paper cites; the underlying OpenFOAM VTK series is not archived because it regenerates deterministically from the case configurations. To reproduce a run:

```bash
source /path/to/openfoam2412/etc/bashrc
python3 scripts/build_case.py --config configs/jeong_case1_discharge.yaml --base-dir /tmp/case1
cd /tmp/case1
blockMesh && topoSet && splitMeshRegions -cellZonesOnly -overwrite
chtMultiRegionFoam | tee log.solver
```

The build script asserts a sha checksum on the electrolyte thermodynamics (`887587fe...`) before launch and enforces a `FoamFile` header check on all generated `fvOptions` dictionaries. See the header docstring in `scripts/build_case.py` for the standing pre-flight discipline (D1–D3).

## Citing this work

If you use this software please cite both the software artifact and the associated paper. Software citation (via Zenodo DOI, deposited at release):

```
Kiran, P. Pranay. (2026). Thermal-battery CFD: an OpenFOAM conjugate heat-transfer
model of a 13-stack LiSi/FeS2 thermal battery. Zenodo.
```

The DOI is not shown inline here because it is minted by Zenodo at each release; see `CITATION.cff` (`identifiers[0].value`) for the authoritative concept DOI, which is updated at every release and always resolves to the current version. The paper citation will be updated on acceptance.

## What is intentionally excluded

- **The Jeong 2019 PDF.** Redistribution of Elsevier-copyrighted content is not permitted; readers with institutional access should retrieve the paper from [doi:10.1016/j.jpowsour.2019.03.067](https://doi.org/10.1016/j.jpowsour.2019.03.067). The Table 1 numerical values used in this work are data (facts, not expression) and are quoted in the manuscript with attribution.
- **Raw VTK output.** Regenerable from `configs/` per instructions above; roughly 100 GB across the ambient sweep.
- **Any internal or institutional material.** This repository contains only the artifacts needed to reproduce the paper's results.
