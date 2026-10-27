#!/usr/bin/env python3
"""Write (or rehash) the manifests of the WM-1 baseline entries in entries/wm1/.

    uv run scripts/wm1_manifests.py

Run after changing a baseline's code, then commit: the runner refuses an entry whose files no
longer hash as its manifest says, and a sealed round refuses one committed after its window
opened (forward/wm/entry.py). created_at is kept across rehashes.
"""

from __future__ import annotations

from forward import ROOT
from forward.wm import baselines
from forward.wm.entry import write_manifest

CODE = ["forward/wm/baselines.py"]
ENTRIES = {
    "climatology": (
        ["truth"],
        "past ten years' observed weeks at the same time of year, offsets up to two days",
    ),
    "persistence": (["truth"], "today's anomaly from the diurnal climatology, plus analogue-week residuals"),
    "raw": (["ensembles"], "50 members of the captured multi-model ensemble, equal weight per model"),
    "emos-ecc": (
        ["ensembles", "truth"],
        "EMOS per lead block fit on captures verified before the init, reordered by ECC-Q",
    ),
}


def main():
    for name, (inputs, summary) in ENTRIES.items():
        d = ROOT / "entries" / "wm1" / name
        man = write_manifest(
            d,
            id=f"wm1-{name}",
            family="wm1",
            kind="sampler",
            summary=summary,
            inputs=inputs,
            code=[str((d / "entry.py").relative_to(ROOT)), *CODE],
            weights=None,
            K=baselines.K,
            leads=baselines.LEADS,
            variables=baselines.VARIABLES,
        )
        print(man["id"], {p: h[:12] for p, h in man["code"].items()})


if __name__ == "__main__":
    main()
