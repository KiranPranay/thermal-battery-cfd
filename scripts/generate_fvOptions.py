#!/usr/bin/env python3
"""
generate_fvOptions.py — Generate constant/<region>/fvOptions for active sources.

For each enabled heat source in config:
  - pyrotechnic: applied to target_material region (e.g. heatPellet)
  - joule_heating: applied to target_material (e.g. cathode); Jeong 2019 Eq. 1
  - chemical_reaction: applied to target_materials (e.g. cathode+anode); Jeong Eq. 2

Joule heating physics (Jeong 2019 §2.1, Eq. 1):
    q_jh = i_A^2 * R       [W/m^3]
        i_A : current per cross-sectional area, A/m^2  (config gives A/cm^2)
        R   : cathode volumetric resistance, Ohm*m

Chemical reaction (entropy) heat (Jeong 2019 §2.1, Eq. 2):
    q_cr = i_V * (-T * dU0/dT)        [W/m^3]
        i_V    : current per unit volume, A/m^3 = i_A / r (r = cell radius)
        T      : local cell temperature, K (constant-T approximation here — see below)
        dU0/dT : entropic coefficient, V/K (sign per Jeong; +2e-4 here -> endothermic)

Net for Case 1 (i_A=0.5 A/cm^2, dU0/dT=+2e-4, T~800 K, r=0.0205 m):
    q_jh  =  +4500   W/m^3  (cathode only)
    q_cr  =  -39024  W/m^3  (cathode + anode)
    Net cathode = +4500 - 39024 = -34524 W/m^3   (endothermic, drives cooldown)
    Net anode   =  0    - 39024 = -39024 W/m^3   (endothermic)

Discharge sources are TIME-gated at activation_after_s (3.0 s for Jeong Case 1).
A liquid-fraction-gated source (alpha > 0.99 in coldest electrolyte cell, per
Jeong's activation criterion) is the more physical upgrade — left as a
follow-up; activation timing in this geometry is monotonic at ~3 s so the
time gate is a defensible first cut.

Reads from: config YAML (heat_sources section)
Writes to:  constant/<region>/fvOptions  (one file per region, ALL source
            blocks for that region collected into a single file)
            constant/<region>/<source>SourceTable  (one table per source)
"""

import sys
from pathlib import Path
from collections import defaultdict
from config_loader import load_config


# -- Reference temperature for the sensibleEnthalpy convention (OpenFOAM
#    default Tstd = 298.15 K, with Hf = 0 in every thermophysicalProperties
#    file — verified across all region generators). h(T) = Cp*(T - T_REF_K)
#    for the constant-Cp regions; the T-linear chemical source uses this
#    exact map to split q_cr = -c*T into an (Su, Sp) pair the solver treats
#    as unconditionally stabilising (Sp < 0).
T_REF_K = 298.15

# -- Cell radius for i_V = i_A / r in chemical reaction (Jeong Eq. 2).
# Phase 5 correction: Jeong Fig 1a's "41 mm" label is the STACK RADIUS
# (radial dimension), not the diameter. Configs post-geomcorr use
# stack_internal radial thickness = 41 mm. Corrected r = 0.041 m
# (supersedes the 0.0205 used in Phases 1-2, which mis-read Fig 1's
# radial 41 mm as diameter).
CELL_RADIUS_M = 0.041

# -- Representative cell temperature for chemical-reaction source.
# Jeong applies the entropic term across the operating band (~500-800 C).
# Constant-T approximation here (T_REP_K = 800 K) — physical upgrade is a
# T-coupled source (codedSource reading T at each cell at each step).
T_REP_K = 800.0


# ===== File header / footer (shared across all sources per region) ============

FVOPTIONS_HEADER = '''/*--------------------------------*- C++ -*----------------------------------*\\
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
    location    "constant/{region}";
    object      fvOptions;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

'''

FVOPTIONS_FOOTER = '''
// ************************************************************************* //
'''


# ===== Per-source block templates (no header/footer; rendered inline) =========

PYRO_BLOCK_TEMPLATE = '''// Pyrotechnic heat source — Jeong 2019 §2.1 (activation phase).
// q_volumetric = {q} W/m^3 at peak burn; time profile from pyroSourceTable.

pyroSource
{{
    type            scalarSemiImplicitSource;
    active          true;

    scalarSemiImplicitSourceCoeffs
    {{
        selectionMode   all;
        volumeMode      specific;

        sources
        {{
            h
            {{
                explicit
                {{
                    type        tableFile;
                    file        "constant/{region}/pyroSourceTable";
                }}
                implicit        0;
            }}
        }}
    }}
}}
'''

