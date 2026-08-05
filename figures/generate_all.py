"""Generate F1-F8 figures for the thermal-battery-cfd manuscript from frozen data.

All input JSONs are in ../data/extractions/ (this repo):
  phase8_v17_ultrafine.json  (Fig 2 anchor values)
  phase8_v14.json            (Fig 3b axial peak-time profile)
  F7_tmin_trajectories.json  (Fig 7 real T_min traces from VTK)
  Frozen numbers hand-transcribed into this script for Figs 1, 4-6, 8
  (all values match the corresponding JSON extractions or the paper's frozen
  tables; see cited docstrings and the README figure-reproduction map).

Colour-blind-safe palette (Wong 2011). Vector PDF output. Consistent fonts.

Usage:  python3 generate_all.py
"""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrow

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE

# Wong palette
CB_BLUE   = "#0072B2"
CB_ORANGE = "#E69F00"
CB_GREEN  = "#009E73"
CB_RED    = "#D55E00"
CB_PURPLE = "#CC79A7"
CB_YELLOW = "#F0E442"
CB_GREY   = "#666666"

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.labelsize": 9,
    "axes.titlesize": 10,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "pdf.fonttype": 42,   # embed as truetype (Elsevier compatible)
    "ps.fonttype": 42,
})


def fig1_geometry():
    """F1: Reference cell geometry + unit cell + wedge decomposition."""
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.2), gridspec_kw={"width_ratios": [1.2, 1.0]})

    # Left: axial layout
    ax = axes[0]
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 119.1)
    ax.set_aspect(0.06)

    # Layer stacking (bottom-to-top, thicknesses in mm)
    layers = [
        ("case (SS)",       4.0,   CB_GREY),
        ("insulator A",    13.0,   "#B87333"),
        ("end region",      8.1,   "#FFB380"),
        ("13 unit cells",  68.9,   "#77A5D1"),
        ("end region",      8.1,   "#FFB380"),
        ("insulator A",    13.0,   "#B87333"),
        ("case (SS)",       4.0,   CB_GREY),
    ]
    y = 0
    for name, dz, col in layers:
        rect = Rectangle((2, y), 6, dz, facecolor=col, edgecolor="black", lw=0.5)
        ax.add_patch(rect)
        ax.text(9, y + dz/2, f"{name}\n{dz:.1f} mm", va="center", ha="left", fontsize=7)
        y += dz
    ax.axvline(2, color="black", lw=1)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 119.1)
    ax.set_xticks([])
    ax.set_yticks([0, 25.1, 94.0, 119.1])
    ax.set_yticklabels(["0", "25.1", "94.0", "119.1"])
    ax.set_ylabel("axial position x (mm)")
    ax.set_title("(a) Axial layout, 119.1 mm envelope")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)

    # Right: unit cell breakdown + wedge
    ax = axes[1]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.5)
    ax.set_aspect(1.0)

    # Unit cell layers (5.3 mm total)
    uc_layers = [
        ("HP 0.9",       0.9, "#FF7043"),
        ("cathode 1.6",  1.6, CB_ORANGE),
        ("elec 0.6",     0.6, CB_BLUE),
        ("anode 1.1",    1.1, CB_GREEN),
        ("coll 0.2",     0.2, CB_GREY),
        ("HP 0.9",       0.9, "#FF7043"),
    ]
    y = 0
    for name, dz, col in uc_layers:
        rect = Rectangle((1, y), 3, dz, facecolor=col, edgecolor="black", lw=0.5)
        ax.add_patch(rect)
        ax.text(4.3, y + dz/2, name, va="center", fontsize=7)
        y += dz
    # Wedge annotation
    ax.annotate("5$^\\circ$ wedge\n= 1/72 of full\nannulus",
                xy=(1, 2.65), xytext=(6.5, 2.65), fontsize=8, ha="center",
                arrowprops=dict(arrowstyle="->", lw=0.8, color=CB_RED))
    ax.set_xticks([])
    ax.set_yticks([0, 5.3])
    ax.set_yticklabels(["0", "5.3"])
    ax.set_ylabel("axial (mm within unit cell)")
    ax.set_title("(b) Unit cell + wedge decomposition")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT / "F1_geometry.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F1_geometry.pdf")


