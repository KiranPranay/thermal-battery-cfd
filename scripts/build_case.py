#!/usr/bin/env python3
"""
build_case.py — Top-level orchestrator for the thermal-battery-cfd pipeline.

Runs all v5 generator scripts in the right order to produce a complete
OpenFOAM case from a single YAML config.

Usage:
    python3 scripts/build_case.py --config configs/jeong2019.yaml [--base-dir .]

After running this, you still need to run:
    blockMesh
    topoSet
    splitMeshRegions -cellZonesOnly -overwrite
    chtMultiRegionFoam
"""

import sys
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from config_loader import load_config, validate_geometry, get_unique_regions


REGION_PROPERTIES_TEMPLATE = '''/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2412                                 |
|   \\\\  /    A nd           |                                                 |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "constant";
    object      regionProperties;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

regions
(
    fluid       ()
    solid       ({regions})
);

// ************************************************************************* //
'''

G_TEMPLATE = '''/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2412                                 |
|   \\\\  /    A nd           |                                                 |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       uniformDimensionedVectorField;
    location    "constant";
    object      g;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

dimensions      [0 1 -2 0 0 0 0];
value           ( -9.81 0 0 );

// ************************************************************************* //
'''

TOP_FVSCHEMES = '''/*--------------------------------*- C++ -*----------------------------------*\\
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      fvSchemes;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes      { default none; }
laplacianSchemes { default none; }
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }

// ************************************************************************* //
'''

TOP_FVSOLUTION = '''/*--------------------------------*- C++ -*----------------------------------*\\
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      fvSolution;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

PIMPLE
{
    nOuterCorrectors 1;
}

// ************************************************************************* //
'''


def write_regionProperties(config, base_dir):
    """Generate constant/regionProperties listing all 8 regions."""
    regions = get_unique_regions(config)
    
    path = base_dir / 'constant' / 'regionProperties'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        f.write(REGION_PROPERTIES_TEMPLATE.format(regions=' '.join(regions)))
    return path, regions


def write_g(base_dir):
    path = base_dir / 'constant' / 'g'
    with open(path, 'w') as f:
        f.write(G_TEMPLATE)
    return path


def write_top_level_solver(base_dir):
    path1 = base_dir / 'system' / 'fvSchemes'
    path1.parent.mkdir(parents=True, exist_ok=True)
    with open(path1, 'w') as f:
        f.write(TOP_FVSCHEMES)
    
    path2 = base_dir / 'system' / 'fvSolution'
    with open(path2, 'w') as f:
        f.write(TOP_FVSOLUTION)
    
    return [path1, path2]


def main():
    parser = argparse.ArgumentParser(description='Build OpenFOAM case from YAML config')
    parser.add_argument('--config', required=True, help='Path to YAML config file')
    parser.add_argument('--base-dir', default='.', help='Case directory (default: .)')
    args = parser.parse_args()
    
    config_path = Path(args.config)
    base_dir = Path(args.base_dir)
    
    print(f"==============================================================")
    print(f"  Building case from {config_path}")
    print(f"  Output directory:   {base_dir}")
    print(f"==============================================================")
    
    config = load_config(config_path)
    
    validate_geometry(config, verbose=True)
    print()
    
    print("--- Top-level files ---")
    p, regions = write_regionProperties(config, base_dir)
    print(f"Wrote {p}")
    print(f"  Regions ({len(regions)}): {' '.join(regions)}")
    p = write_g(base_dir)
    print(f"Wrote {p}")
    for p in write_top_level_solver(base_dir):
        print(f"Wrote {p}")
    print()
    
    import subprocess
    
    # v5 generators. The original "stays v4" claim was wrong — solver_settings,
    # controlDict, and blockMeshDict all needed v5 versions (per-region dirs,
    # per-region function objects, and material-prefix detection respectively).
    # Only fvOptions is genuinely v4-compatible: it writes only to 
    # constant/heatPellet/, which has the same name in v4 and v5.
    generators = [
        ('blockMeshDict', 'generate_blockMeshDict.py', f"{base_dir}/system/blockMeshDict"),
        ('topoSetDict',   'generate_topoSetDict.py',   f"{base_dir}/system/topoSetDict"),
        ('controlDict',   'generate_controlDict.py',   f"{base_dir}/system/controlDict"),
        ('thermophysicalProperties', 'generate_thermophysics.py', str(base_dir)),
        ('initial fields', 'generate_initial_fields.py', str(base_dir)),
        ('solver settings', 'generate_solver_settings.py', str(base_dir)),
        ('fvOptions', 'generate_fvOptions.py', str(base_dir)),
    ]
    
    for label, script, output in generators:
        print(f"--- {label} ---")
        cmd = ['python3', str(SCRIPT_DIR / script), str(config_path)]
        cmd.append(output)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                print(f"  {line}")
        if result.returncode != 0:
            print(f"  ERROR: {script} failed (exit {result.returncode})")
            if result.stdout:
                print(result.stdout)
            sys.exit(1)
        print()
    
    print("==============================================================")
    print("  Case built successfully.")
    print("==============================================================")
    print()
    print("Next steps:")
    print(f"  cd {base_dir}")
    print(f"  blockMesh > log.blockMesh 2>&1")
    print(f"  topoSet > log.topoSet 2>&1")
    print(f"  splitMeshRegions -cellZonesOnly -overwrite > log.splitMeshRegions 2>&1")
    print(f"  chtMultiRegionFoam > log.solver 2>&1 &")
    print()


if __name__ == '__main__':
    main()