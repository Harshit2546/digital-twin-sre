"""
Language-specific AST symbol and relationship extractors.
"""

from indexer.extractors.base import BaseLanguageExtractor
from indexer.extractors.python_extractor import PythonExtractor

__all__ = ["BaseLanguageExtractor", "PythonExtractor"]
