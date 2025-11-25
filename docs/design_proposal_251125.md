# 设计提案：用户意图识别与复杂输入处理

**日期**: 2025-11-25
**状态**: 提案阶段
**优先级**: Phase 1 高优先级，Phase 2-3 中低优先级

---

## 背景

当前系统已经实现了基本的步骤追踪和事实提取，但在处理复杂用户输入时存在局限性。真实场景中，用户可能会：
- 同时陈述多个事实
- 向系统提问（"检查了什么？"、"有什么结论？"）
- 建议诊断方向（"会不会是磁盘问题？"）
- 推翻之前的检查结果（"之前说错了，实际是..."）
- 在一句话中混合多种意图

本提案旨在设计一套完整的用户意图识别和分段处理机制。

---

## 复杂场景分析

### 1. 多个事实陈述

**场景示例**：
```
"IO 正常，CPU 使用率 95%，内存还有 20% 可用"
```

**当前实现**: ✅ 已支持
- `_extract_facts_from_user_message()` 返回 `List[ConfirmedFact]`
- LLM 提取为 JSON 数组：`["IO 正常", "CPU 使用率 95%", "内存 20% 可用"]`
- 每个事实独立评估对各假设的影响

**结论**: 无需改进

---

### 2. 用户提问（回顾型）

**场景示例**：
```
"现在咱们都检查了什么了？"
"根据现有的检查结果，可以有什么结论？"
"还有哪些假设没排除？"
```

**当前问题**: ❌ 需要改进
- 系统将其识别为"非执行反馈"（正确）
- 但系统仍会推荐下一步，**无法回答用户的问题**

**改进方案**：
1. 识别用户意图为 `query`（查询）
2. 生成总结响应，不推荐新步骤
3. 响应包含：
   - 已完成的检查列表
   - 当前活跃的假设及置信度
   - 已排除的假设
   - 下一步建议（可选）

**响应示例**：
```markdown
**已完成的检查：**
✓ 检查 IO 等待 → 正常
✓ 检查 CPU 使用率 → 95%（异常）

**当前假设：**
1. 并行查询未使用并行执行 (置信度: 68%)
2. 频繁更新导致索引碎片 (置信度: 42%)
3. 统计信息不准确 (置信度: 35%)

**初步结论：**
根据 IO 正常但 CPU 使用率异常，更可能是计算密集型问题而非 IO 瓶颈。
建议继续检查并行查询配置。
```

---

### 3. 混合输入

**场景示例**：
```
"IO 正常，会不会是磁盘的问题？之前检查了什么？"
```

**包含的意图**：
- **事实陈述**: "IO 正常"
- **方向建议**: "会不会是磁盘的问题"
- **回顾查询**: "之前检查了什么"

**处理逻辑**：
1. **提取事实** → 更新 `confirmed_facts`
2. **识别建议** → 临时提升"磁盘相关假设"的权重
3. **回答问题** → 在响应中添加"已检查步骤摘要"
4. **综合生成** → 一个响应包含多个部分

**响应示例**：
```markdown
根据您的反馈"IO 正常"，我们已排除了 IO 瓶颈的可能性。

关于磁盘问题，我确实注意到有"磁盘空间不足"的假设（当前置信度 32%）。
让我重点检查这个方向。

**已完成的检查：**
✓ 检查 IO 等待 → 正常
✓ 检查 CPU 使用率 → 95%（异常）

**下一步建议：**
检查磁盘空间使用情况...
```

---

### 4. 推翻之前的结果

**场景示例**：
```
"之前说 IO 正常是我看错了，其实 IO 等待很高"
"抱歉，刚才那个 CPU 数据不对，应该是 50%"
```

**当前问题**: ❌ 严重问题
- 没有机制修正已确认的事实
- 错误的事实会持续影响假设评估
- 可能导致错误的诊断方向

**改进方案**：

