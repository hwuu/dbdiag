"""步骤级检索引擎

实现基于向量和关键词的混合检索
"""
import sqlite3
from typing import List, Optional, Set
from pathlib import Path

from dbdiag.models.step import DiagnosticStep
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.vector_utils import deserialize_f32, cosine_similarity


class StepRetriever:
    """步骤检索器"""

    def __init__(self, db_path: str, embedding_service: EmbeddingService = None):
        """
        初始化检索器

        Args:
            db_path: 数据库路径
            embedding_service: Embedding 服务实例（单例，可选）
        """
        self.db_path = db_path
        self.embedding_service = embedding_service

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        vector_candidates: int = 50,
        keywords: Optional[List[str]] = None,
        excluded_step_ids: Optional[Set[str]] = None,
    ) -> List[tuple[DiagnosticStep, float]]:
        """
        检索相关的诊断步骤

        Args:
            query: 查询文本
            top_k: 返回前 K 个结果
            vector_candidates: 向量召回候选数量
            keywords: 关键词列表（用于过滤）
            excluded_step_ids: 已执行的步骤 ID（降低权重）

        Returns:
            (步骤, 得分) 列表，按得分降序排列
        """
        if excluded_step_ids is None:
            excluded_step_ids = set()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # 1. 向量检索（语义相似）
            if self.embedding_service:
                query_embedding = self.embedding_service.encode(query)

                # 获取所有有向量的步骤
                cursor.execute(
                    """
                    SELECT
                        step_id, ticket_id, step_index,
                        observed_fact, observation_method, analysis_result,
                        ticket_description, ticket_root_cause,
                        fact_embedding
                    FROM diagnostic_steps
                    WHERE fact_embedding IS NOT NULL
                    """
                )

                candidates = []
                for row in cursor.fetchall():
                    step_id = row["step_id"]
                    fact_emb_blob = row["fact_embedding"]

                    # 反序列化向量
                    fact_embedding = deserialize_f32(fact_emb_blob)

                    # 计算相似度
                    similarity = cosine_similarity(query_embedding, fact_embedding)

                    candidates.append((dict(row), similarity))

                # 按相似度排序，取 Top-N
                candidates.sort(key=lambda x: x[1], reverse=True)
                candidates = candidates[:vector_candidates]
            else:
                # 如果没有 embedding_service，使用关键词检索
                cursor.execute(
                    """
                    SELECT
                        step_id, ticket_id, step_index,
                        observed_fact, observation_method, analysis_result,
                        ticket_description, ticket_root_cause
                    FROM diagnostic_steps
                    """
                )
                candidates = [(dict(row), 0.5) for row in cursor.fetchall()[:vector_candidates]]

            # 2. 关键词过滤（如果提供）
            if keywords:
                filtered_candidates = []
                for row_dict, similarity in candidates:
                    # 检查是否包含关键词
                    text = f"{row_dict['observed_fact']} {row_dict['observation_method']} {row_dict['analysis_result']}"
                    if any(keyword.lower() in text.lower() for keyword in keywords):
                        filtered_candidates.append((row_dict, similarity))
                candidates = filtered_candidates

            # 3. 重排序（综合评分）
            scored_steps = []
            for row_dict, vector_score in candidates:
                step_id = row_dict["step_id"]

                # 3.1 向量相似度（权重 50%）
                vector_score_weight = 0.5 * vector_score

                # 3.2 步骤新颖度（权重 30%）
                novelty = 0.3 if step_id not in excluded_step_ids else 0.1

                # 3.3 关键词匹配度（权重 20%）
                keyword_score = 0.0
                if keywords:
                    text = f"{row_dict['observed_fact']} {row_dict['observation_method']}"
                    matched = sum(1 for kw in keywords if kw.lower() in text.lower())
                    keyword_score = 0.2 * (matched / len(keywords))
                else:
                    keyword_score = 0.2  # 无关键词时给默认分

                # 综合评分
                final_score = vector_score_weight + novelty + keyword_score

                # 构建 DiagnosticStep 对象
                step = DiagnosticStep(
                    step_id=row_dict["step_id"],
                    ticket_id=row_dict["ticket_id"],
                    step_index=row_dict["step_index"],
                    observed_fact=row_dict["observed_fact"],
                    observation_method=row_dict["observation_method"],
                    analysis_result=row_dict["analysis_result"],
                    ticket_description=row_dict["ticket_description"],
                    ticket_root_cause=row_dict["ticket_root_cause"],
                )

                scored_steps.append((step, final_score))

            # 4. 排序并返回 Top-K
            scored_steps.sort(key=lambda x: x[1], reverse=True)
            return scored_steps[:top_k]

        finally:
            conn.close()


def get_default_retriever(config_path: Optional[str] = None) -> StepRetriever:
    """
    获取默认的检索器实例

    Args:
        config_path: 配置文件路径

    Returns:
        StepRetriever 实例
    """
    from dbdiag.utils.config import load_config

    config = load_config(config_path)

    # 默认数据库路径
    project_root = Path(__file__).parent.parent.parent
    db_path = str(project_root / "data" / "tickets.db")

    return StepRetriever(db_path, config)
