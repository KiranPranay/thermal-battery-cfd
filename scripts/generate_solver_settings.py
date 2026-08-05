#!/usr/bin/env python3
"""
generate_solver_settings.py — Generate system/<region>/fvSchemes and fvSolution.

v5 changes:
  - Uses config_loader.get_unique_regions() so insulation_A and insulation_B
    both get solver settings
  - No more local INSULATION_KEYWORDS list (centralized in config_loader)

These files don't have config-dependent values (numerical schemes are universal
for solid heat conduction). But we need one set per region.

Reads from: config YAML (just to know which regions exist)
Writes to:  system/<region>/fvSchemes and system/<region>/fvSolution
"""

import sys
from pathlib import Path
from config_loader import load_config, get_unique_regions


FVSCHEMES = '''/*--------------------------------*- C++ -*----------------------------------*\\
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
    location    "system/{region}";
    object      fvSchemes;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

ddtSchemes      {{ default Euler; }}
gradSchemes     {{ default Gauss linear; }}
divSchemes      {{ default none; }}
laplacianSchemes
{{
    default             none;
    laplacian(alpha,h)  Gauss linear corrected;
}}
interpolationSchemes {{ default linear; }}
snGradSchemes   {{ default corrected; }}

// ************************************************************************* //
'''

FVSOLUTION = '''/*--------------------------------*- C++ -*----------------------------------*\\
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
    location    "system/{region}";
    object      fvSolution;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

solvers
{{
    h
    {{
        solver           PCG;
        preconditioner   DIC;
        tolerance        1e-06;
        relTol           0.1;
    }}

    hFinal
    {{
        $h;
        tolerance        1e-06;
        relTol           0;
    }}
}}

PIMPLE
{{
    nNonOrthogonalCorrectors 0;
}}

// ************************************************************************* //
'''


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 generate_solver_settings.py <config.yaml> [base_dir]")
    
    config_path = sys.argv[1]
    base_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('.')
    
    config = load_config(config_path)
    regions = get_unique_regions(config)
    
    written = 0
    for region in regions:
        for fname, template in (('fvSchemes', FVSCHEMES), ('fvSolution', FVSOLUTION)):
            path = base_dir / 'system' / region / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                f.write(template.format(region=region))
            written += 1
            print(f"Wrote {path}", file=sys.stderr)
    
    print(f"\nDone: {written} solver setting files generated for {len(regions)} regions", file=sys.stderr)


if __name__ == '__main__':
    main()
