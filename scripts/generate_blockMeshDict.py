#!/usr/bin/env python3
"""
generate_blockMeshDict.py — Generate blockMeshDict from YAML config.

Strategy: single hex block with multi-grading.
  - x-direction: 7 sub-blocks matching axial layout (case bottom, mica bottom,
    bottom stack region, electroactive, top stack region, mica top, case top).
    Stack regions get fine cells (~0.067mm), case_ss and mica caps get coarse
    cells (~0.5mm).
  - y-direction: 3 sub-blocks (stack inside, insulation wrap, case_ss wall),
    all ~0.5mm cells.
  - z-direction (wedge): 1 cell.

Reads from: config YAML (assembly + mesh sections)
Writes to: system/blockMeshDict
"""

import sys
from pathlib import Path
from config_loader import load_config, expand_assembly, get_radial_layout


HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
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
    object      blockMeshDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

// 2D axisymmetric thermal battery — generated from config
"""


def compute_axial_blocks(config):
    """
    Group flat axial layers into 7 sub-blocks for multi-grading.
    
    Returns list of (length_m, n_cells, label) tuples.
    """
    flat = expand_assembly(config)
    mesh = config['mesh']
    cell_stack_mm = mesh['axial_cell_size_stack_mm']
    cell_outside_mm = mesh['axial_cell_size_outside_mm']
    
    # Strategy: case_ss and insulation caps get coarse cells (cell_outside_mm).
    # Everything else (the stack region with its small layers) gets fine cells.
    #
    # The "stack region" is everything between the bottom mica cap and the top mica cap.
    # We identify case_ss layers (case bottom, case top) and mica caps separately,
    # and treat anything else as stack region.
    
    # Walk through flat layers and group by resolution
    blocks = []   # list of (length_mm, n_cells, label)
    cur_length_mm = 0
    cur_label = None
    cur_resolution = None   # 'fine' or 'coarse'
    
    def classify(material, position_idx, total_layers):
        """Classify a layer as fine (stack) or coarse (case/mica cap)."""
        # Heuristic: case_ss layers (only ever at very start or very end of axial sequence)
        # and the FIRST mica layer (after case_ss bottom) and LAST mica layer (before case_ss top)
        # are coarse. Everything else is fine (stack region).
        return material, position_idx
    
    # Identify boundary positions
    n = len(flat)
    
    # Find positions of case_ss layers (should be at very start and end)
    case_positions = [i for i, (m, _, _) in enumerate(flat) if m == 'case_ss']
    
    # Find positions of mica caps — these are the FIRST insulation layer after the
    # bottom case_ss and the LAST insulation layer before the top case_ss.
    # Detect by: first/last contiguous mica run touching the case.
    # v5: recognize any insulator_A_* or insulator_B_* material (was only 3 hardcoded names)
    def _is_insulation(mat_name):
        if mat_name.startswith('insulator_A_') or mat_name.startswith('insulator_B_'):
            return True
        # Backwards compatibility with v4 names
        if mat_name in ('insulation_mica', 'insulation_microporous', 'insulation_aerogel'):
            return True
        return False
    
    bottom_case_end = -1
    if case_positions:
        bottom_case_end = case_positions[0]
    
    # Walk forward from bottom_case_end to find end of bottom mica cap
    bottom_mica_end = bottom_case_end
    for i in range(bottom_case_end + 1, n):
        if _is_insulation(flat[i][0]):
            bottom_mica_end = i
        else:
            break
    
    # Walk backward to find start of top mica cap
    top_case_start = case_positions[-1] if case_positions else n
    top_mica_start = top_case_start
    for i in range(top_case_start - 1, -1, -1):
        if _is_insulation(flat[i][0]):
            top_mica_start = i
        else:
            break
    
    # Now classify each layer
    classifications = []   # 'coarse' or 'fine'
    for i, (mat, _, _) in enumerate(flat):
        if i <= bottom_case_end:
            # Bottom case_ss
            classifications.append('coarse')
        elif i <= bottom_mica_end:
            # Bottom mica cap
            classifications.append('coarse')
        elif i >= top_case_start:
            # Top case_ss
            classifications.append('coarse')
        elif i >= top_mica_start:
            # Top mica cap
            classifications.append('coarse')
        else:
            # Inside the stack region
            classifications.append('fine')
    
    # Group contiguous layers with same classification into blocks
    blocks = []
    cur_class = None
    cur_length_mm = 0
    cur_labels = []
    
    for i, ((mat, thick_m, label), cls) in enumerate(zip(flat, classifications)):
        thick_mm = thick_m * 1000
        if cls != cur_class:
            if cur_class is not None:
                # Emit previous block
                cell_size = cell_outside_mm if cur_class == 'coarse' else cell_stack_mm
                n_cells = round(cur_length_mm / cell_size)
                blocks.append((cur_length_mm, n_cells, cur_class))
            cur_class = cls
            cur_length_mm = thick_mm
            cur_labels = [label]
        else:
            cur_length_mm += thick_mm
            cur_labels.append(label)
    
    # Emit final block
    if cur_length_mm > 0:
        cell_size = cell_outside_mm if cur_class == 'coarse' else cell_stack_mm
        n_cells = round(cur_length_mm / cell_size)
        blocks.append((cur_length_mm, n_cells, cur_class))
    
    return blocks


def compute_radial_blocks(config):
    """Group radial layers into sub-blocks. Each layer is one block at radial cell size."""
    radial = get_radial_layout(config)
    cell_size_mm = config['mesh']['radial_cell_size_mm']
    
    blocks = []
    for material, thick_m in radial:
        thick_mm = thick_m * 1000
        n_cells = round(thick_mm / cell_size_mm)
        blocks.append((thick_mm, n_cells, material))
    return blocks


def generate(config):
    """Generate the blockMeshDict content."""
    import math
    
    axial_blocks = compute_axial_blocks(config)
    radial_blocks = compute_radial_blocks(config)
    
    total_axial_mm = sum(L for L, _, _ in axial_blocks)
    total_radial_mm = sum(L for L, _, _ in radial_blocks)
    
    total_axial_cells = sum(n for _, n, _ in axial_blocks)
    total_radial_cells = sum(n for _, n, _ in radial_blocks)
    
    # x_offset: where does case_ss bottom start? Default -5 mm.
    x_offset_mm = config['mesh'].get('x_offset_mm', -5.0)
    x_min_m = x_offset_mm * 1e-3
    x_max_m = x_min_m + total_axial_mm * 1e-3
    y_max_m = total_radial_mm * 1e-3
    
    # Wedge angle
    half_angle_deg = config['mesh']['wedge_angle_deg']
    half_angle_rad = math.radians(half_angle_deg)
    z_at_outer = y_max_m * math.sin(half_angle_rad)
    
    # Compose simpleGrading entries
    # Format: ( fraction n_cells expansion_ratio )
    axial_grading_entries = []
    for L_mm, n_cells, label in axial_blocks:
        fraction = L_mm / total_axial_mm
        axial_grading_entries.append((fraction, n_cells, label))
    
    radial_grading_entries = []
    for L_mm, n_cells, label in radial_blocks:
        fraction = L_mm / total_radial_mm
        radial_grading_entries.append((fraction, n_cells, label))
    
    # Build the blockMeshDict text
    out = HEADER
    out += "// Generated by generate_blockMeshDict.py\n"
    out += f"// Total axial extent: {total_axial_mm:.3f} mm  ({total_axial_cells} cells)\n"
    out += f"// Total radial extent: {total_radial_mm:.3f} mm  ({total_radial_cells} cells)\n"
    out += f"// Wedge half-angle: {half_angle_deg} deg, z at outer = ±{z_at_outer*1000:.4f} mm\n\n"
    
    out += "scale 1.0;\n\n"
    
    out += "vertices\n(\n"
    out += f"    // n3=0 face (back wedge, z = -y*sin)\n"
    out += f"    ( {x_min_m:.6f}    0          0          )   // 0\n"
    out += f"    ( {x_max_m:.6f}    0          0          )   // 1\n"
    out += f"    ( {x_max_m:.6f}    {y_max_m:.6f}    {-z_at_outer:.6f}   )   // 2\n"
    out += f"    ( {x_min_m:.6f}    {y_max_m:.6f}    {-z_at_outer:.6f}   )   // 3\n\n"
    out += f"    // n3=max face (front wedge, z = +y*sin)\n"
    out += f"    ( {x_min_m:.6f}    0          0          )   // 4\n"
    out += f"    ( {x_max_m:.6f}    0          0          )   // 5\n"
    out += f"    ( {x_max_m:.6f}    {y_max_m:.6f}     {z_at_outer:.6f}   )   // 6\n"
    out += f"    ( {x_min_m:.6f}    {y_max_m:.6f}     {z_at_outer:.6f}   )   // 7\n"
    out += ");\n\n"
    
    out += "blocks\n(\n"
    out += f"    hex (0 1 2 3 4 5 6 7) ({total_axial_cells} {total_radial_cells} 1)\n"
    out += "    simpleGrading\n    (\n"
    out += "        (\n"
    for frac, n_cells, label in axial_grading_entries:
        out += f"            ( {frac:.4f} {n_cells} 1 )    // {label}\n"
    out += "        )\n"
    out += "        (\n"
    for frac, n_cells, label in radial_grading_entries:
        out += f"            ( {frac:.4f} {n_cells} 1 )    // {label}\n"
    out += "        )\n"
    out += "        1\n"
    out += "    )\n"
    out += ");\n\n"
    
    out += "edges\n(\n);\n\n"
    
    out += """boundary