def fig2_cell6_components():
    """F2: Cell-6 component transients through the pyrotechnic burn.

    Data source: phase8_v17_ultrafine.json (WI=0.005 rerun, frozen at v1.7 tag).
    Loaded from data/phase8_v17_ultrafine.json (copied verbatim from thesis repo).
    """
    # Load from JSON to avoid transcription drift
    import json as _json
    json_path = DATA / "phase8_v17_ultrafine.json"
    if not json_path.exists():
        # Copy from thesis repo tag
        import shutil
        src = Path("../data/extractions/phase8_v17_ultrafine.json")
        if src.exists():
            shutil.copy(src, json_path)
    with open(json_path) as f:
        _v17 = _json.load(f)

    # Frozen v1.7 tag: phase8_v17_ultrafine.json (schema: at_t_0p42 keys)
    at_042 = _v17["at_t_0p42"]
    hp_042_mean = at_042["HP_LOWx_mean_K"]
    elec_042_mean = at_042["electrolyte_c6_mean_K"]
    # Face-resolved values come from phase8_v16_c6.json (v1.6 basis, also frozen at v1.7 tag).
    # Load them separately.
    v16_path = DATA / "phase8_v16_c6.json"
    if not v16_path.exists():
        import shutil
        shutil.copy(Path("../data/extractions/phase8_v16_c6.json"), v16_path)
    with open(v16_path) as f:
        _v16 = _json.load(f)
    m = _v16["measurements_at_t_0p42s"]
    elec_042_cathode = m["cell_6_electrolyte_cathode_side_face"]["T_mean_K"]
    elec_042_anode_04 = m["cell_6_electrolyte_anode_side_face_at_t0p4"]["T_mean_K"]

    # Neighboring-time samples from the same run (frozen extraction, tabulated at v1.7)
    # These are used to show the trajectory shape; the t=0.42 anchors above are the
    # authoritative direct measurements against Jeong.
    t = np.array([0.30, 0.35, 0.40, 0.41, 0.42, 0.425, 0.43, 0.45, 0.50, 0.55, 0.60, 0.80])
    # Interpolate/anchor to the JSON's t=0.42 mean values for HP and electrolyte
    hp_mean   = np.array([1055.18, 1151.93, 1245.43, 1261.98, hp_042_mean, 1270.03, 1260.54, 1226.78, 1164.26, 1123.30, 1089.52, 1010.03])
    elec_mean = np.array([357.52, 384.55, 415.03, 421.66, elec_042_mean, 431.85, 435.32, 449.48, 486.37, 523.81, 543.36, 616.89])
    elec_cathode_face = np.array([np.nan, np.nan, 364.31, np.nan, elec_042_cathode, np.nan, np.nan, 388.08, np.nan, np.nan, np.nan, np.nan])
    elec_anode_face   = np.array([np.nan, np.nan, elec_042_anode_04, np.nan, 531.49, np.nan, np.nan, 563.03, np.nan, np.nan, np.nan, np.nan])

    fig, ax = plt.subplots(figsize=(6.4, 4.0))

    ax.plot(t, hp_mean, "o-", color=CB_RED, label="HP cell-6 low-x (ours, mean)", lw=1.8, markersize=4)
    ax.plot(t, elec_mean, "s-", color=CB_BLUE, label="Electrolyte cell-6 (ours, mean)", lw=1.8, markersize=4)
    ax.plot(t, elec_anode_face, "^--", color="#66C2A5", label="Electrolyte anode-side face", lw=1.0, markersize=4)
    ax.plot(t, elec_cathode_face, "v--", color="#FC8D62", label="Electrolyte cathode-side face", lw=1.0, markersize=4)

    # Jeong reference annotations
    ax.axvline(0.421, color=CB_GREY, ls=":", lw=1.0)
    ax.text(0.421, 100, "burn end\n0.421 s", ha="center", va="bottom", fontsize=7, color=CB_GREY)
    ax.plot(0.42, 1320, "*", color="black", markersize=14, label="Jeong Fig 2 HP peak (1320 K)")
    ax.plot(0.42, 420, "P", color=CB_GREY, markersize=10, label="Jeong Fig 2 elec (~420 K)")

    ax.set_xlim(0.28, 0.85)
    ax.set_ylim(0, 1600)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("temperature (K)")
    ax.set_title("Cell-6 component transient through pyrotechnic burn")
    ax.legend(loc="upper right", fontsize=7, framealpha=0.95)
    ax.grid(True, alpha=0.3)

    # Adiabatic bound annotation
    ax.axhline(1973, color=CB_RED, ls=":", lw=0.7, alpha=0.6)
    ax.text(0.82, 1985, "$T_{ad}$ = 1973 K", fontsize=7, ha="right", va="bottom", color=CB_RED, alpha=0.8)

    plt.tight_layout()
    plt.savefig(OUT / "F2_cell6_components.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F2_cell6_components.pdf")


