#!/usr/bin/env python3
"""
config_loader.py — Common YAML loading + validation for the thermal-battery-cfd pipeline.

v5 changes:
  - Supports separate Insulator A (always mica) and Insulator B (parametric)
  - Material names insulator_A_* and insulator_B_* recognized
  - Generic 'insulator_B' reference in radial_sequence resolves at config-load time
  - get_primary_insulator_A_material() and get_primary_insulator_B_material() helpers

Provides:
  - load_config(path) — parses YAML, validates structure, returns dict
  - expand_assembly(config) — expands axial_sequence blocks into flat layer list
  - get_radial_layout(config) — radial layers with insulator_B placeholders resolved
  - get_unique_materials(config) — set of material names used after resolution
  - get_primary_insulator_A_material(config)
  - get_primary_insulator_B_material(config)
  - validate_geometry(config) — sanity checks (totals, mesh resolution)
  - material_to_region(material) — map material name to OpenFOAM region name

All other generator scripts should import from here. Do not parse YAML directly.
"""

import yaml
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any


# Material categories — used to determine OpenFOAM region assignment
INSULATOR_A_PREFIX = 'insulator_A_'
INSULATOR_B_PREFIX = 'insulator_B_'
INSULATOR_B_PLACEHOLDER = 'insulator_B'    # generic reference resolved per-case

# Region names in OpenFOAM (post splitMeshRegions)
REGION_INSULATOR_A = 'insulation_A'
REGION_INSULATOR_B = 'insulation_B'


def load_config(path) -> Dict[str, Any]:
    """Load and validate a YAML config file. Exits on validation errors."""
    path = Path(path)
    if not path.exists():
        sys.exit(f"ERROR: config file not found: {path}")
    
    with open(path) as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            sys.exit(f"ERROR: invalid YAML in {path}: {e}")
    
    _validate_structure(config, path)
    return config


def _validate_structure(config: dict, path: Path) -> None:
    """Check that all required top-level sections are present."""
    required = ['case', 'materials', 'assembly', 'mesh', 'heat_sources',
                'boundary_conditions', 'run_controls', 'validation']
    missing = [k for k in required if k not in config]
    if missing:
        sys.exit(f"ERROR: {path} missing required sections: {missing}")
    
    asm = config['assembly']
    if 'axial_sequence' not in asm:
        sys.exit(f"ERROR: {path} missing assembly.axial_sequence")
    if 'radial_sequence' not in asm:
        sys.exit(f"ERROR: {path} missing assembly.radial_sequence")
    
    # Check that all materials referenced in assembly exist in materials section
    # OR are valid placeholders that get resolved
    materials = set(config['materials'].keys())
    materials.add('stack_internal')
    materials.add(INSULATOR_B_PLACEHOLDER)   # placeholder is allowed in radial
    
    referenced = _collect_referenced_materials(config)
    unknown = referenced - materials
    if unknown:
        sys.exit(f"ERROR: {path} references undefined materials: {unknown}")
    
    # Verify primary_insulator_B_material is set and refers to a valid material
    primary_B = get_primary_insulator_B_material(config)
    if primary_B is None:
        sys.exit(f"ERROR: {path} must specify primary_insulator_B_material "
                 f"(or have at least one insulator_B_* material defined)")
    if primary_B not in config['materials']:
        sys.exit(f"ERROR: primary_insulator_B_material='{primary_B}' "
                 f"is not defined in materials section")


def _collect_referenced_materials(config: dict) -> set:
    """Return all material names referenced anywhere in the assembly."""
    used = set()
    asm = config['assembly']
    blocks = asm.get('blocks', {})
    
    for item in asm['axial_sequence']:
        if 'material' in item:
            used.add(item['material'])
        elif 'block' in item:
            block = blocks.get(item['block'])
            if block is None:
                sys.exit(f"ERROR: assembly.axial_sequence references undefined block: {item['block']}")
            for layer in block['layers']:
                used.add(layer['material'])
    
    for item in asm['radial_sequence']:
        if 'material' in item:
            used.add(item['material'])
    
    return used


def get_primary_insulator_A_material(config: dict):
    """Return the material name to use for any 'insulator_A' references.
    
    Defaults to insulator_A_mica if not specified — Insulator A is fixed
    by Jeong's design and parametric studies should keep it constant.
    """
    primary = config.get('primary_insulator_A_material')
    if primary and primary in config['materials']:
        return primary
    
    # Auto-detect: find the first insulator_A_* material defined
    for mat_name in config['materials']:
        if mat_name.startswith(INSULATOR_A_PREFIX):
            return mat_name
    
    return None


def get_primary_insulator_B_material(config: dict):
    """Return the material name to use for any 'insulator_B' placeholder references.
    
    This is the parametric variable — varied per case.
    """
    primary = config.get('primary_insulator_B_material')
    if primary and primary in config['materials']:
        return primary
    
    # Auto-detect: find the first insulator_B_* material defined
    for mat_name in config['materials']:
        if mat_name.startswith(INSULATOR_B_PREFIX):
            return mat_name
    
    return None


def material_to_region(material: str) -> str:
    """Map a material name to its OpenFOAM region name.
    
    All insulator_A_* materials → 'insulation_A'
    All insulator_B_* materials (including the placeholder) → 'insulation_B'
    All others → use material name as-is
    """
    if material == INSULATOR_B_PLACEHOLDER:
        return REGION_INSULATOR_B
    if material.startswith(INSULATOR_A_PREFIX):
        return REGION_INSULATOR_A
    if material.startswith(INSULATOR_B_PREFIX):
        return REGION_INSULATOR_B
    return material