(
    axis
    {
        type empty;
        faces ( (0 1 5 4) );
    }
    wedgeFront
    {
        type wedge;
        faces ( (4 5 6 7) );
    }
    wedgeBack
    {
        type wedge;
        faces ( (0 3 2 1) );
    }
    outerCase
    {
        type patch;
        faces ( (3 7 6 2) );
    }
    bottom
    {
        type patch;
        faces ( (0 4 7 3) );
    }
    top
    {
        type patch;
        faces ( (1 2 6 5) );
    }
);

mergePatchPairs
(
);

// ************************************************************************* //
"""
    
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 generate_blockMeshDict.py <config.yaml> [output_path]")
    
    config_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "system/blockMeshDict"
    
    config = load_config(config_path)
    content = generate(config)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(content)
    
    # Diagnostic to stderr
    axial_blocks = compute_axial_blocks(config)
    radial_blocks = compute_radial_blocks(config)
    total_cells = sum(n for _, n, _ in axial_blocks) * sum(n for _, n, _ in radial_blocks)
    print(f"Wrote {output_path}", file=sys.stderr)
    print(f"  Axial sub-blocks: {len(axial_blocks)}", file=sys.stderr)
    for L, n, label in axial_blocks:
        print(f"    {L:7.2f} mm  {n:>4d} cells  ({label})", file=sys.stderr)
    print(f"  Radial sub-blocks: {len(radial_blocks)}", file=sys.stderr)
    for L, n, label in radial_blocks:
        print(f"    {L:7.2f} mm  {n:>4d} cells  ({label})", file=sys.stderr)
    print(f"  Total cells: {total_cells}", file=sys.stderr)


if __name__ == '__main__':
    main()
