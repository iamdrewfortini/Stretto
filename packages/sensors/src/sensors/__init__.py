# SPDX-License-Identifier: Apache-2.0
"""Humanflow desktop sensors: consent-gated, local-only, counts never content.

The sensor agent imports no sibling package so it can run alone on a
desktop. It samples focus window, idle time and (P1) input/pointer
intensity, derives episodes and attention metrics deterministically,
and streams small events to the local runtime over POST /v1/ingest.
No typed content, no screen pixels and no audio are ever stored or sent.
"""
from .consent import ConsentStore, SOURCES
from .adapters import Adapter, Sample, discover, register, registry
from .episodes import EpisodeBuilder, categorize
from .metrics import MetricsEngine
from .narration import Narrator
from .ingest import IngestClient
from .importer import Importer

__all__ = [
    "ConsentStore", "SOURCES", "Adapter", "Sample", "discover",
    "register", "registry", "EpisodeBuilder", "categorize",
    "MetricsEngine", "Narrator", "IngestClient", "Importer",
]
