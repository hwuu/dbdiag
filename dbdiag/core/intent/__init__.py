"""意图识别模块

解耦的用户意图识别框架，可用于任何对话系统。
"""

from dbdiag.core.intent.models import UserIntent, QueryType
from dbdiag.core.intent.classifier import IntentClassifier

__all__ = ["UserIntent", "QueryType", "IntentClassifier"]
