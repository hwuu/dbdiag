"""索引重建脚本

从原始数据表（raw_anomalies）重建标准现象库（phenomena）和关联表（ticket_anomalies）。

核心流程：
1. 读取 raw_anomalies
2. 生成向量（Embedding API）
3. 向量聚类（相似度阈值）
4. LLM 生成标准描述
5. 生成 phenomena + ticket_anomalies
6. 构建向量索引
"""
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any

from dbdiag.utils.config import load_config
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.services.llm_service import LLMService
from dbdiag.utils.vector_utils import cosine_similarity
from dbdiag.dao import RawAnomalyDAO, IndexBuilderDAO


def rebuild_index(
    db_path: Optional[str] = None,
    config_path: Optional[str] = None,
    similarity_threshold: float = 0.85,
) -> None:
    """
    重建索引

    Args:
        db_path: 数据库路径，默认 data/tickets.db
        config_path: 配置文件路径，默认 config.yaml
        similarity_threshold: 聚类相似度阈值，默认 0.85
    """
    if db_path is None:
        project_root = Path(__file__).parent.parent
        db_path = str(project_root / "data" / "tickets.db")

    if not Path(db_path).exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    print(f"[rebuild-index] 开始重建索引...")
    print(f"数据库: {db_path}")
    print(f"相似度阈值: {similarity_threshold}")

    # 加载配置
    config = load_config(config_path)

    # 初始化服务
    embedding_service = EmbeddingService(config)
    llm_service = LLMService(config)

    # 初始化 DAO
    raw_anomaly_dao = RawAnomalyDAO(db_path)
    index_builder_dao = IndexBuilderDAO(db_path)

    # 1. 读取原始异常
    print("\n[1/6] 读取原始异常...")
    raw_anomalies = raw_anomaly_dao.get_all()
    print(f"  共 {len(raw_anomalies)} 条原始异常")

    if not raw_anomalies:
        print("  [WARN] 没有原始异常数据，跳过重建")
        return

    # 2. 生成向量
    print("\n[2/6] 生成向量...")
    descriptions = [a["description"] for a in raw_anomalies]
    embeddings = embedding_service.encode_batch(descriptions)

    for i, anomaly in enumerate(raw_anomalies):
        anomaly["embedding"] = embeddings[i]

    print(f"  生成了 {len(embeddings)} 个向量")

    # 3. 向量聚类
    print("\n[3/6] 向量聚类...")
    clusters = cluster_by_similarity(raw_anomalies, similarity_threshold)
    print(f"  聚类结果: {len(raw_anomalies)} 个异常 -> {len(clusters)} 个聚类")

    # 4. 生成标准现象
    print("\n[4/6] 生成标准现象...")
    phenomena = []
    anomaly_to_phenomenon = {}  # raw_anomaly_id -> phenomenon_id

    for cluster_id, cluster_items in enumerate(clusters):
        phenomenon = _generate_phenomenon(
            cluster_id=cluster_id,
            cluster_items=cluster_items,
            llm_service=llm_service,
        )
        phenomena.append(phenomenon)

        # 记录映射关系
        for item in cluster_items:
            anomaly_to_phenomenon[item["id"]] = phenomenon["phenomenon_id"]

    print(f"  生成了 {len(phenomena)} 个标准现象")

    # 5. 使用 DAO 保存到数据库
    print("\n[5/6] 保存到数据库...")
    try:
        stats = index_builder_dao.rebuild_all(
            phenomena=phenomena,
            raw_anomalies=raw_anomalies,
            anomaly_to_phenomenon=anomaly_to_phenomenon,
        )

        print(f"\n[OK] 索引重建完成")
        print(f"  phenomena: {stats['phenomena']}")
        print(f"  ticket_anomalies: {stats['ticket_anomalies']}")
        print(f"  root_causes: {stats['root_causes']}")
        print(f"  tickets: {stats['tickets']}")

    except Exception as e:
        print(f"\n[ERROR] 索引重建失败: {e}")
        raise


def cluster_by_similarity(
    items: List[Dict[str, Any]],
    similarity_threshold: float,
) -> List[List[Dict[str, Any]]]:
    """
    基于向量相似度的聚类算法

    使用贪心聚类：
    1. 按顺序遍历所有项
    2. 对每个项，检查是否与现有聚类中心相似
    3. 如果相似，加入该聚类；否则创建新聚类

    Args:
        items: 包含 'embedding' 字段的项列表
        similarity_threshold: 相似度阈值

    Returns:
        聚类列表，每个聚类是一个项列表
    """
    clusters: List[List[Dict[str, Any]]] = []
    cluster_centers: List[List[float]] = []

    for item in items:
        embedding = item["embedding"]
        matched_cluster_idx = None
        max_similarity = 0

        # 检查与现有聚类的相似度
        for idx, center in enumerate(cluster_centers):
            similarity = cosine_similarity(embedding, center)
            if similarity > similarity_threshold and similarity > max_similarity:
                matched_cluster_idx = idx
                max_similarity = similarity

        if matched_cluster_idx is not None:
            # 加入现有聚类
            clusters[matched_cluster_idx].append(item)
            # 更新聚类中心（增量平均）
            n = len(clusters[matched_cluster_idx])
            old_center = np.array(cluster_centers[matched_cluster_idx])
            new_embedding = np.array(embedding)
            cluster_centers[matched_cluster_idx] = (
                (old_center * (n - 1) + new_embedding) / n
            ).tolist()
        else:
            # 创建新聚类
            clusters.append([item])
            cluster_centers.append(embedding)

    return clusters


def _generate_phenomenon(
    cluster_id: int,
    cluster_items: List[Dict[str, Any]],
    llm_service: LLMService,
) -> Dict[str, Any]:
    """
    为聚类生成标准现象

    Args:
        cluster_id: 聚类 ID
        cluster_items: 聚类中的原始异常列表
        llm_service: LLM 服务

    Returns:
        标准现象字典
    """
    phenomenon_id = f"P-{cluster_id + 1:04d}"

    # 收集描述和方法
    descriptions = [item["description"] for item in cluster_items]
    methods = [item["observation_method"] for item in cluster_items]

    # 如果只有一个项，直接使用
    if len(cluster_items) == 1:
        standard_description = descriptions[0]
    else:
        # 使用 LLM 生成标准化描述
        prompt = f"""以下是多个相似的数据库异常现象描述：
{chr(10).join(f'- {d}' for d in descriptions)}

请生成一个标准化的异常现象描述，要求：
1. 保留关键指标名称
2. 使用通用的阈值表述（如"超过阈值"而非具体数字）
3. 简洁明确

只输出标准化描述，不要其他内容。"""

        try:
            standard_description = llm_service.generate_simple(prompt)
            standard_description = standard_description.strip()
        except Exception as e:
            print(f"    [WARN] LLM 生成失败，使用第一个描述: {e}")
            standard_description = descriptions[0]

    # 选择最完整的观察方法
    best_method = max(methods, key=lambda m: len(m) if m else 0)

    # 计算聚类中心向量
    embeddings = [item["embedding"] for item in cluster_items]
    center_embedding = np.mean(embeddings, axis=0).tolist()

    return {
        "phenomenon_id": phenomenon_id,
        "description": standard_description,
        "observation_method": best_method,
        "source_anomaly_ids": [item["id"] for item in cluster_items],
        "cluster_size": len(cluster_items),
        "embedding": center_embedding,
    }


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    config_path = sys.argv[2] if len(sys.argv) > 2 else None

    rebuild_index(db_path, config_path)