**检测修正性陈述**：
```python
def _detect_correction(self, user_message: str, session: SessionState) -> List[Correction]:
    """
    使用 LLM 识别修正模式：
    - "之前说X，其实是Y"
    - "刚才那个数据错了，应该是Z"
    - "我看错了，实际上..."
    - "抱歉，X不对"

    Returns:
        [{"fact_to_remove": "IO 正常", "new_fact": "IO 等待很高"}]
    """
```

**处理流程**：
1. 识别被修正的事实（与历史 `confirmed_facts` 匹配）
2. 从 `confirmed_facts` 中移除旧事实
3. 添加新事实
4. **重新评估所有假设**（因为基础数据变了）
5. 可选：移除某些 `executed_steps`（如果该步骤需要重新执行）
6. 在响应中确认修正：
   ```
   好的，我已更新信息：将"IO 正常"修正为"IO 等待很高"。
   基于这个新信息，让我重新评估假设...
   ```

**数据模型**：
```python
class Correction(BaseModel):
    """修正信息"""
    original_fact: str           # 原始陈述
    corrected_fact: str          # 修正后的陈述
    correction_reason: str       # 修正原因（可选）
    timestamp: datetime
```

---

### 5. 用户建议方向

**场景示例**：
```
"会不会是磁盘的问题？"
"我怀疑是网络配置的问题"
"这个表现像是死锁"
```

**当前处理**: ⚠️ 部分支持
- 这些会被提取为"事实"（不够准确）
- 没有区分"用户观察的事实" vs "用户的主观猜测"

**改进方案**：

**识别用户建议**：
```python
def _extract_user_suggestion(self, user_message: str) -> List[str]:
    """
    识别模式：
    - "会不会是...?"
    - "我觉得可能是..."
    - "怀疑是..."
    - "看起来像是..."
    - "应该是...吧"
    """
```

**处理策略**：
1. **不直接添加为事实**（避免主观猜测污染事实库）
2. **临时提升相关假设的优先级**：
   - 在当前轮次给予 +0.1 ~ +0.2 的置信度加成
   - 加成在下一轮重新评估时失效
3. **在响应中明确回应**：
   ```
   您提到可能是磁盘问题。确实，我也注意到了"磁盘空间不足"这个假设
   （当前置信度 32% + 用户建议加成 15% = 47%）。
   让我们重点检查一下磁盘相关的指标...
   ```

**实现细节**：
```python
class Hypothesis(BaseModel):
    root_cause: str
    confidence: float              # 基础置信度
    user_boost: float = 0.0        # 用户建议的临时加成

    @property
    def effective_confidence(self) -> float:
        """实际置信度（含用户加成）"""
        return min(self.confidence + self.user_boost, 1.0)
```

---

## 完整设计方案

### 阶段 1：意图识别（核心）

**数据模型**：
```python
class UserIntent(BaseModel):
    """用户意图分类"""
    intent_type: str  # "feedback" | "query" | "suggestion" | "correction" | "mixed"

    # 各类内容
    facts: List[str] = []           # 陈述的事实
    questions: List[str] = []       # 提出的问题
    suggestions: List[str] = []     # 建议的方向/怀疑
    corrections: List[Dict] = []    # 修正内容

    # 标记
    has_execution_feedback: bool = False      # 是否包含执行反馈
    needs_summary: bool = False               # 是否需要总结响应
    needs_hypothesis_adjustment: bool = False # 是否需要调整假设优先级
```

**LLM Prompt**：
```python
system_prompt = """你是用户意图分析助手。分析用户消息的意图类型。

意图类型：
1. feedback（诊断反馈）：用户报告了诊断步骤的执行结果
   例如："IO 正常"、"CPU 使用率 95%"

2. query（系统查询）：用户询问系统状态或进展
   例如："检查了什么？"、"有什么结论？"

3. suggestion（方向建议）：用户建议或怀疑某个方向
   例如："会不会是磁盘问题？"、"我觉得是网络的原因"

4. correction（修正陈述）：用户修正之前说过的内容
   例如："之前说错了，实际上..."、"刚才那个数据不对"

5. mixed（混合）：包含多种意图

输出格式：JSON
{
  "intent_type": "...",
  "facts": [...],
  "questions": [...],
  "suggestions": [...],
  "corrections": [{"original": "...", "corrected": "..."}],
  "has_execution_feedback": true/false,
  "needs_summary": true/false,
  "needs_hypothesis_adjustment": true/false
}
"""
```

