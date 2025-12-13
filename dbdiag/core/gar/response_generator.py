"""响应生成器

生成用户可读的响应，并附带工单引用
"""
from typing import List, Dict, Any

from dbdiag.models import SessionState
from dbdiag.dao import PhenomenonDAO, TicketDAO, RootCauseDAO
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
        self._phenomenon_dao = PhenomenonDAO(db_path)
        self._ticket_dao = TicketDAO(db_path)
        self._root_cause_dao = RootCauseDAO(db_path)

    def _get_phenomenon_details(self, phenomenon_ids: List[str]) -> List[Dict[str, str]]:
        """
        获取现象详情

        Args:
            phenomenon_ids: 现象 ID 列表

        Returns:
            现象详情列表
        """
        return self._phenomenon_dao.get_by_ids(phenomenon_ids)

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

        if action == "confirm_root_cause":
            return self._generate_root_cause_response(session, recommendation)
        elif action == "ask_symptom":
            return self._generate_question_response(recommendation["message"])
        else:
            return self._generate_question_response(recommendation.get("message", "请提供更多信息"))

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
        root_cause_id = recommendation["root_cause"]  # 现在是 root_cause_id
        confidence = recommendation["confidence"]

        # 获取根因描述文本
        root_cause_description = self._get_root_cause_description(root_cause_id)

        # 获取相关工单引用
        citations = self._get_citations_for_root_cause(root_cause_id)

        # 获取解决方案
        solution = self._get_solution_for_root_cause(root_cause_id)

        # 获取已确认现象详情
        confirmed_ids = [cp.phenomenon_id for cp in session.confirmed_phenomena]
        phenomenon_details = self._get_phenomenon_details(confirmed_ids)

        # 调用 LLM 生成诊断总结
        diagnosis_summary = self._generate_diagnosis_summary(
            user_problem=session.user_problem,
            confirmed_phenomena=session.confirmed_phenomena,
            phenomenon_details=phenomenon_details,
            root_cause=root_cause_description,
            solution=solution,
            citations=citations,
        )

        message = f"""**根因已定位：{root_cause_description}** (置信度: {confidence:.0%})

{diagnosis_summary}

**引用工单：** {' '.join([f"[{i+1}]" for i in range(len(citations))])}
"""

        # 添加引用详情
        if citations:
            message += "\n---\n"
            for i, citation in enumerate(citations, 1):
                message += f"\n[{i}] **Ticket {citation['ticket_id']}**: {citation['description']}"
                message += f"\n    根因: {citation['root_cause']}"
                if citation.get('solution'):
                    message += f"\n    解决: {citation['solution'][:100]}..."
                message += "\n"

        return {
            "action": "confirm_root_cause",
            "message": message,
            "root_cause": root_cause_description,  # 返回描述文本
            "root_cause_id": root_cause_id,
            "confidence": confidence,
            "solution": solution,
            "citations": citations,
            "diagnosis_summary": diagnosis_summary,
        }

    def _generate_diagnosis_summary(
        self,
        user_problem: str,
        confirmed_phenomena: list,
        phenomenon_details: List[Dict[str, str]],
        root_cause: str,
        solution: str,
        citations: List[Dict[str, str]],
    ) -> str:
        """
        调用 LLM 生成诊断总结

        Args:
            user_problem: 用户问题描述
            confirmed_phenomena: 已确认现象列表
            phenomenon_details: 现象详情
            root_cause: 根因
            solution: 解决方案
            citations: 引用工单

        Returns:
            诊断总结文本
        """
        # 构建现象描述
        phenomena_text = ""
        detail_map = {d["phenomenon_id"]: d for d in phenomenon_details}
        for cp in confirmed_phenomena:
            detail = detail_map.get(cp.phenomenon_id, {})
            phenomena_text += f"- {detail.get('description', cp.phenomenon_id)}\n"
            phenomena_text += f"  用户反馈: {cp.result_summary}\n"

        # 构建引用案例
        citations_text = ""
        for c in citations[:2]:  # 最多取 2 个案例
            citations_text += f"- {c['description']}: {c['root_cause']}\n"

        prompt = f"""你是数据库诊断专家。请根据以下诊断过程，生成一份简洁的诊断总结报告。

## 用户问题
{user_problem}

## 已确认的现象
{phenomena_text if phenomena_text else "（无明确确认的现象）"}

## 定位的根因
{root_cause}

## 参考案例
{citations_text if citations_text else "（无参考案例）"}

## 建议解决方案
{solution}

请生成诊断总结，包含以下三个部分：
1. **观察到的现象**：列出诊断过程中确认的关键现象
2. **推理链路**：解释为什么这些现象指向该根因（因果关系）
3. **恢复措施**：具体的解决步骤

要求：
- 简洁明了，每部分 2-3 句话
- 使用 Markdown 格式
- 不要重复"根因已定位"这样的开头"""

        try:
            summary = self.llm_service.generate(prompt)
            # 清理 LLM 可能返回的 markdown 代码块标记
            summary = summary.strip()
            if summary.startswith("```markdown"):
                summary = summary[len("```markdown"):].strip()
            elif summary.startswith("```"):
                summary = summary[3:].strip()
            if summary.endswith("```"):
                summary = summary[:-3].strip()
            return summary
        except Exception as e:
            # 降级：返回简单模板
            return f"""**观察到的现象：**
{phenomena_text if phenomena_text else "用户描述: " + user_problem}

**推理链路：**
基于已确认现象和历史案例，判断根因为：{root_cause}

**恢复措施：**
{solution}"""

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

    def _get_citations_for_root_cause(self, root_cause_id: str) -> List[Dict[str, str]]:
        """
        获取根因的引用工单

        Args:
            root_cause_id: 根因 ID

        Returns:
            引用列表
        """
        return self._ticket_dao.get_by_root_cause_id(root_cause_id, limit=3)

    def _get_solution_for_root_cause(self, root_cause_id: str) -> str:
        """
        获取根因的解决方案

        Args:
            root_cause_id: 根因 ID

        Returns:
            解决方案文本
        """
        return self._root_cause_dao.get_solution(root_cause_id)

    def _get_root_cause_description(self, root_cause_id: str) -> str:
        """
        获取根因描述文本

        Args:
            root_cause_id: 根因 ID

        Returns:
            根因描述文本
        """
        return self._root_cause_dao.get_description(root_cause_id)
