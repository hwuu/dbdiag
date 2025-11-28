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
import sqlite3
import json
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from dbdiag.utils.config import load_config
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.services.llm_service import LLMService
from dbdiag.utils.vector_utils import serialize_f32, cosine_similarity
from dbdiag.dao import RawAnomalyDAO


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

    # 使用 DAO 读取原始异常
    raw_anomaly_dao = RawAnomalyDAO(db_path)

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

    # 批量写入操作使用直接 sqlite3 连接（需要事务控制）
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 4. 清除旧数据
        print("\n[4/6] 清除旧数据...")
        cursor.execute("DELETE FROM ticket_anomalies")
        cursor.execute("DELETE FROM phenomena")
        conn.commit()
        print("  已清除旧的 phenomena 和 ticket_anomalies")

        # 5. 生成标准现象
        print("\n[5/6] 生成标准现象...")
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

        # 6. 保存到数据库
        print("\n[6/6] 保存到数据库...")

        # 保存 phenomena
        for p in phenomena:
            cursor.execute("""
                INSERT INTO phenomena (
                    phenomenon_id, description, observation_method,
                    source_anomaly_ids, cluster_size, embedding
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                p["phenomenon_id"],
                p["description"],
                p["observation_method"],
                json.dumps(p["source_anomaly_ids"]),
                p["cluster_size"],
                serialize_f32(p["embedding"]),
            ))

        # 保存 ticket_anomalies
        for anomaly in raw_anomalies:
            phenomenon_id = anomaly_to_phenomenon[anomaly["id"]]
            cursor.execute("""
                INSERT INTO ticket_anomalies (
                    id, ticket_id, phenomenon_id, why_relevant, raw_anomaly_id
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                anomaly["id"],
                anomaly["ticket_id"],
                phenomenon_id,
                anomaly["why_relevant"],
                anomaly["id"],
            ))

        # 构建 root_causes 表
        print("\n[6.5/7] 构建 root_causes 表...")
        root_cause_map = _build_root_causes(cursor)
        print(f"  生成了 {len(root_cause_map)} 个根因")

        # 同步到 tickets 表（包含 root_cause_id）
        _sync_to_tickets(cursor, root_cause_map)

        conn.commit()

        # 显示统计
        cursor.execute("SELECT COUNT(*) FROM phenomena")
        phenomena_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ticket_anomalies")
        ticket_anomalies_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM root_causes")
        root_causes_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tickets")
        tickets_count = cursor.fetchone()[0]

        print(f"\n[OK] 索引重建完成")
        print(f"  phenomena: {phenomena_count}")
        print(f"  ticket_anomalies: {ticket_anomalies_count}")
        print(f"  root_causes: {root_causes_count}")
        print(f"  tickets: {tickets_count}")

    except Exception as e:
        print(f"\n[ERROR] 索引重建失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


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


def _build_root_causes(cursor: sqlite3.Cursor) -> Dict[str, str]:
    """
    从 raw_tickets 提取唯一根因，生成 root_causes 表

    Returns:
        根因文本到 root_cause_id 的映射
    """
    # 1. 提取唯一根因及其统计信息
    cursor.execute("""
        SELECT
            root_cause,
            GROUP_CONCAT(ticket_id) as ticket_ids,
            COUNT(*) as ticket_count,
            MAX(solution) as solution
        FROM raw_tickets
        GROUP BY root_cause
        ORDER BY ticket_count DESC
    """)

    root_cause_rows = cursor.fetchall()
    root_cause_map = {}  # root_cause_text -> root_cause_id

    # 2. 清除旧数据
    cursor.execute("DELETE FROM root_causes")

    # 3. 生成 root_causes 记录
    for idx, row in enumerate(root_cause_rows):
        root_cause_text = row[0]
        ticket_ids = row[1].split(",") if row[1] else []
        ticket_count = row[2]
        solution = row[3] or ""

        root_cause_id = f"RC-{idx + 1:04d}"
        root_cause_map[root_cause_text] = root_cause_id

        # 查找该根因关联的现象 ID
        cursor.execute("""
            SELECT DISTINCT ta.phenomenon_id
            FROM ticket_anomalies ta
            WHERE ta.ticket_id IN (
                SELECT ticket_id FROM raw_tickets WHERE root_cause = ?
            )
        """, (root_cause_text,))
        phenomenon_ids = [r[0] for r in cursor.fetchall()]

        cursor.execute("""
            INSERT INTO root_causes (
                root_cause_id, description, solution,
                key_phenomenon_ids, related_ticket_ids, ticket_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            root_cause_id,
            root_cause_text,
            solution,
            json.dumps(phenomenon_ids),
            json.dumps(ticket_ids),
            ticket_count,
        ))

    return root_cause_map


def _sync_to_tickets(cursor: sqlite3.Cursor, root_cause_map: Dict[str, str]) -> None:
    """
    同步数据到 tickets 表，包含 root_cause_id 外键

    Args:
        cursor: 数据库游标
        root_cause_map: 根因文本到 root_cause_id 的映射
    """
    # 先清空 tickets 表
    cursor.execute("DELETE FROM tickets")

    # 从 raw_tickets 读取数据并写入 tickets
    cursor.execute("""
        SELECT ticket_id, metadata_json, description, root_cause, solution
        FROM raw_tickets
    """)

    for row in cursor.fetchall():
        ticket_id, metadata_json, description, root_cause_text, solution = row
        root_cause_id = root_cause_map.get(root_cause_text)

        cursor.execute("""
            INSERT INTO tickets (
                ticket_id, metadata_json, description,
                root_cause_id, root_cause, solution
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ticket_id,
            metadata_json or "{}",
            description,
            root_cause_id,
            root_cause_text,
            solution,
        ))


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    config_path = sys.argv[2] if len(sys.argv) > 2 else None

    rebuild_index(db_path, config_path)
