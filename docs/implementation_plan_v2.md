> **[OLD - 已完成]** 本文档记录的是 V1 到 V2 的迁移计划，该迁移已于 2025 年 11 月完成。
> 保留此文档仅供历史参考。当前数据结构请参考 `design.md`。

# V2 架构实现计划

## 概述

将现有的 step-based 架构迁移到 phenomenon-based 架构，核心变更：
- `diagnostic_steps` → `anomalies` + `phenomena`
- 原始数据与处理后数据分离
- 批量推荐现象（集合）

## 现有模块分析

### 需要废弃（标记 deprecated）的模块/类

| 文件 | 类/函数 | 原因 |
|------|---------|------|
| `dbdiag/models/step.py` | `DiagnosticStep` | 替换为 `Phenomenon` |
| `dbdiag/models/session.py` | `ExecutedStep` | 替换为 `ConfirmedPhenomenon` |
| `dbdiag/models/session.py` | `Hypothesis.supporting_step_ids` | 替换为 `supporting_phenomenon_ids` |
| `scripts/init_db.py` | `diagnostic_steps` 表定义 | 替换为新表结构 |
| `scripts/import_tickets.py` | `_import_ticket()` | 需要更新为导入到 raw 表 |

### 需要新增的模块

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `dbdiag/models/phenomenon.py` | `Phenomenon`, `RawAnomaly` | 现象数据模型 |
| `dbdiag/models/session.py` | `ConfirmedPhenomenon` | 已确认现象 |
| `scripts/rebuild_index.py` | `rebuild_index()` | 聚类 + LLM 标准化 |

---

## 分步实现计划

### Phase 1: 数据模型层（1-2 天）

#### Step 1.1: 新增 phenomenon 模型

**文件**: `dbdiag/models/phenomenon.py`

```python
# 新增类
class RawAnomaly       # 原始异常
class Phenomenon       # 标准现象
class TicketAnomaly    # 工单-现象关联
```

**UT**: `tests/unit/test_phenomenon_model.py`
- 测试模型创建、序列化、反序列化

#### Step 1.2: 更新 session 模型

**文件**: `dbdiag/models/session.py`

```python
# 新增
class ConfirmedPhenomenon  # 替代 ExecutedStep

# 更新
class Hypothesis:
    supporting_phenomenon_ids: List[str]  # 替代 supporting_step_ids
    supporting_ticket_ids: List[str]      # 新增
    next_recommended_phenomenon_id: Optional[str]

class SessionState:
    confirmed_phenomena: List[ConfirmedPhenomenon]  # 替代 executed_steps
    recommended_phenomenon_ids: List[str]  # 替代 recommended_step_ids
```

**UT**: `tests/unit/test_session_models.py` 更新
- 测试新字段

#### Step 1.3: 标记 step.py 为 deprecated

**文件**: `dbdiag/models/step.py`

```python
import warnings

class DiagnosticStep(BaseModel):
    """
    DEPRECATED: 此类已废弃，请使用 phenomenon.Phenomenon
    """
    def __init__(self, **kwargs):
        warnings.warn(
            "DiagnosticStep is deprecated, use Phenomenon instead",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(**kwargs)
```

---

### Phase 2: 数据库层（1-2 天）

#### Step 2.1: 更新 init_db.py

**文件**: `scripts/init_db.py`

新增表：
- `raw_tickets` - 原始工单
- `raw_anomalies` - 原始异常
- `phenomena` - 标准现象库
- `ticket_anomalies` - 工单-现象关联

保留表（兼容）：
- `tickets` - 更新为处理后工单
- `sessions` - 保持不变

废弃表：
- `diagnostic_steps` - 标记为 deprecated，暂不删除

**UT**: `tests/unit/test_init_db.py`
- 测试新表创建
- 测试表结构正确性

#### Step 2.2: 更新 import_tickets.py

**文件**: `scripts/import_tickets.py`

```python
def import_tickets_v2(data_path, db_path):
    """
    导入到 raw_tickets + raw_anomalies
    """
    ...

# 保留旧函数，标记 deprecated
def import_tickets(data_path, db_path):
    """
    DEPRECATED: 使用 import_tickets_v2
    """
    warnings.warn("import_tickets is deprecated", DeprecationWarning)
    ...
```

**UT**: `tests/unit/test_import_tickets.py`
- 测试 v2 导入功能
- 验证原始数据正确存储

#### Step 2.3: 新增 rebuild_index.py

**文件**: `scripts/rebuild_index.py`

```python
def rebuild_index(db_path):
    """
    核心流程：
    1. 读取 raw_anomalies
    2. 生成向量
    3. 聚类
    4. LLM 生成标准描述
    5. 生成 phenomena + ticket_anomalies
    6. 构建向量索引
    """
    ...
```

**UT**: `tests/unit/test_rebuild_index.py`
- 测试聚类算法
- 测试 phenomenon 生成
- 测试关联映射

---

### Phase 3: 核心逻辑层（2-3 天）

#### Step 3.1: 更新 retriever.py

**文件**: `dbdiag/core/retriever.py`