---

### 阶段 2：分段处理流程

**核心逻辑**：
```python
def continue_conversation(self, session_id: str, user_message: str) -> Dict[str, Any]:
    """继续对话（增强版）"""

    # 加载会话
    session = self.session_service.get_session(session_id)

    # 1. 意图识别
    intent = self._classify_user_intent(user_message, session)

    # 2. 处理修正（优先级最高）
    if intent.corrections:
        self._handle_corrections(intent.corrections, session)

    # 3. 提取事实
    if intent.facts:
        new_facts = self._extract_facts(intent.facts, session)
        session.confirmed_facts.extend(new_facts)

    # 4. 标记已执行步骤
    if intent.has_execution_feedback:
        self._mark_executed_steps_from_feedback(user_message, session)

    # 5. 处理用户建议
    if intent.suggestions:
        self._boost_suggested_hypotheses(intent.suggestions, session)

    # 6. 更新假设
    session = self.hypothesis_tracker.update_hypotheses(session)

    # 7. 生成响应
    if intent.needs_summary:
        # 生成总结响应，回答用户问题
        response = self._generate_summary_response(session, intent.questions)
    else:
        # 正常推荐流程
        recommendation = self.recommender.recommend_next_action(session)
        response = self.response_generator.generate_response(session, recommendation)

        # 如果有用户问题，在响应中添加回答
        if intent.questions:
            response["message"] = self._add_answers_to_response(
                response["message"],
                intent.questions,
                session
            )

    # 8. 添加对话历史
    session.dialogue_history.append(DialogueMessage(role="user", content=user_message))
    session.dialogue_history.append(DialogueMessage(role="assistant", content=response["message"]))

    # 9. 保存会话
    self.session_service.update_session(session)

    return response
```

---

### 阶段 3：辅助方法实现

#### 3.1 修正处理

```python
def _handle_corrections(
    self,
    corrections: List[Dict],
    session: SessionState
) -> None:
    """
    处理用户修正

    Args:
        corrections: [{"original": "IO 正常", "corrected": "IO 等待很高"}]
        session: 会话状态
    """
    for correction in corrections:
        original = correction["original"]
        corrected = correction["corrected"]

        # 1. 从 confirmed_facts 中查找并移除旧事实
        removed = False
        for i, fact in enumerate(session.confirmed_facts):
            if self._is_similar_fact(fact.fact, original):
                session.confirmed_facts.pop(i)
                removed = True
                break

        # 2. 添加新事实
        if corrected:
            session.confirmed_facts.append(
                ConfirmedFact(
                    fact=corrected,
                    from_user_input=True,
                    is_correction=True,  # 新增字段
                    corrected_from=original if removed else None
                )
            )

        # 3. 标记需要重新评估
        # （在 update_hypotheses 时会重新计算所有假设）

def _is_similar_fact(self, fact1: str, fact2: str) -> bool:
    """判断两个事实是否相似（用于匹配修正）"""
    # 简单实现：使用 LLM 或文本相似度
    # 复杂实现：考虑语义相似性
    return fact1.lower() in fact2.lower() or fact2.lower() in fact1.lower()
```

#### 3.2 总结响应生成