def fig3_axial_tpeak():
    """F3: (a) axial electrolyte trajectories vs Jeong Fig 3a; (b) t_peak vs cell + asymmetry."""
    # From phase8_v14.json: t_peak profile for all 13 cells
    # Copied here as constants for figure stability
    x_c_mm = [22.618, 27.963, 33.307, 38.651, 43.996, 49.340, 54.684,
              60.028, 65.372, 70.717, 76.061, 81.405, 86.749]
    t_peak = [30, 92, 148, 202, 260, 314, 330, 284, 214, 168, 126, 80, 26]
    T_peak = [905.86, 848.50, 826.79, 815.40, 808.89, 805.80, 804.63, 805.24,
              808.88, 815.92, 827.25, 848.02, 904.82]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 3.6))

    # (a) T_peak vs axial position (simplified: representative envelope)
    # Use synthetic T(t) trajectories keyed to t_peak and T_peak — for a schematic overlay
    # Since we don't have per-cell t-series here (would need full trajectory extraction),
    # plot the peak points as (t_peak, T_peak) markers labelled by cell.
    for cn, (xm, tp, Tp) in enumerate(zip(x_c_mm, t_peak, T_peak)):
        marker = "o"
        col = CB_BLUE
        if cn in (0, 12):
            col = CB_RED
        elif cn in (3, 9):
            col = CB_ORANGE
        elif cn == 6:
            col = CB_GREEN
        ax1.plot(tp, Tp, marker, color=col, markersize=7)
        ax1.annotate(f"c{cn}", (tp, Tp), xytext=(4, 4), textcoords="offset points", fontsize=7)

    # Jeong Point references
    ax1.axvline(35, color=CB_GREY, ls=":", lw=0.8)
    ax1.axvline(80, color=CB_GREY, ls=":", lw=0.8)
    ax1.axvline(150, color=CB_GREY, ls=":", lw=0.8)
    ax1.axvline(200, color=CB_GREY, ls=":", lw=0.8)
    for x, lbl in [(35, "Pt 1/7"), (80, "Pt 2/6"), (150, "Pt 3"), (200, "Pt 4")]:
        ax1.text(x, 920, lbl, ha="center", va="bottom", fontsize=7, color=CB_GREY)

    ax1.set_xlim(0, 380)
    ax1.set_ylim(770, 940)
    ax1.set_xlabel("$t_{\\rm peak}$ (s, late-argmax gate $t > 20$ s)")
    ax1.set_ylabel("$T_{\\rm peak}$ at cell (K)")
    ax1.set_title("(a) Electrolyte peak times per cell")
    ax1.grid(True, alpha=0.3)

    # (b) Peak time profile + asymmetry
    cell_idx = list(range(13))
    ax2.plot(cell_idx, t_peak, "o-", color=CB_BLUE, lw=1.5)
    for cn, tp in enumerate(t_peak):
        ax2.annotate(f"c{cn}", (cn, tp), xytext=(0, 4), textcoords="offset points",
                     fontsize=6, ha="center")

    # Highlight c4/c8 asymmetry maximum
    ax2.plot([4, 8], [260, 214], "s", color=CB_RED, markersize=10, mec="black", mew=1.2)
    ax2.annotate("|$\\Delta t$| = 46 s max\n(c4/c8 pair)",
                 xy=(6, 240), xytext=(6, 130), ha="center", fontsize=8,
                 arrowprops=dict(arrowstyle="->", lw=0.8, color=CB_RED))

    ax2.axvline(6, color=CB_GREEN, ls=":", lw=0.8)
    ax2.text(6, 20, "c6\ncentre", ha="center", fontsize=7, color=CB_GREEN)

    ax2.set_xlabel("cell index (0 = low-x = Point 1)")
    ax2.set_ylabel("$t_{\\rm peak}$ (s)")
    ax2.set_title("(b) Peak-time profile: c4/c8 asymmetry")
    ax2.set_ylim(0, 380)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "F3_axial_tpeak.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F3_axial_tpeak.pdf")


