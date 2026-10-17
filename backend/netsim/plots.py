"""One matplotlib style for every figure: PDF (vector, for the paper) and PNG, colour-blind safe palette (Okabe-Ito)."""
from __future__ import annotations

from pathlib import Path

OKABE_ITO = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt_
    plt_.rcParams.update({
        "font.size": 9, "axes.titlesize": 9, "axes.labelsize": 9, "legend.fontsize": 8, "figure.dpi": 150,
        "axes.prop_cycle": matplotlib.cycler(color=OKABE_ITO), "axes.spines.top": False, "axes.spines.right": False,
        "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.bbox": "tight", "axes.grid": True, "grid.alpha": 0.25,
    })
    return plt_


def save(fig, outdir: str | Path, name: str) -> list[str]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("pdf", "png"):
        p = out / f"{name}.{ext}"
        fig.savefig(p)
        paths.append(p.name)
    plt().close(fig)
    return paths


def errorbar(ax, x, ci_list, label=None, pct=True, marker=0, **kw):
    """Line with CI whiskers; ci_list = [{"est","lo","hi"}...]."""
    k = 100.0 if pct else 1.0
    y = [c["est"] * k for c in ci_list]
    lo = [(c["est"] - c["lo"]) * k for c in ci_list]
    hi = [(c["hi"] - c["est"]) * k for c in ci_list]
    ax.errorbar(x, y, yerr=[lo, hi], marker=MARKERS[marker % len(MARKERS)], capsize=2, linewidth=1.2, markersize=4, label=label, **kw)
