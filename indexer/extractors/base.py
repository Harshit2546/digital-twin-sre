"""
indexer/extractors/base.py

Abstract base interface for language-specific AST extractors.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path

from indexer.models import SystemTopologyGraph


class BaseLanguageExtractor(ABC):
    """
    Contract for extracting AST symbols, endpoints, calls, and environment
    dependencies from a source code file.
    """

    @abstractmethod
    def extract(
        self,
        file_path: Path,
        code_bytes: bytes,
        workspace_root: Path,
        graph: SystemTopologyGraph,
    ) -> None:
        """
        Parses source code bytes and registers symbols, endpoints,
        and dependency edges into the graph.
        """
        pass