def fig4_operability_envelope():
    """F4: HEADLINE. M_peak vs T_amb with buffer band + both thresholds + regions."""
    # Values from Table tab:mpeak (frozen v1.7 report §5a / §4)
    T_amb = np.array([-40, -20, 0, 26.85, 50])
    M_peak = np.array([713.57, 728.18, 745.19, 800.27, 832.35])
    alpha  = np.array([0.4140, 0.9010, 1.000, 1.000, 1.000])

    # Thresholds (v1.7 published)
    T_strict = -16.86; T_strict_err = 1.4
    T_melt   = -36.47; T_melt_err   = 1.55
    M_strict = 730.85; M_melt = 716.15

    fig, ax = plt.subplots(figsize=(6.8, 4.2))

    # Buffer band shading
    ax.axhspan(701.15, 731.15, color=CB_YELLOW, alpha=0.35, label="apparent-$c_p$ buffer band")

    # Threshold horizontals
    ax.axhline(M_strict, color=CB_RED, ls="--", lw=1.2, label=f"strict-$\\alpha$: $M_{{\\rm peak}}$ = {M_strict} K")
    ax.axhline(M_melt,   color=CB_BLUE, ls="--", lw=1.2, label=f"melt-basis: $M_{{\\rm peak}}$ = {M_melt} K")

    # M_peak points and curve
    ax.plot(T_amb, M_peak, "o-", color="black", lw=1.8, markersize=9,
            markerfacecolor=CB_ORANGE, markeredgecolor="black", label="measured $M_{\\rm peak}$ (5 pts)")
    for T, M in zip(T_amb, M_peak):
        ax.annotate(f"{M:.1f}", (T, M), xytext=(0, 8), textcoords="offset points",
                    fontsize=7, ha="center")

    # Thresholds vertical with error bars
    ax.errorbar([T_strict], [M_strict], xerr=T_strict_err, color=CB_RED,
                fmt="D", markersize=8, capsize=5, lw=2, label=f"$T^*_{{\\rm strict}}$ = {T_strict}$\\pm${T_strict_err}$^\\circ$C")
    ax.errorbar([T_melt], [M_melt], xerr=T_melt_err, color=CB_BLUE,
                fmt="D", markersize=8, capsize=5, lw=2, label=f"$T^*_{{\\rm melt}}$ = {T_melt}$\\pm${T_melt_err}$^\\circ$C")

    # Region shading
    ax.axvspan(-50, T_melt - T_melt_err, ymin=0, ymax=1, color="#F5B7B1", alpha=0.15, label=None)
    ax.axvspan(T_melt + T_melt_err, T_strict - T_strict_err, ymin=0, ymax=1, color="#F9E79F", alpha=0.15, label=None)
    ax.axvspan(T_strict + T_strict_err, 55, ymin=0, ymax=1, color="#A9DFBF", alpha=0.15, label=None)

    ax.text(-45, 800, "FAILED", fontsize=10, ha="left", va="center",
            bbox=dict(facecolor="#F5B7B1", alpha=0.7, edgecolor="none"))
    ax.text(-25, 800, "DEGRADED\nwindow", fontsize=10, ha="center", va="center",
            bbox=dict(facecolor="#F9E79F", alpha=0.7, edgecolor="none"))
    ax.text(35, 800, "FULLY\nACTIVATED", fontsize=10, ha="center", va="center",
            bbox=dict(facecolor="#A9DFBF", alpha=0.7, edgecolor="none"))

    ax.set_xlim(-50, 55)
    ax.set_ylim(700, 850)
    ax.set_xlabel("Ambient temperature $T_{\\rm amb}$ ($^\\circ$C)")
    ax.set_ylabel("$M_{\\rm peak}$ = max$_t$ $T_{\\rm min,elec}$ (K)")
    ax.set_title("Operability envelope: $M_{\\rm peak}$($T_{\\rm amb}$), two thresholds, three regions")
    ax.legend(loc="lower right", fontsize=7, framealpha=0.95)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "F4_operability_envelope.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F4_operability_envelope.pdf")


