from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_memory.services.taxonomy_catalog import TaxonomyCatalog  # noqa: E402


def main() -> int:
    catalog = TaxonomyCatalog.load()
    node_counts = Counter(node.node_type for node in catalog.nodes)
    print(
        json.dumps(
            {
                "catalog_version": catalog.manifest.catalog_version,
                "content_sha256": catalog.manifest.content_sha256,
                "nodes": len(catalog.nodes),
                "edges": len(catalog.edges),
                "synonyms": len(catalog.synonyms),
                "packs": len(catalog.packs),
                "state_archetypes": len(catalog.state_archetypes),
                "credential_counts": {
                    "boards": node_counts["certifying_board"],
                    "specialties": node_counts["specialty"],
                    "subspecialties": node_counts["subspecialty"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
