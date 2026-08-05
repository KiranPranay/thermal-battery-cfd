#!/usr/bin/env python3
"""
extract_phase2_timeseries.py — Extract T(t) per region for Phase 2 cases.

Reads VTM files (via foamToVTK output) and produces a CSV with columns:
    case, region, time_s, T_min, T_mean, T_max, n_cells

Run after Phase 2 verification (which already created VTK/ subdirs).

Usage:
    python3 scripts/extract_phase2_timeseries.py \\
        --cases-root runs/phase2 \\
        --output reports/current/phase2_timeseries.csv
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
    sys.exit("ERROR: pyvista not installed. Run from .venv:\n"
             "  source .venv/bin/activate")


REGIONS = ('heatPellet', 'cathode', 'electrolyte', 'anode', 'collector',
           'insulation_A', 'insulation_B', 'case_ss')


def _get_T(mb):
    """Extract T array from a multiblock dataset."""
    if mb.n_blocks == 0:
        return None
    interior = mb[0]
    if 'T' in interior.cell_data:
        return np.asarray(interior.cell_data['T'])
    if 'T' in interior.point_data:
        return np.asarray(interior.point_data['T'])
    return None


def _get_time(vtm_path, mb):
    """Extract simulation time from VTM file or its companion time file."""
    if mb.n_blocks > 0:
        interior = mb[0]
        if 'TimeValue' in interior.field_data:
            tv = interior.field_data['TimeValue']
            if len(tv) > 0:
                return float(tv[0])
    
    # Fall back to companion time file
    time_file = vtm_path.parent / vtm_path.stem / 'uniform' / 'time'
    if time_file.exists():
        m = re.search(r'value\s+([0-9.eE+-]+)', time_file.read_text())
        if m:
            return float(m.group(1))
    
    # Last resort: parse the index from the filename
    # foamToVTK uses suffixes like region_0.vtm, region_1.vtm, ...
    return None


def extract_region_series(case_dir, region):
    """Read all VTM files for a region, return list of (t, T_min, T_mean, T_max, n_cells)."""
    vtk_dir = case_dir / 'VTK' / region
    if not vtk_dir.is_dir():
        return []
    
    entries = []
    vtm_files = sorted(
        vtk_dir.glob('*.vtm'),
        key=lambda p: int(p.stem.split('_')[-1]) if '_' in p.stem else 0
    )
    
    for vtm in vtm_files:
        try:
            mb = pv.read(str(vtm))
        except Exception as e:
            print(f"  WARNING: skipping {vtm.name}: {e}", file=sys.stderr)
            continue
        
        T = _get_T(mb)
        if T is None:
            continue
        
        t = _get_time(vtm, mb)
        if t is None:
            continue
        
        entries.append({
            'time_s': t,
            'T_min': float(np.min(T)),
            'T_mean': float(np.mean(T)),
            'T_max': float(np.max(T)),
            'n_cells': len(T),
        })
    
    entries.sort(key=lambda e: e['time_s'])
    return entries


def process_case(case_dir):
    """Return list of dict rows for all (case, region, time) combos."""
    case_label = case_dir.name
    print(f"\n[{case_label}]")
    
    rows = []
    for region in REGIONS:
        series = extract_region_series(case_dir, region)
        if not series:
            print(f"  ! no data for {region}", file=sys.stderr)
            continue
        
        for e in series:
            rows.append({
                'case': case_label,
                'region': region,
                'time_s': e['time_s'],
                'T_min': e['T_min'],
                'T_mean': e['T_mean'],
                'T_max': e['T_max'],
                'n_cells': e['n_cells'],
            })
        
        # Print summary for this region
        t0_T = series[0]['T_mean']
        tN_T = series[-1]['T_mean']
        peak_T = max(e['T_max'] for e in series)
        print(f"  {region:15s}: {len(series):3d} samples, "
              f"T_mean {t0_T:.1f}→{tN_T:.1f} K, T_max peak {peak_T:.1f} K")
    
    return rows


def main():
    parser = argparse.ArgumentParser(description='Extract Phase 2 time-series data')
    parser.add_argument('--cases-root', default='runs/phase2',
                        help='Directory containing case workdirs')
    parser.add_argument('--output', default='reports/current/phase2_timeseries.csv')
    args = parser.parse_args()
    
    cases_root = Path(args.cases_root)
    if not cases_root.is_dir():
        sys.exit(f"ERROR: {cases_root} not found")
    
    cases = sorted(d for d in cases_root.iterdir() if d.is_dir() and (d / 'VTK').exists())
    if not cases:
        sys.exit(f"ERROR: no cases with VTK/ subdir found in {cases_root}")
    
    print(f"Found {len(cases)} cases with VTK output")
    
    all_rows = []
    for c in cases:
        all_rows.extend(process_case(c))
    
    if not all_rows:
        sys.exit("ERROR: no data extracted from any case")
    
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    
    print(f"\nWrote {len(all_rows)} rows to {output}")


if __name__ == '__main__':
    main()