def fig5_derating():
    """F5: three-basis derating for Case 3-1."""
    # Values from Table tab:derating (frozen v1.7 report §5b)
    T_amb = np.array([-20, 0, 26.85])
    t_strict = np.array([np.nan, 323.51, 651.22])
    t_melt   = np.array([316.83, 426.20, 852.28])
    t_interval = t_strict - np.where(np.isnan(t_strict), np.nan, np.array([316.83, 426.20, 852.28]))

    fig, ax = plt.subplots(figsize=(6.4, 3.8))

    ax.plot(T_amb, t_strict, "D-", color=CB_RED, lw=1.8, markersize=9, label="strict-$\\alpha$ ($T{=}730.85$ K)")
    ax.plot(T_amb, t_melt, "s-", color=CB_BLUE, lw=1.8, markersize=9, label="melt ($T{=}716.15$ K)")

    # Annotate values
    for T, ts, tm in zip(T_amb, t_strict, t_melt):
        if not np.isnan(ts):
            ax.annotate(f"{ts:.1f}", (T, ts), xytext=(0, -14), textcoords="offset points",
                        fontsize=7, ha="center", color=CB_RED)
        ax.annotate(f"{tm:.1f}", (T, tm), xytext=(0, 8), textcoords="offset points",
                    fontsize=7, ha="center", color=CB_BLUE)

    # Fault-condition marker for -20 strict
    ax.text(-20, 780, "STRICT FAULT\nnever activates", ha="center", va="center", fontsize=8,
            color=CB_RED, bbox=dict(facecolor="#F5B7B1", alpha=0.7, edgecolor=CB_RED))

    # Slope annotations
    ax.text(13, 500, "strict slope\n+12.20 s/$^\\circ$C\n(0→+26.85)", fontsize=7, color=CB_RED, ha="center")
    ax.text(-10, 380, "melt cold\n+5.47", fontsize=7, color=CB_BLUE, ha="center")
    ax.text(15, 700, "melt warm\n+15.87 s/$^\\circ$C", fontsize=7, color=CB_BLUE, ha="center")

    ax.set_xlim(-30, 40)
    ax.set_ylim(0, 950)
    ax.set_xlabel("Ambient temperature $T_{\\rm amb}$ ($^\\circ$C)")
    ax.set_ylabel("Crossing time (s post-activation)")
    ax.set_title("Case 3-1 discharge derating on three bases (family-pure, never joined)")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.95)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "F5_derating.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F5_derating.pdf")


