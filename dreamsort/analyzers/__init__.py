# analyzers

from .eden import EdenAnalyzer
from .eden_config import cheat_switch, set_enabled
from .recomp import RecompAnalyzer
from .ryujinx import RyujinxAnalyzer

__all__ = ["EdenAnalyzer", "RecompAnalyzer", "RyujinxAnalyzer",
           "cheat_switch", "set_enabled"]