JOULE_BLOCK_TEMPLATE = '''// Joule heating source — Jeong 2019 §2.1 Eq. 1.
//   q_jh = i_A^2 * R                    [W/m^3, applied to {region}]
//     i_A = {iA_cm2} A/cm^2 = {iA:.1f} A/m^2
//     R   = {R} Ohm*m  (cathode_resistance_ohm_m)
//     q_jh = ({iA:.1f})^2 * {R} = {q_jh:.4e} W/m^3
//
// Time-gated via jouleSourceTable: q = 0 before t = {act_t} s, q = q_jh after.

jouleSource
{{
    type            scalarSemiImplicitSource;
    active          true;

    scalarSemiImplicitSourceCoeffs
    {{
        selectionMode   all;
        volumeMode      specific;

        sources
        {{
            h
            {{
                explicit
                {{
                    type        tableFile;
                    file        "constant/{region}/jouleSourceTable";
                }}
                implicit        0;
            }}
        }}
    }}
}}
'''

CHEMICAL_BLOCK_TEMPLATE = '''// Chemical reaction (entropic) heat — Jeong 2019 §2.1 Eq. 2, T-LINEAR form.
//   q_cr = -c * T                       [W/m^3, applied to {region}]
//     c      = i_V * (dU0/dT)
//            = (i_A / r) * (dU0/dT)
//            = ({iA:.1f} / {r}) * {dUdT}
//            = {c:.4e} W/m^3/K
//     i_V    = i_A / r = {iV:.4e} A/m^3
//     dU0/dT = {dUdT} V/K
//
// SEMI-IMPLICIT DECOMPOSITION (unconditionally stabilising, Sp < 0):
//   T = h / Cp + T_ref     with T_ref = {T_ref} K, Cp_{region} = {Cp} J/kg/K
//   q_cr = -c * (h/Cp + T_ref)
//        = (-c * T_ref) + (-c / Cp) * h
//        = Su + Sp * h
//   Su   = -c * T_ref = {Su_cr:.4e} W/m^3       (constant, explicit)
//   Sp   = -c / Cp    = {Sp_cr:.4e} 1/s          (implicit coefficient of h)
//
// Net rate at any T is exact Jeong Eq. 2: q_cr = -c * T. At T = 800 K this
// gives {q_cr_at_800:.4e} W/m^3 (matches the earlier constant-800 value to
// numerical precision).
//
// Time-gated via chemicalSuTable + chemicalSpTable: both step from 0 to
// their post-activation values at t = {act_t} s.

chemicalSource
{{
    type            scalarSemiImplicitSource;
    active          true;

    scalarSemiImplicitSourceCoeffs
    {{
        selectionMode   all;
        volumeMode      specific;

        sources
        {{
            h
            {{
                explicit
                {{
                    type        tableFile;
                    file        "constant/{region}/chemicalSuTable";
                }}
                implicit
                {{
                    type        tableFile;
                    file        "constant/{region}/chemicalSpTable";
                }}
            }}
        }}
    }}
}}
'''


# ===== Source descriptor builders =============================================
# Each builder returns one or more descriptors; a descriptor is a dict with:
#   region:         target region name
#   block_text:     the named-source block to embed in fvOptions
#   table_filename: filename for the source table under constant/<region>/
#   table_content:  full text content of the table file

def _build_pyro_descriptor(pyro_cfg):
    region = pyro_cfg['target_material']
    q_max = float(pyro_cfg['q_volumetric_W_per_m3'])
    profile = pyro_cfg['time_profile']

    # Pyro table reuses the existing format
    table_lines = ["// Pyrotechnic heat source table — generated from config",
                   "// Format: (time_s    q_volumetric_W_per_m3)",
                   f"// q_max = {q_max} W/m^3",
                   "",
                   "("]
    for entry in profile:
        t = float(entry[0])
        frac = float(entry[1])
        q = q_max * frac
        table_lines.append(f"    ({t:8.3f}   {q:.4e})")
    table_lines.append(")")

    return [{
        'region':         region,
        'block_text':     PYRO_BLOCK_TEMPLATE.format(region=region, q=q_max),
        'table_filename': 'pyroSourceTable',
        'table_content':  '\n'.join(table_lines) + '\n',
    }]


