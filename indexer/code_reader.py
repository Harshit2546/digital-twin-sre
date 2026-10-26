"""
indexer/code_reader.py

Master code indexer that dispatches files to language-specific extractors
and registers symbols, routes, calls, and environment dependencies into the SystemTopologyGraph.
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Set, Type
import logging

from indexer.extractors.base import BaseLanguageExtractor
from indexer.extractors.python_extractor import PythonExtractor
from indexer.models import SystemTopologyGraph

logger = logging.getLogger(__name__)

# Registry mapping file extensions to extractor classes
EXTRACTOR_REGISTRY: Dict[str, Type[BaseLanguageExtractor]] = {
    ".py": PythonExtractor,
}

IGNORE_DIRS: Set[str] = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "site-packages",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
}


def index_code(workspace_root: Path, graph: SystemTopologyGraph) -> None:
    """
    Recursively scans the workspace for supported source files, runs the appropriate
    language extractor, and populates the in-memory SystemTopologyGraph.
    """
    extractors: Dict[str, BaseLanguageExtractor] = {}

    for file_path in workspace_root.rglob("*"):
        # Skip directories and ignored directory paths
        if not file_path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in file_path.parts):
            continue

        ext = file_path.suffix.lower()
        if ext not in EXTRACTOR_REGISTRY:
            continue

        # Lazy instantiation of extractor
        if ext not in extractors:
            extractors[ext] = EXTRACTOR_REGISTRY[ext]()

        extractor = extractors[ext]
        try:
            code_bytes = file_path.read_bytes()
            extractor.extract(file_path, code_bytes, workspace_root, graph)
        except Exception as e:
            logger.warning("Failed to index source file %s: %s", file_path, e)