def fig6_rescue_config():
    """F6: rescue depth-restricted config vs Jeong Fig 4 arrangement (schematic)."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.2, 4.0))

    # Left: our depth-restricted
    ax = ax1
    ax.set_xlim(0, 10); ax.set_ylim(0, 100); ax.set_aspect("equal")
    # Stack (simplified)
    ax.add_patch(Rectangle((2, 20), 6, 60, facecolor="#77A5D1", edgecolor="black"))
    ax.text(5, 50, "13 unit cells\n(stack)", ha="center", va="center", fontsize=9)
    # End regions (top, bottom)
    ax.add_patch(Rectangle((2, 12), 6, 8, facecolor="#FFB380", edgecolor="black"))
    ax.text(5, 16, "end region", ha="center", fontsize=7)
    ax.add_patch(Rectangle((2, 80), 6, 8, facecolor="#FFB380", edgecolor="black"))
    ax.text(5, 84, "end region", ha="center", fontsize=7)
    # Insulator A caps (13 mm)
    ax.add_patch(Rectangle((2, 0), 6, 12, facecolor="#B87333", edgecolor="black"))
    ax.add_patch(Rectangle((2, 88), 6, 12, facecolor="#B87333", edgecolor="black"))
    ax.text(5, 6, "insulator A", ha="center", fontsize=7)
    ax.text(5, 94, "insulator A", ha="center", fontsize=7)
    # Rescue slab (dark shading) at stack-facing edge (3.6 mm depth)
    ax.add_patch(Rectangle((2, 8.4), 6, 3.6, facecolor=CB_RED, edgecolor="black", alpha=0.85))
    ax.add_patch(Rectangle((2, 88), 6, 3.6, facecolor=CB_RED, edgecolor="black", alpha=0.85))
    ax.text(9.2, 10.2, "rescue slab\n3.6 mm\n1087 J/wedge", va="center", fontsize=7)
    ax.axis("off")
    ax.set_title("(a) Ours: depth-restricted rescue")

    # Right: Jeong Fig 4a schematic (additional pellet pair on top and bottom stacks)
    ax = ax2
    ax.set_xlim(0, 10); ax.set_ylim(0, 100); ax.set_aspect("equal")
    ax.add_patch(Rectangle((2, 20), 6, 60, facecolor="#77A5D1", edgecolor="black"))
    ax.text(5, 50, "13 unit cells", ha="center", fontsize=9)
    ax.add_patch(Rectangle((2, 12), 6, 8, facecolor="#FFB380", edgecolor="black"))
    ax.add_patch(Rectangle((2, 80), 6, 8, facecolor="#FFB380", edgecolor="black"))
    # Additional pellets (dark) IN the end region
    ax.add_patch(Rectangle((2, 13), 6, 2, facecolor=CB_RED, edgecolor="black"))
    ax.add_patch(Rectangle((2, 85), 6, 2, facecolor=CB_RED, edgecolor="black"))
    ax.add_patch(Rectangle((2, 0), 6, 12, facecolor="#B87333", edgecolor="black"))
    ax.add_patch(Rectangle((2, 88), 6, 12, facecolor="#B87333", edgecolor="black"))
    ax.text(9.2, 14, "add'l pellet\n(Jeong Fig 4a)", va="center", fontsize=7)
    ax.axis("off")
    ax.set_title("(b) Jeong Fig 4a arrangement (context)")

    plt.tight_layout()
    plt.savefig(OUT / "F6_rescue_config.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F6_rescue_config.pdf")


def fig7_rescue_tmin():
    """F7: T_min(t) for rescue trajectories, REAL data from VTK extraction.

    Data source: F7_tmin_trajectories.json, extracted from the frozen VTK
    outputs of three runs (7A baseline, 7C DEPTH, D2). Full-fidelity T_min
    trajectories at the solver's native cadence. Not a schematic.
    """
    import json as _json
    json_path = DATA / "F7_tmin_trajectories.json"
    with open(json_path) as f:
        data = _json.load(f)

    fig, ax = plt.subplots(figsize=(6.4, 4.0))

    # Colours and labels per case
    case_style = {
        "phase7a_t_neg40":              (CB_GREY,   1.5, "7A baseline (no rescue, no discharge)"),
        "phase7c_rescue_depth_t_neg40": (CB_GREEN,  1.8, "7C DEPTH (rescue, discharge-OFF)"),
        "phase7c_depth_disch_t_neg40":  (CB_PURPLE, 1.8, "D2 (rescue with Case-1 discharge)"),
    }

    for case, (col, lw, lbl) in case_style.items():
        if case not in data:
            continue
        t = np.array(data[case]["t"])
        Tmin = np.array(data[case]["T_min"])
        ax.plot(t, Tmin, "-", color=col, lw=lw, label=lbl)

    ax.axhline(730.85, color=CB_RED, ls="--", lw=1.0, label="strict-$\\alpha$ 730.85 K")
    ax.axhline(716.15, color=CB_BLUE, ls="--", lw=1.0, label="melt 716.15 K")

    # Melt crossings for 7C DEPTH (from v1.7 §6/§8_d1)
    ax.axvline(268.71, color=CB_GREEN, ls=":", lw=0.7, alpha=0.7)
    ax.axvline(522.81, color=CB_GREEN, ls=":", lw=0.7, alpha=0.7)
    ax.annotate("melt up 268.7 s", (268.71, 716.15), xytext=(-45, -22), textcoords="offset points",
                fontsize=7, color=CB_GREEN,
                arrowprops=dict(arrowstyle="->", lw=0.5, color=CB_GREEN))
    ax.annotate("melt dn 522.8 s", (522.81, 716.15), xytext=(25, -22), textcoords="offset points",
                fontsize=7, color=CB_GREEN,
                arrowprops=dict(arrowstyle="->", lw=0.5, color=CB_GREEN))

    # M_peak annotations
    ax.annotate("$M_{\\rm peak}$ = 727.33 K", xy=(434, 727.33), xytext=(490, 745),
                fontsize=7, color=CB_GREEN,
                arrowprops=dict(arrowstyle="->", lw=0.5, color=CB_GREEN))
    ax.annotate("$M_{\\rm peak}$ = 726.23 K", xy=(434, 726.23), xytext=(490, 703),
                fontsize=7, color=CB_PURPLE,
                arrowprops=dict(arrowstyle="->", lw=0.5, color=CB_PURPLE))
    ax.annotate("$M_{\\rm peak}$ = 713.57 K\n(at t=270 s)", xy=(270, 713.57), xytext=(90, 630),
                fontsize=7, color=CB_GREY,
                arrowprops=dict(arrowstyle="->", lw=0.5, color=CB_GREY))

    ax.set_xlim(0, 700)
    ax.set_ylim(230, 780)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("$T_{\\min}$ (K) on coldest electrolyte cell")
    ax.set_title("Rescue $T_{\\min}(t)$ at $T_{\\rm amb} = -40$ $^\\circ$C (real VTK traces)")
    ax.legend(loc="lower right", fontsize=7, framealpha=0.95)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT / "F7_rescue_tmin.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F7_rescue_tmin.pdf (REAL trajectories extracted from VTK)")


def fig8_energy_split():
    """F8: rescue energy split (34/35/23/8 bar chart)."""
    # From Table tab:rescue_split (v1.7 §6/§8_c)
    labels = ["Stack\n(useful)", "Case-side loss\n(outward)", "Ins A cap\n(retained)", "Ledger residual\n(coupling)"]
    values = [374.33, 384.08, 246.12, 82.50]
    pct = [34.4, 35.3, 22.6, 7.6]
    cols = [CB_GREEN, CB_RED, CB_ORANGE, CB_GREY]

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    y = np.arange(len(labels))
    bars = ax.barh(y, values, color=cols, edgecolor="black", lw=0.8)

    for i, (v, p) in enumerate(zip(values, pct)):
        ax.text(v + 15, i, f"{v:.1f} J\n({p}%)", va="center", fontsize=8)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, 500)
    ax.set_xlabel("energy delivered (J per wedge, from 1087 J deposit)")
    ax.set_title("Rescue energy destination at $T_{\\rm amb} = -40$ $^\\circ$C, discharge-OFF")
    ax.grid(True, axis="x", alpha=0.3)
    ax.invert_yaxis()

    # Total closure annotation
    ax.text(250, 3.7, "$\\Sigma$ = 1086.13 J (99.9\\% closure vs 1087 J analytic)",
            ha="center", fontsize=7, style="italic")

    plt.tight_layout()
    plt.savefig(OUT / "F8_energy_split.pdf", bbox_inches="tight")
    plt.close(fig)
    print("F8_energy_split.pdf")


if __name__ == "__main__":
    fig1_geometry()
    fig2_cell6_components()
    fig3_axial_tpeak()
    fig4_operability_envelope()
    fig5_derating()
    fig6_rescue_config()
    fig7_rescue_tmin()
    fig8_energy_split()
    print("\nAll 8 figures generated in figures/*.pdf")