def _step_table_lines(name_hdr, q_value, act_t, comment_lines=None):
    """Build a step-function tableFile body: 0 before act_t, q_value after.
    OpenFOAM tableFile clamps outside the range, so the final (1e6, q_value)
    pair makes the source hold indefinitely after activation."""
    eps = 0.001
    lines = [f"// {name_hdr}",
             "// Format: (time_s    q_volumetric_W_per_m3)",
             "// Step function at activation_after_s (1 ms ramp).",
             f"// q after activation = {q_value:.4e} W/m^3"]
    if comment_lines:
        lines.extend(f"// {c}" for c in comment_lines)
    lines += ["",
              "(",
              f"    ({0.0:>10.3f}   {0.0:.4e})",
              f"    ({max(act_t - eps, 0.0):>10.3f}   {0.0:.4e})",
              f"    ({act_t:>10.3f}   {q_value:.4e})",
              f"    ({1.0e6:>10.1f}   {q_value:.4e})",
              ")"]
    return '\n'.join(lines) + '\n'


def _build_joule_descriptor(jh_cfg):
    region = jh_cfg['target_material']
    iA_cm2 = float(jh_cfg['current_density_A_per_cm2'])
    iA = iA_cm2 * 1.0e4              # A/cm^2 -> A/m^2
    R = float(jh_cfg['cathode_resistance_ohm_m'])
    q_jh = iA * iA * R               # W/m^3 (Jeong Eq. 1)
    act_t = float(jh_cfg.get('activation_after_s', 3.0))

    return [{
        'region': region,
        'block_text': JOULE_BLOCK_TEMPLATE.format(
            region=region, iA=iA, iA_cm2=iA_cm2, R=R, q_jh=q_jh, act_t=act_t,
        ),
        'table_filename': 'jouleSourceTable',
        'table_content': _step_table_lines(
            "Joule heating source table — Jeong 2019 Eq. 1 (cathode)",
            q_jh, act_t,
            comment_lines=[f"i_A = {iA_cm2} A/cm^2 ({iA:.0f} A/m^2), R = {R} Ohm*m"],
        ),
    }]


def _build_chemical_descriptors(cr_cfg, jh_cfg, materials):
    """Chemical-reaction sources for each target region — T-LINEAR form.

    Emits Jeong Eq. 2 exactly (q_cr = -c*T, not the constant-800 K
    approximation) via OpenFOAM's scalarSemiImplicitSource (Su, Sp) pair.
    See CHEMICAL_BLOCK_TEMPLATE for the derivation.

    Reads current density from joule_heating (i_A is the SAME current the
    cell is discharging at — Jeong uses one i_A for both Joule and chemical).
    Reads Cp per target region from `materials` so Sp = -c/Cp is exact.
    """
    targets = cr_cfg['target_materials']
    if not jh_cfg or 'current_density_A_per_cm2' not in jh_cfg:
        sys.exit("ERROR: chemical_reaction requires joule_heating.current_density_A_per_cm2 "
                 "to be set in heat_sources (they share i_A per Jeong).")
    iA_cm2 = float(jh_cfg['current_density_A_per_cm2'])
    iA = iA_cm2 * 1.0e4                    # A/m^2
    iV = iA / CELL_RADIUS_M                # A/m^3 (Jeong: i_V = i_A / r)
    dUdT = float(cr_cfg['dU0_dT_V_per_K'])
    act_t = float(cr_cfg.get('activation_after_s', 3.0))

    # Jeong Eq. 2 in T-linear form: q_cr = -c * T with c = i_V * dU0/dT.
    # c > 0 for dU0/dT > 0  =>  q_cr = -c*T < 0 (endothermic, drives cooldown).
    c = iV * dUdT                           # W/m^3/K

    descriptors = []
    for region in targets:
        if region not in materials:
            sys.exit(f"ERROR: chemical_reaction target '{region}' not in config.materials "
                     f"(need cp_J_per_kg_K to compute Sp = -c/Cp)")
        Cp = float(materials[region]['cp_J_per_kg_K'])
        Su_cr = -c * T_REF_K               # W/m^3 (explicit)
        Sp_cr = -c / Cp                     # 1/s (implicit coefficient of h)
        q_cr_at_800 = -c * 800.0            # for the header comment / sanity check

        descriptors.append({
            'region': region,
            'block_text': CHEMICAL_BLOCK_TEMPLATE.format(
                region=region, iA=iA, r=CELL_RADIUS_M, iV=iV,
                dUdT=dUdT, c=c, T_ref=T_REF_K, Cp=Cp,
                Su_cr=Su_cr, Sp_cr=Sp_cr, q_cr_at_800=q_cr_at_800,
                act_t=act_t,
            ),
            'table_filenames': ['chemicalSuTable', 'chemicalSpTable'],
            'table_contents':  [
                _step_table_lines(
                    f"Chemical reaction Su — Jeong 2019 Eq. 2 explicit part ({region})",
                    Su_cr, act_t,
                    comment_lines=[
                        f"Su = -c * T_ref = -{c:.4e} * {T_REF_K} = {Su_cr:.4e} W/m^3",
                        f"c = (i_A/r) * dU0/dT = ({iA:.0f}/{CELL_RADIUS_M}) * {dUdT} = {c:.4e} W/m^3/K",
                    ],
                ),
                _step_table_lines(
                    f"Chemical reaction Sp — Jeong 2019 Eq. 2 implicit coefficient ({region})",
                    Sp_cr, act_t,
                    comment_lines=[
                        f"Sp = -c / Cp_{region} = -{c:.4e} / {Cp} = {Sp_cr:.4e} 1/s",
                        f"Sp < 0 -> unconditionally stabilising in the h equation.",
                    ],
                ),
            ],
        })
    return descriptors