```python
def retrieve_relevant_phenomena(session, top_k=10):
    """替代 retrieve_relevant_steps"""
    ...

# 保留旧函数，标记 deprecated
def retrieve_relevant_steps(session, top_k=10):
    """DEPRECATED"""
    warnings.warn("deprecated", DeprecationWarning)
    return retrieve_relevant_phenomena(session, top_k)
```

**UT**: `tests/unit/test_retriever.py` 更新
- 测试现象检索
- 测试向量匹配

#### Step 3.2: 更新 hypothesis_tracker.py

**文件**: `dbdiag/core/hypothesis_tracker.py`

```python
def update_hypotheses(session, new_facts):
    """更新假设，使用 phenomenon_ids"""
    ...

def compute_confidence(root_cause_pattern, supporting_phenomena, ...):
    """基于现象匹配计算置信度"""
    ...
```

**UT**: `tests/unit/test_hypothesis_tracker.py` 更新
- 测试置信度计算
- 测试假设更新

#### Step 3.3: 更新 recommender.py

**文件**: `dbdiag/core/recommender.py`

```python
def recommend_next_phenomena(session, top_k=3):
    """推荐一波现象（集合）"""
    ...

def generate_batch_recommendation(session, phenomena):
    """生成批量推荐响应"""
    ...

# 保留旧函数，标记 deprecated
def recommend_next_step(session):
    """DEPRECATED"""
    ...
```

**UT**: `tests/unit/test_recommender.py` 更新
- 测试批量推荐
- 测试现象选择算法

#### Step 3.4: 更新 dialogue_manager.py

**文件**: `dbdiag/core/dialogue_manager.py`

```python
def process_user_input(user_input, session):
    """
    1. 匹配现象
    2. 更新 confirmed_facts
    3. 计算置信度
    4. 推荐下一波现象
    """
    ...
```

**UT**: `tests/unit/test_dialogue_manager.py`
- 测试完整对话流程

---

### Phase 4: 集成测试（1-2 天）

#### Step 4.1: 更新 E2E 测试

**文件**: `tests/e2e/test_e2e_diagnosis.py`

- 测试完整诊断流程
- 测试批量推荐
- 测试置信度阈值触发

#### Step 4.2: 更新 CLI 交互测试

**文件**: `tests/e2e/test_cli_interaction.py`

- 测试 CLI 显示批量推荐
- 测试用户反馈处理

---

### Phase 5: 清理和文档（0.5 天）

#### Step 5.1: 清理 deprecated 警告

- 确保所有 deprecated 代码有清晰警告
- 更新 CHANGELOG

#### Step 5.2: 更新文档

- 更新 README
- 确保 design.md 和代码一致

---

## 实现顺序依赖图

```
Phase 1 (数据模型)
    │
    ├─ Step 1.1: phenomenon.py
    ├─ Step 1.2: session.py 更新
    └─ Step 1.3: step.py deprecated
           │
           ▼
Phase 2 (数据库层)
    │
    ├─ Step 2.1: init_db.py 更新
    ├─ Step 2.2: import_tickets.py 更新
    └─ Step 2.3: rebuild_index.py 新增
           │
           ▼
Phase 3 (核心逻辑) ─────────────────┐
    │                               │
    ├─ Step 3.1: retriever.py       │
    ├─ Step 3.2: hypothesis_tracker │
    ├─ Step 3.3: recommender.py     │
    └─ Step 3.4: dialogue_manager   │
           │                        │
           ▼                        │
Phase 4 (集成测试) ◄────────────────┘
    │
    ├─ Step 4.1: E2E 测试
    └─ Step 4.2: CLI 测试
           │
           ▼
Phase 5 (清理文档)
```

---

## UT 覆盖清单

| 模块 | 测试文件 | 覆盖内容 |
|------|----------|----------|
| `models/phenomenon.py` | `test_phenomenon_model.py` | 模型创建、序列化 |
| `models/session.py` | `test_session_models.py` | 新字段测试 |
| `scripts/init_db.py` | `test_init_db.py` | 表结构测试 |
| `scripts/import_tickets.py` | `test_import_tickets.py` | v2 导入测试 |
| `scripts/rebuild_index.py` | `test_rebuild_index.py` | 聚类、生成测试 |
| `core/retriever.py` | `test_retriever.py` | 现象检索测试 |
| `core/hypothesis_tracker.py` | `test_hypothesis_tracker.py` | 置信度计算测试 |
| `core/recommender.py` | `test_recommender.py` | 批量推荐测试 |
| `core/dialogue_manager.py` | `test_dialogue_manager.py` | 对话流程测试 |

---

## Deprecated 模块/函数汇总

```python
# dbdiag/models/step.py
class DiagnosticStep  # DEPRECATED → use Phenomenon

# dbdiag/models/session.py
class ExecutedStep  # DEPRECATED → use ConfirmedPhenomenon

# scripts/import_tickets.py
def import_tickets()  # DEPRECATED → use import_tickets_v2()

# dbdiag/core/retriever.py
def retrieve_relevant_steps()  # DEPRECATED → use retrieve_relevant_phenomena()

# dbdiag/core/recommender.py
def recommend_next_step()  # DEPRECATED → use recommend_next_phenomena()
```

---

## 开始实现

准备好后，从 **Phase 1, Step 1.1** 开始。
