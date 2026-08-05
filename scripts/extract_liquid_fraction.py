#!/usr/bin/env python3
"""
extract_liquid_fraction.py — Extract electrolyte liquid fraction over time
from Phase 2d VTK output.

The liquid fraction is the standard operational metric in thermal battery
literature (see Jeong 2019). A cell is considered "molten" when its
temperature exceeds the electrolyte melt point (716.15 K for LiF-LiBr-LiCl).

Three fractions are computed per timestep:
  - frac_count:  n_molten / n_total (cell-count fraction)
  - frac_volume: vol_molten / vol_total (mass-weighted, more physical)
  - axial_distribution: molten fraction split into N axial bands

The volume-weighted fraction is more physically meaningful because the
axisymmetric wedge mesh has cells with different volumes (radial cells
at larger r have more volume).

Usage:
    python3 scripts/extract_liquid_fraction.py \\
        --cases-root runs/phase2 \\
        --cases phase2d_ceramic_lifecycle phase2d_aerogel_lifecycle \\
        --output reports/current/phase2d_liquid_fraction.csv \\
        --axial-output reports/current/phase2d_axial_distribution.csv \\
        --n-axial-bands 10
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np

try:
    import pyvista as pv
except ImportError:
    sys.exit("ERROR: pyvista not installed. Activate .venv first:\n"
             "  source .venv/bin/activate")


T_MELT = 716.15           # K, electrolyte melt point (Jeong 2019)
MELT_WINDOW_K = 10.0      # K, full melt band (matches materials.electrolyte.phase_change.window_K)
# Melt band [T_MELT - MELT_WINDOW_K/2, T_MELT + MELT_WINDOW_K/2] = [711.15, 721.15] K

def compute_alpha(T):
    """Per-cell enthalpy-equivalent liquid fraction.

    alpha(T) ramps 0 -> 1 linearly across the melt window
    [T_MELT - w/2, T_MELT + w/2]; clamped to [0, 1] outside.
    This is the Jeong-equivalent per-cell liquid fraction used in his
    Fluent enthalpy formulation; with it we can also report Jeong's
    activation criterion (lowest electrolyte alpha > 0.99).

    Note: this is a LINEAR ramp, not the true thermodynamic enthalpy
    profile through the mushy zone. It's a defensible operational
    proxy for the cells we have (alpha goes 0->1 as T crosses the band),
    and it lets us report the SAME comparison Jeong does without altering
    the underlying simulation (the solver still uses its own phase-change
    enthalpy treatment internally — alpha here is a *diagnostic* on T).
    """
    half = MELT_WINDOW_K / 2.0
    return np.clip((T - (T_MELT - half)) / MELT_WINDOW_K, 0.0, 1.0)


def get_T_and_volumes(mb):
    """Extract per-cell T and cell volumes from a multiblock dataset."""
    if mb.n_blocks == 0:
        return None, None, None
    interior = mb[0]
    
    # Temperature: prefer cell data (we want per-cell, not per-point)
    if 'T' in interior.cell_data:
        T = np.asarray(interior.cell_data['T'])
        cell_centers = interior.cell_centers().points
    elif 'T' in interior.point_data:
        # Convert point data to cell data
        cell_data_grid = interior.point_data_to_cell_data()
        T = np.asarray(cell_data_grid['T'])
        cell_centers = interior.cell_centers().points
    else:
        return None, None, None
    
    # Cell volumes: use compute_cell_sizes
    sized = interior.compute_cell_sizes(length=False, area=False, volume=True)
    volumes = np.asarray(sized.cell_data['Volume'])
    
    return T, volumes, cell_centers


def get_time(vtm_path, mb):
    """Extract simulation time from VTM."""
    if mb.n_blocks > 0:
        interior = mb[0]
        if 'TimeValue' in interior.field_data:
            tv = interior.field_data['TimeValue']
            if len(tv) > 0:
                return float(tv[0])
    # Fallback: companion uniform/time file
    time_file = vtm_path.parent / vtm_path.stem / 'uniform' / 'time'
    if time_file.exists():
        m = re.search(r'value\s+([0-9.eE+-]+)', time_file.read_text())
        if m:
            return float(m.group(1))
    return None


def compute_axial_distribution(T, volumes, cell_centers, n_bands):
    """Split cells into N axial bands, compute liquid fraction per band.

    Returns dict: band_index -> dict of (z_center, frac_count, frac_volume, n_molten, n_total).

    The wedge mesh uses X as the axial direction (Y = radial, Z = wedge-thickness ≈ 0).
    We autodetect the widest-spanning axis so this works regardless of orientation. The output
    key is kept as `z_center_mm` for backward compat with downstream plotters — it holds the
    axial-position band center regardless of which physical axis that maps to.
    """
    cc = np.asarray(cell_centers)   # pyvista/vtk points wrapper doesn't have .ptp
    axial_idx = int(np.argmax(cc.max(axis=0) - cc.min(axis=0)))
    z = cc[:, axial_idx]
    z_min, z_max = z.min(), z.max()
    z_edges = np.linspace(z_min, z_max, n_bands + 1)
    
    molten_mask = T > T_MELT
    
    bands = {}
    for i in range(n_bands):
        in_band = (z >= z_edges[i]) & (z < z_edges[i + 1] + 1e-9)
        if in_band.sum() == 0:
            continue
        
        n_total = int(in_band.sum())
        n_molten = int((in_band & molten_mask).sum())
        v_total = float(volumes[in_band].sum())
        v_molten = float(volumes[in_band & molten_mask].sum())
        
        bands[i] = {
            'z_center_mm': float((z_edges[i] + z_edges[i + 1]) / 2 * 1000),
            'n_molten': n_molten,
            'n_total': n_total,
            'v_molten': v_molten,
            'v_total': v_total,
            'frac_count': n_molten / n_total if n_total else 0,
            'frac_volume': v_molten / v_total if v_total else 0,
        }
    
    return bands


def process_case(case_dir, n_axial_bands):
    """Process one case. Returns (overall_rows, axial_rows)."""
    case_label = case_dir.name
    print(f"\n[{case_label}]")
    
    vtk_dir = case_dir / 'VTK' / 'electrolyte'
    if not vtk_dir.is_dir():
        print(f"  ! no VTK/electrolyte directory — run foamToVTK -region electrolyte first")
        return [], []
    
    vtm_files = sorted(
        vtk_dir.glob('*.vtm'),
        key=lambda p: int(p.stem.split('_')[-1]) if '_' in p.stem else 0
    )
    
    if not vtm_files:
        print(f"  ! no .vtm files found in {vtk_dir}")
        return [], []
    
    print(f"  Found {len(vtm_files)} VTM files")
    
    overall_rows = []
    axial_rows = []
    
    for i, vtm in enumerate(vtm_files):
        try:
            mb = pv.read(str(vtm))
        except Exception as e:
            print(f"  ! {vtm.name}: read failed: {e}")
            continue
        
        T, volumes, cell_centers = get_T_and_volumes(mb)
        if T is None or volumes is None:
            continue
        
        t = get_time(vtm, mb)
        if t is None:
            continue
        
        # Overall liquid fraction — BINARY metric (T > T_MELT)
        molten_mask = T > T_MELT
        n_total = len(T)
        n_molten = int(molten_mask.sum())
        v_total = float(volumes.sum())
        v_molten = float(volumes[molten_mask].sum())

        # Overall liquid fraction — JEONG-EQUIVALENT alpha metric.
        # alpha is a per-cell linear-ramp liquid fraction (0 below the melt
        # band, 1 above, ramping linearly across [T_MELT - w/2, T_MELT + w/2]).
        # The three quantities reported below are all over ALL electrolyte
        # cells of this timestep:
        #   alpha_lowest       — Jeong's strict criterion (>0.99 = activated).
        #                        Always near 0 in practice — there is always
        #                        an edge cell at ambient. This is correct &
        #                        intentional; Jeong's criterion is strict.
        #   alpha_mean_volw    — volume-weighted mean of alpha. Should be
        #                        in the same ballpark as frac_volume (binary)
        #                        but slightly higher because partial-melt
        #                        cells count fractionally instead of as 0.
        #   alpha_p05          — 5th-percentile alpha; a SOFTER diagnostic
        #                        showing how cold the coldest ~5% of cells
        #                        is. NOT a Jeong-equivalent metric — never
        #                        confuse with alpha_lowest.
        alpha = compute_alpha(T)
        alpha_lowest = float(alpha.min())
        alpha_mean_volw = float((alpha * volumes).sum() / v_total) if v_total else 0.0
        alpha_p05 = float(np.percentile(alpha, 5))

        overall_rows.append({
            'case': case_label,
            'time_s': t,
            # Existing binary metric (unchanged)
            'n_molten': n_molten,
            'n_total': n_total,
            'v_molten_m3': v_molten,
            'v_total_m3': v_total,
            'frac_count': n_molten / n_total if n_total else 0,
            'frac_volume': v_molten / v_total if v_total else 0,
            'T_min': float(T.min()),
            'T_max': float(T.max()),
            'T_mean': float(T.mean()),
            # NEW: Jeong-equivalent alpha metric
            'alpha_lowest': alpha_lowest,             # Jeong activation criterion (>0.99)
            'alpha_mean_volw': alpha_mean_volw,       # volume-weighted mean alpha
            'alpha_p05': alpha_p05,                   # softer diagnostic (5th percentile)
        })
        
        # Axial distribution
        bands = compute_axial_distribution(T, volumes, cell_centers, n_axial_bands)
        for band_idx, band_data in bands.items():
            axial_rows.append({
                'case': case_label,
                'time_s': t,
                'band_idx': band_idx,
                'z_center_mm': band_data['z_center_mm'],
                'n_molten': band_data['n_molten'],
                'n_total': band_data['n_total'],
                'frac_count': band_data['frac_count'],
                'frac_volume': band_data['frac_volume'],
            })
        
        # Progress
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(vtm_files)} done — last: t={t:.1f}s, frac_volume={v_molten/v_total*100:.2f}%")
    
    overall_rows.sort(key=lambda r: r['time_s'])
    print(f"  Extracted {len(overall_rows)} timesteps")
    
    if overall_rows:
        # Headline summary
        first = overall_rows[0]
        last = overall_rows[-1]
        peak = max(overall_rows, key=lambda r: r['frac_volume'])
        print(f"  t={first['time_s']:>7.1f}s: frac_volume = {first['frac_volume']*100:>6.2f}% molten")
        print(f"  t={peak['time_s']:>7.1f}s: frac_volume = {peak['frac_volume']*100:>6.2f}% (PEAK)")
        print(f"  t={last['time_s']:>7.1f}s: frac_volume = {last['frac_volume']*100:>6.2f}% molten (END)")
    
    return overall_rows, axial_rows


def main():
    parser = argparse.ArgumentParser(description='Extract electrolyte liquid fraction')
    parser.add_argument('--cases-root', default='runs/phase2')
    parser.add_argument('--cases', nargs='+',
                        default=['phase2d_ceramic_lifecycle', 'phase2d_aerogel_lifecycle'])
    parser.add_argument('--output', default='reports/current/phase2d_liquid_fraction.csv')
    parser.add_argument('--axial-output', default='reports/current/phase2d_axial_distribution.csv')
    parser.add_argument('--n-axial-bands', type=int, default=10)
    args = parser.parse_args()
    
    cases_root = Path(args.cases_root)
    if not cases_root.is_dir():
        sys.exit(f"ERROR: {cases_root} not found")
    
    all_overall = []
    all_axial = []
    
    for case_name in args.cases:
        case_dir = cases_root / case_name
        if not case_dir.is_dir():
            print(f"WARNING: case dir not found: {case_dir}")
            continue
        overall, axial = process_case(case_dir, args.n_axial_bands)
        all_overall.extend(overall)
        all_axial.extend(axial)
    
    if not all_overall:
        sys.exit("ERROR: no data extracted")
    
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(all_overall[0].keys()))
        writer.writeheader()
        writer.writerows(all_overall)
    print(f"\nWrote {len(all_overall)} overall rows to {output}")
    
    axial_output = Path(args.axial_output)
    with open(axial_output, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(all_axial[0].keys()))
        writer.writeheader()
        writer.writerows(all_axial)
    print(f"Wrote {len(all_axial)} axial-band rows to {axial_output}")
    
    # Quick comparison summary
    print()
    print("=" * 70)
    print("LIQUID FRACTION SUMMARY")
    print("=" * 70)
    print(f"{'Case':<35} {'Peak frac':>10} {'End frac':>10} {'End molten %':>14}")
    print("-" * 70)
    by_case = {}
    for r in all_overall:
        by_case.setdefault(r['case'], []).append(r)
    
    for case, rows in by_case.items():
        peak = max(rows, key=lambda r: r['frac_volume'])
        end = rows[-1]
        print(f"{case:<35} {peak['frac_volume']*100:>9.2f}% "
              f"{end['frac_volume']*100:>9.2f}% "
              f"{end['n_molten']:>5d}/{end['n_total']}")
    
    # Differentiation
    cases = list(by_case.keys())
    if len(cases) == 2:
        end_fracs = [by_case[c][-1]['frac_volume'] for c in cases]
        diff_pct = (end_fracs[1] - end_fracs[0]) * 100
        print()
        print(f"Steady-state liquid fraction differentiation:")
        print(f"  {cases[1]} vs {cases[0]}: {diff_pct:+.3f} percentage points")
        print(f"  ({end_fracs[1]/end_fracs[0]:.3f}x ratio)")


if __name__ == '__main__':
    main()