# ===== Collection + writing ==================================================

def collect_sources(config):
    """Walk config and assemble a flat list of source descriptors."""
    sources = []
    hs = config.get('heat_sources', {})

    pyro = hs.get('pyrotechnic', {})
    if pyro.get('enabled', False):
        sources.extend(_build_pyro_descriptor(pyro))

    jh = hs.get('joule_heating', {})
    if jh.get('enabled', False):
        sources.extend(_build_joule_descriptor(jh))

    cr = hs.get('chemical_reaction', {})
    if cr.get('enabled', False):
        materials = config.get('materials', {})
        sources.extend(_build_chemical_descriptors(cr, jh, materials))

    return sources


def write_all_sources(sources, base_dir):
    """Group sources by region, write ONE fvOptions per region containing
    every source block for that region, plus each source's table file.

    This is the critical correctness contract: OpenFOAM reads exactly one
    fvOptions per region. If two sources target the same region (e.g.
    joule + chemical both on cathode), both source BLOCKS must appear in
    that single file. Silent loss of a block here would silently drop a
    heat source from the simulation.
    """
    by_region = defaultdict(list)
    for s in sources:
        by_region[s['region']].append(s)

    written = []
    for region, srcs in by_region.items():
        fvopt_path = base_dir / 'constant' / region / 'fvOptions'
        fvopt_path.parent.mkdir(parents=True, exist_ok=True)

        with open(fvopt_path, 'w') as f:
            f.write(FVOPTIONS_HEADER.format(region=region))
            for s in srcs:
                f.write(s['block_text'])
                f.write('\n')
            f.write(FVOPTIONS_FOOTER)
        written.append(fvopt_path)

        for s in srcs:
            # Support both legacy single-table sources (table_filename +
            # table_content) and the T-linear chemical source's paired
            # (table_filenames + table_contents).
            if 'table_filenames' in s:
                for fname, content in zip(s['table_filenames'], s['table_contents']):
                    table_path = base_dir / 'constant' / region / fname
                    with open(table_path, 'w') as f:
                        f.write(content)
                    written.append(table_path)
            else:
                table_path = base_dir / 'constant' / region / s['table_filename']
                with open(table_path, 'w') as f:
                    f.write(s['table_content'])
                written.append(table_path)

    return written


# ===== Entry point ============================================================

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 generate_fvOptions.py <config.yaml> [base_dir]")

    config_path = sys.argv[1]
    base_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('.')

    config = load_config(config_path)
    sources = collect_sources(config)
    written = write_all_sources(sources, base_dir)

    # Summary per region (helps the operator spot a silent missing source)
    by_region = defaultdict(list)
    for s in sources:
        by_region[s['region']].append(s['block_text'].split('\n', 2)[2].split('{', 1)[0].strip()
                                       if False else
                                       # extract source NAME (pyroSource / jouleSource / chemicalSource)
                                       next((line.split('\n', 1)[0].strip()
                                             for line in [s['block_text']] for ln in [line]
                                             if ln), '?'))
    # Simpler readable summary:
    summary = defaultdict(list)
    for s in sources:
        # Grab the source name by parsing the block (the first identifier before '{')
        name = 'unknown'
        for line in s['block_text'].splitlines():
            stripped = line.strip()
            if stripped.endswith('Source') and not stripped.startswith('//'):
                name = stripped
                break
        summary[s['region']].append(name)

    for path in written:
        print(f"Wrote {path}", file=sys.stderr)
    print(f"\nDone: {len(written)} files generated for {len(by_region)} region(s)", file=sys.stderr)
    for region, names in sorted(summary.items()):
        print(f"  {region}: {', '.join(names)}", file=sys.stderr)


if __name__ == '__main__':
    main()
