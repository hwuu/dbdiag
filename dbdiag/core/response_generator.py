"""响应生成器

生成用户可读的响应，并附带工单引用
"""
import sqlite3
from typing import List, Dict, Any, Optional
from pathlib import Path

from dbdiag.models.step import DiagnosticStep
from dbdiag.models.session import SessionState, Hypothesis
from dbdiag.services.llm_service import LLMService


class ResponseGenerator:
    """响应生成器"""

    def __init__(self, db_path: str, llm_service: LLMService):
        """
        初始化响应生成器

        Args:
            db_path: 数据库路径
            llm_service: LLM 服务
        """
        self.db_path = db_path
        self.llm_service = llm_service

    def generate_response(
        self, session: SessionState, recommendation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成完整响应（包含引用）

        Args:
            session: 会话状态
            recommendation: 推荐动作

        Returns:
            响应字典
        """
        action = recommendation["action"]

        if action == "recommend_step":
            return self._generate_step_response(session, recommendation["step"])
        elif action == "confirm_root_cause":
            return self._generate_root_cause_response(session, recommendation)
        elif action == "ask_symptom":
            return self._generate_question_response(recommendation["message"])
        else:
            return self._generate_question_response(recommendation.get("message", "请提供更多信息"))

    def _generate_step_response(
        self, session: SessionState, step: DiagnosticStep
    ) -> Dict[str, Any]:
        """
        生成步骤推荐响应

        Args:
            session: 会话状态
            step: 推荐的步骤

        Returns:
            响应字典
        """
        # 查找相关工单（引用）
        citations = self._get_citations_for_step(step)

        # 构建引用标记
        citation_markers = " ".join([f"[{i+1}]" for i in range(len(citations))])

        # 使用 LLM 生成自然语言响应
        llm_prompt = f"""
基于以下诊断步骤，生成一段简洁的诊断建议（100字以内）：

**观察目标：** {step.observed_fact}
**诊断目的：** {step.analysis_result}

要求：
1. 语言简洁专业
2. 解释为什么要执行这个步骤
3. 不要重复观察目标的内容
"""

        explanation = self.llm_service.generate_simple(
            llm_prompt,
            system_prompt="你是一个数据库运维专家，擅长诊断数据库问题。回答要简明扼要。",
        )

        # 构建完整消息
        message = f"""{explanation}

**检查目标：** {step.observed_fact}

**具体操作：**
```sql
{step.observation_method}
```

**诊断目的：** {step.analysis_result}

**引用工单：** {citation_markers}
"""

        # 添加引用详情
        if citations:
            message += "\n\n---\n"
            for i, citation in enumerate(citations, 1):
                message += f"\n[{i}] **Ticket {citation['ticket_id']}**: {citation['description']}"
                message += f"\n    根因: {citation['root_cause']}\n"

        return {
            "action": "recommend_step",
            "message": message,
            "step": {
                "step_id": step.step_id,
                "observed_fact": step.observed_fact,
                "observation_method": step.observation_method,
                "analysis_result": step.analysis_result,
            },
            "citations": citations,
        }

    def _generate_root_cause_response(
        self, session: SessionState, recommendation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成根因确认响应

        Args:
            session: 会话状态
            recommendation: 推荐信息

        Returns:
            响应字典
        """
        root_cause = recommendation["root_cause"]
        confidence = recommendation["confidence"]
        supporting_step_ids = recommendation["supporting_step_ids"]

        # 获取相关工单引用
        citations = self._get_citations_for_root_cause(root_cause)

        # 构建诊断链路
        diagnostic_chain = []
        for i, fact in enumerate(session.confirmed_facts, 1):
            diagnostic_chain.append(f"{i}. ✓ {fact.fact}")

        chain_text = "\n".join(diagnostic_chain)

        # 获取解决方案
        solution = self._get_solution_for_root_cause(root_cause)

        message = f"""**根因已定位：{root_cause}** (置信度: {confidence:.0%})

**诊断链路：**
{chain_text}

**建议解决方案：**
{solution}

**引用工单：** {' '.join([f"[{i+1}]" for i in range(len(citations))])}
"""

        # 添加引用详情
        if citations:
            message += "\n\n---\n"
            for i, citation in enumerate(citations, 1):
                message += f"\n[{i}] **Ticket {citation['ticket_id']}**: {citation['description']}"
                message += f"\n    根因: {citation['root_cause']}"
                if citation.get('solution'):
                    message += f"\n    解决: {citation['solution'][:100]}..."
                message += "\n"

        return {
            "action": "confirm_root_cause",
            "message": message,
            "root_cause": root_cause,
            "confidence": confidence,
            "solution": solution,
            "citations": citations,
        }

    def _generate_question_response(self, question: str) -> Dict[str, Any]:
        """
        生成询问响应

        Args:
            question: 询问内容

        Returns:
            响应字典
        """
        return {
            "action": "ask_question",
            "message": question,
        }

    def _get_citations_for_step(self, step: DiagnosticStep) -> List[Dict[str, str]]:
        """
        获取步骤的引用工单

        Args:
            step: 诊断步骤

        Returns:
            引用列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT DISTINCT t.ticket_id, t.description, t.root_cause
                FROM tickets t
                JOIN diagnostic_steps ds ON t.ticket_id = ds.ticket_id
                WHERE ds.step_id = ?
                LIMIT 3
                """,
                (step.step_id,),
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    def _get_citations_for_root_cause(self, root_cause: str) -> List[Dict[str, str]]:
        """
        获取根因的引用工单

        Args:
            root_cause: 根因

        Returns:
            引用列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT ticket_id, description, root_cause, solution
                FROM tickets
                WHERE root_cause = ?
                LIMIT 3
                """,
                (root_cause,),
            )

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    def _get_solution_for_root_cause(self, root_cause: str) -> str:
        """
        获取根因的解决方案

        Args:
            root_cause: 根因

        Returns:
            解决方案文本
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT solution
                FROM tickets
                WHERE root_cause = ?
                LIMIT 1
                """,
                (root_cause,),
            )

            row = cursor.fetchone()
            if row:
                return row[0]

            return "暂无具体解决方案，请参考相关工单。"

        finally:
            conn.close()
