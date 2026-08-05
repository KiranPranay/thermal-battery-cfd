#!/usr/bin/env python3
"""
generate_controlDict.py — Generate system/controlDict from config.

v5 changes:
  - Uses config_loader.get_unique_regions() so insulation_A and insulation_B
    are correctly tracked in function objects
  - No more local INSULATION_KEYWORDS / material_to_region (centralized)
  - stack_regions filter excludes insulation_A, insulation_B, and case_ss

Includes per-region function objects to track max T per region.

Reads from: config YAML (run_controls section)
Writes to:  system/controlDict
"""

import sys
from pathlib import Path
from config_loader import (
    load_config, get_unique_regions,
    REGION_INSULATOR_A, REGION_INSULATOR_B,
)


HEADER = '''/*--------------------------------*- C++ -*----------------------------------*\\
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
    class       dictionary;
    location    "system";
    object      controlDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

application     chtMultiRegionFoam;
'''


def generate(config):
    rc = config['run_controls']
    
    out = HEADER
    out += "startFrom       startTime;\n"
    out += "startTime       0;\n"
    out += "stopAt          endTime;\n"
    out += f"endTime         {rc['endTime_s']};\n\n"
    out += f"deltaT          {float(rc['deltaT_initial_s'])};\n\n"
    out += "writeControl    adjustable;\n"
    out += f"writeInterval   {rc['write_interval_s']};\n"
    out += "purgeWrite      0;\n"
    out += "writeFormat     binary;\n"
    out += "writePrecision  8;\n"
    out += "writeCompression off;\n"
    out += "timeFormat      general;\n"
    out += "timePrecision   6;\n"
    out += "runTimeModifiable true;\n\n"
    
    out += f"adjustTimeStep  {'yes' if rc.get('adaptive_timestep', True) else 'no'};\n"
    out += f"maxCo           {rc.get('maxCo', 0.5)};\n"
    out += f"maxDi           {rc.get('maxDi', 0.4)};\n"
    out += f"maxDeltaT       {float(rc.get('maxDeltaT_s', 1e-3))};\n\n"
    
    # Function objects: max T per region for stack-internal regions, 
    # plus skin T on case_ss outerCase
    regions = get_unique_regions(config)
    
    out += "functions\n{\n"
    
    # Define a template function object for max T, then alias for each region
    # Pick the first stack-internal region as template
    # Stack-internal = NOT insulation_A, NOT insulation_B, NOT case_ss
    stack_regions = [r for r in regions 
                     if r not in (REGION_INSULATOR_A, REGION_INSULATOR_B, 'case_ss')]
    if stack_regions:
        template_region = stack_regions[0]
        out += f"    maxT_{template_region}\n"
        out += "    {\n"
        out += f"        type            volFieldValue;\n"
        out += f"        libs            (fieldFunctionObjects);\n"
        out += f"        region          {template_region};\n"
        out += f"        fields          (T);\n"
        out += f"        operation       max;\n"
        out += f"        writeFields     false;\n"
        out += f"        writeControl    timeStep;\n"
        out += f"        writeInterval   100;\n"
        out += f"        log             true;\n"
        out += "    }\n\n"
        
        # Aliases for other regions
        for r in regions:
            if r == template_region:
                continue
            out += f"    maxT_{r} {{ ${{maxT_{template_region}}}; region {r}; }}\n"
        out += "\n"
    
    # Skin temperature: areaAverage on outerCase patch of case_ss region
    if 'case_ss' in regions:
        out += "    skinT_outerCase\n"
        out += "    {\n"
        out += "        type            surfaceFieldValue;\n"
        out += "        libs            (fieldFunctionObjects);\n"
        out += "        region          case_ss;\n"
        out += "        regionType      patch;\n"
        out += "        name            outerCase;\n"
        out += "        operation       areaAverage;\n"
        out += "        fields          (T);\n"
        out += "        writeFields     false;\n"
        out += "        writeControl    timeStep;\n"
        out += "        writeInterval   100;\n"
        out += "        log             true;\n"
        out += "    }\n"
    
    out += "}\n\n"
    out += "// ************************************************************************* //\n"
    
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 generate_controlDict.py <config.yaml> [output_path]")
    
    config_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "system/controlDict"
    
    config = load_config(config_path)
    content = generate(config)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(content)
    
    print(f"Wrote {output_path}", file=sys.stderr)
    rc = config['run_controls']
    print(f"  endTime: {rc['endTime_s']}s, write every {rc['write_interval_s']}s", file=sys.stderr)


if __name__ == '__main__':
    main()