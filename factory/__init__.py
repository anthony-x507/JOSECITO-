"""Embedded DIGOS Factory runtime.

This package is intentionally small: it provides the executable Factory
contract that TorreDeControl expects in clean clones.
"""

from .manager import FactoryManager
from .superior import SuperiorAgent

__all__ = ["FactoryManager", "SuperiorAgent"]
