"""GAR2: Graph-Augmented Reasoning v2

基于观察的诊断推理引擎。

核心概念：
- Observation: 用户观察，可与标准现象匹配
- Symptom: 症状，观察列表的集合
- 图传播: 观察 → 现象 → 根因，计算置信度
"""

from dbdiag.core.gar2.models import (
    Observation,
    Symptom,
    HypothesisV2,
    SessionStateV2,
)
from dbdiag.core.gar2.input_analyzer import InputAnalyzer, SymptomDelta
from dbdiag.core.gar2.observation_matcher import ObservationMatcher
from dbdiag.core.gar2.confidence_calculator import ConfidenceCalculator
from dbdiag.core.gar2.dialogue_manager import GAR2DialogueManager

__all__ = [
    "Observation",
    "Symptom",
    "HypothesisV2",
    "SessionStateV2",
    "InputAnalyzer",
    "SymptomDelta",
    "ObservationMatcher",
    "ConfidenceCalculator",
    "GAR2DialogueManager",
]