def resolve_insulator_B(material: str, primary_B: str) -> str:
    """If material is the generic insulator_B placeholder, resolve to the actual material name."""
    if material == INSULATOR_B_PLACEHOLDER:
        return primary_B
    return material


def expand_assembly(config: dict) -> List[Tuple[str, float, str]]:
    """
    Expand the axial_sequence (with blocks and repeats) into a flat list.
    
    Returns list of (material_name, thickness_m, label) tuples.
    Material names are NOT resolved here — insulator_A_* names stay as-is.
    """
    asm = config['assembly']
    blocks = asm.get('blocks', {})
    seq = asm['axial_sequence']
    
    flat = []
    seq_idx = 0
    
    for item in seq:
        if 'material' in item:
            mat = item['material']
            thick_m = item['thickness_mm'] * 1e-3
            label = item.get('label', f"layer{seq_idx:03d}_{mat}")
            flat.append((mat, thick_m, label))
            seq_idx += 1
        elif 'block' in item:
            block_name = item['block']
            repeat = item.get('repeat', 1)
            block = blocks[block_name]
            for r in range(repeat):
                for li, layer in enumerate(block['layers']):
                    mat = layer['material']
                    thick_m = layer['thickness_mm'] * 1e-3
                    label = f"{block_name}_{r:02d}_l{li}_{mat}"
                    flat.append((mat, thick_m, label))
                    seq_idx += 1
    
    return flat


def get_radial_layout(config: dict) -> List[Tuple[str, float]]:
    """Return radial layers as list of (material, thickness_m).
    
    Resolves the generic insulator_B placeholder to the actual material
    chosen for this run via primary_insulator_B_material.
    """
    radial = config['assembly']['radial_sequence']
    primary_B = get_primary_insulator_B_material(config)
    
    out = []
    for r in radial:
        mat = resolve_insulator_B(r['material'], primary_B)
        out.append((mat, r['thickness_mm'] * 1e-3))
    return out


def get_unique_materials(config: dict) -> List[str]:
    """Return sorted list of material names actually used (after Insulator B resolution)."""
    flat = expand_assembly(config)
    primary_B = get_primary_insulator_B_material(config)
    
    used = set()
    for mat, _, _ in flat:
        used.add(resolve_insulator_B(mat, primary_B))
    for mat, _ in get_radial_layout(config):
        used.add(mat)
    
    used.discard('stack_internal')   # virtual
    return sorted(used)


def get_unique_regions(config: dict) -> List[str]:
    """Return sorted list of OpenFOAM region names that will be created.
    
    All insulator_A_* materials map to 'insulation_A',
    all insulator_B_* materials map to 'insulation_B',
    everything else maps to its material name.
    """
    materials = get_unique_materials(config)
    regions = set()
    for mat in materials:
        regions.add(material_to_region(mat))
    return sorted(regions)


def get_total_axial_extent_m(config: dict) -> float:
    flat = expand_assembly(config)
    return sum(thick for _, thick, _ in flat)


def get_total_radial_extent_m(config: dict) -> float:
    radial = get_radial_layout(config)
    return sum(thick for _, thick in radial)


def validate_geometry(config: dict, verbose: bool = True) -> None:
    """Print geometry summary and check for issues."""
    flat = expand_assembly(config)
    radial = get_radial_layout(config)
    
    total_axial = get_total_axial_extent_m(config) * 1000
    total_radial = get_total_radial_extent_m(config) * 1000
    
    primary_A = get_primary_insulator_A_material(config)
    primary_B = get_primary_insulator_B_material(config)
    
    if verbose:
        print(f"=== Geometry summary ===")
        print(f"Case: {config['case']['name']}")
        print(f"Total axial extent: {total_axial:.2f} mm")
        print(f"Total radial extent: {total_radial:.2f} mm")
        print(f"Total layers (after expansion): {len(flat)}")
        print()
        print(f"Insulator selection:")
        print(f"  Insulator A (fixed):  {primary_A}")
        print(f"  Insulator B (varied): {primary_B}")
        print()
    
    from collections import Counter
    mat_thickness = Counter()
    mat_count = Counter()
    for mat, thick, _ in flat:
        # Resolve placeholder for accounting purposes
        resolved = resolve_insulator_B(mat, primary_B)
        mat_thickness[resolved] += thick
        mat_count[resolved] += 1
    
    if verbose:
        print(f"Material breakdown (axial):")
        for mat in sorted(mat_thickness):
            print(f"  {mat:30s}: {mat_count[mat]:3d} pieces, total {mat_thickness[mat]*1000:.2f} mm")
        print()
    
    # Region breakdown
    if verbose:
        regions = get_unique_regions(config)
        print(f"OpenFOAM regions ({len(regions)}):")
        for r in regions:
            print(f"  {r}")
        print()
    
    mesh = config['mesh']
    min_thickness = min(thick for _, thick, _ in flat)
    cells_in_smallest = min_thickness / (mesh['axial_cell_size_stack_mm'] * 1e-3)
    if verbose:
        print(f"Mesh resolution check:")
        print(f"  Smallest layer thickness: {min_thickness*1000:.3f} mm")
        print(f"  Stack cell size: {mesh['axial_cell_size_stack_mm']:.3f} mm")
        print(f"  Cells across smallest layer: {cells_in_smallest:.1f}")
        if cells_in_smallest < 2:
            print(f"  WARNING: smallest layer has < 2 cells.")


def get_axial_position_x_mm(config: dict, x_offset_mm: float = -5.0) -> float:
    return config['mesh'].get('x_offset_mm', x_offset_mm)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 config_loader.py <config.yaml>")
    
    config = load_config(sys.argv[1])
    validate_geometry(config, verbose=True)
    print(f"\n✓ Config validates: {sys.argv[1]}")