```python
def _generate_summary_response(
    self,
    session: SessionState,
    questions: List[str]
) -> Dict[str, Any]:
    """
    生成总结响应（回答用户查询）

    Args:
        session: 会话状态
        questions: 用户问题列表

    Returns:
        响应字典
    """
    # 构建总结内容
    summary_parts = []

    # 1. 已完成的检查
    if session.executed_steps:
        summary_parts.append("**已完成的检查：**")
        for step in session.executed_steps:
            summary_parts.append(f"✓ {step.step_id}: {step.result_summary}")

    # 2. 当前假设
    if session.active_hypotheses:
        summary_parts.append("\n**当前假设（按置信度排序）：**")
        for i, hyp in enumerate(session.active_hypotheses, 1):
            summary_parts.append(
                f"{i}. {hyp.root_cause} "
                f"(置信度: {hyp.confidence:.0%})"
            )

    # 3. 已确认事实
    if session.confirmed_facts:
        summary_parts.append("\n**已确认的事实：**")
        for fact in session.confirmed_facts[-5:]:  # 最近5个
            summary_parts.append(f"• {fact.fact}")

    # 4. 使用 LLM 生成自然语言总结
    llm_prompt = f"""基于以下诊断信息，生成一段总结：

{chr(10).join(summary_parts)}

用户问题：{', '.join(questions)}

请用简洁的语言总结当前诊断进展，并回答用户的问题。"""

    summary_text = self.llm_service.generate_simple(
        llm_prompt,
        system_prompt="你是数据库诊断助手，擅长总结诊断进展。"
    )

    return {
        "action": "summary",
        "message": summary_text,
        "summary_data": {
            "executed_steps": len(session.executed_steps),
            "active_hypotheses": len(session.active_hypotheses),
            "confirmed_facts": len(session.confirmed_facts)
        }
    }
```

#### 3.3 假设加成

```python
def _boost_suggested_hypotheses(
    self,
    suggestions: List[str],
    session: SessionState
) -> None:
    """
    根据用户建议临时提升相关假设的优先级

    Args:
        suggestions: 用户建议列表（如 ["磁盘问题", "网络延迟"]）
        session: 会话状态
    """
    # 使用 LLM 匹配用户建议与现有假设
    for suggestion in suggestions:
        for hypothesis in session.active_hypotheses:
            similarity = self._calculate_suggestion_similarity(
                suggestion,
                hypothesis.root_cause
            )

            if similarity > 0.5:  # 相关度阈值
                # 临时加成（在下一轮更新时会重新计算）
                hypothesis.user_boost = min(similarity * 0.2, 0.2)

def _calculate_suggestion_similarity(
    self,
    suggestion: str,
    root_cause: str
) -> float:
    """
    计算用户建议与假设根因的相关度

    使用 LLM 评分 0-1
    """
    prompt = f"""用户建议: {suggestion}
假设根因: {root_cause}

这两者的相关度是多少？（0-1，0表示无关，1表示完全相关）
只输出数字。"""

    try:
        score = float(self.llm_service.generate_simple(prompt))
        return min(max(score, 0.0), 1.0)
    except:
        return 0.0
```

---

## 实施计划

### Phase 1 - 核心功能（高优先级）

**目标**: 解决最关键的用户体验问题

**包含**：
- ✅ 意图识别（区分 feedback/query/suggestion/correction）
- ✅ 查询类问题的总结响应
- ✅ 修正机制（"之前说错了"）

**预计工作量**: 2-3 天

**验收标准**：
- 用户询问"检查了什么？"时，系统能生成总结而非推荐新步骤
- 用户修正"之前说错了，实际是X"时，系统能更新事实并重新评估
- E2E 测试覆盖这些场景

---

### Phase 2 - 增强功能（中优先级）

**目标**: 提升系统智能性和用户友好度

**包含**：
- ✅ 用户建议的处理（"会不会是X问题？"）
- ✅ 混合输入的分段处理
- ✅ 响应中回答用户问题

**预计工作量**: 1-2 天

**验收标准**：
- 用户建议"会不会是磁盘问题"时，系统提升相关假设优先级并在响应中确认
- 混合输入能被正确分段处理
- 响应包含对用户问题的回答

---

### Phase 3 - 高级功能（低优先级）

**目标**: 支持更复杂的对话模式

**包含**：
- ✅ 上下文引用处理（"刚才那个"、"之前提到的"）
- ✅ 多轮澄清对话
- ✅ 主动提问策略优化

**预计工作量**: 3-5 天

**验收标准**：
- 用户使用代词或引用时，系统能正确理解
- 系统能主动澄清模糊信息

---

## 成本分析

### LLM 调用增加

**当前**：每轮对话约 3-4 次 LLM 调用
1. 提取事实
2. 评估事实对假设的影响
3. 生成响应

**Phase 1 后**：每轮对话约 4-6 次 LLM 调用
1. **意图识别** ⭐ 新增
2. 提取事实
3. **检测修正**（如有）⭐ 新增
4. 评估事实对假设的影响
5. **生成总结**（如为 query 意图）⭐ 新增
6. 生成响应

**成本增加**: 约 50%

**优化策略**：
- 使用更便宜的模型做意图识别（如 GPT-3.5）
- 缓存常见问题的总结模板
- 批量处理 LLM 调用

---

## 风险与挑战

### 1. LLM 准确性

**风险**: 意图识别可能出错，导致错误处理

**缓解**：
- 提供详细的 few-shot examples
- 使用置信度阈值
- 错误情况下回退到保守策略（默认为 feedback）

### 2. 复杂度增加

**风险**: 代码复杂度显著增加，维护成本上升

**缓解**：
- 模块化设计，每个意图类型独立处理
- 充分的单元测试和 E2E 测试
- 详细的文档和注释

### 3. 用户期望管理

**风险**: 用户可能期望系统理解所有自然语言细节

**缓解**：
- 在 UI 中提供明确的使用指南
- 当系统不确定时，主动询问用户澄清
- 提供"我不理解，请重新表述"的回退响应

---

## 后续讨论点

1. **优先级确认**: Phase 1 中的哪些功能最重要？
2. **成本权衡**: LLM 调用增加 50% 是否可接受？
3. **实现时机**: 是否在当前修复提交后立即开始 Phase 1？
4. **测试策略**: 如何设计 E2E 测试覆盖这些复杂场景？

---

## 附录：数据模型变更

### ConfirmedFact 扩展

```python
class ConfirmedFact(BaseModel):
    """已确认的事实（扩展版）"""
    fact: str
    from_user_input: bool
    step_id: Optional[str] = None
    observation_result: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    # 新增字段
    is_correction: bool = False         # 是否是修正后的事实
    corrected_from: Optional[str] = None # 原始陈述（如果是修正）
    confidence_score: float = 1.0        # 事实的可信度（用户可能说"好像是..."）
```

### Hypothesis 扩展

```python
class Hypothesis(BaseModel):
    """根因假设（扩展版）"""
    root_cause: str
    confidence: float  # 基础置信度
    supporting_step_ids: List[str]
    missing_facts: List[str]
    next_recommended_step_id: Optional[str] = None

    # 新增字段
    user_boost: float = 0.0              # 用户建议的临时加成
    boost_reason: Optional[str] = None   # 加成原因

    @property
    def effective_confidence(self) -> float:
        """实际置信度（含用户加成）"""
        return min(self.confidence + self.user_boost, 1.0)
```

### UserIntent 模型

```python
class UserIntent(BaseModel):
    """用户意图分类"""
    intent_type: str  # "feedback" | "query" | "suggestion" | "correction" | "mixed"

    # 各类内容
    facts: List[str] = []
    questions: List[str] = []
    suggestions: List[str] = []
    corrections: List[Dict[str, str]] = []  # [{"original": "...", "corrected": "..."}]

    # 标记
    has_execution_feedback: bool = False
    needs_summary: bool = False
    needs_hypothesis_adjustment: bool = False

    # 置信度
    confidence: float = 1.0  # LLM 对意图识别的置信度
```

---

## 参考资料

- [Multi-turn Dialogue Management](https://arxiv.org/abs/2108.08877)
- [Intent Recognition in Task-oriented Dialogue](https://arxiv.org/abs/1902.10909)
- [Error Correction in Conversational AI](https://arxiv.org/abs/2104.08763)

---

**文档版本**: v1.0
**最后更新**: 2025-11-25
**作者**: Claude (claude-sonnet-4-5)
