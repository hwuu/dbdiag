"""索引重建脚本

从原始数据表重建标准化数据。

核心流程：
1. 读取 raw_anomalies
2. 生成异常向量（Embedding API）
3. 异常向量聚类（相似度阈值）
4. LLM 生成标准现象描述
5. 提取原始根因并生成向量
6. 根因向量聚类 + LLM 生成标准根因
7. 保存到数据库
8. 初始化 RAR 索引
"""
import sqlite3
import time
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any

from tqdm import tqdm

from dbdiag.utils.config import load_config
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.services.llm_service import LLMService
from dbdiag.utils.vector_utils import cosine_similarity, serialize_f32
from dbdiag.dao import RawAnomalyDAO, RawTicketDAO, IndexBuilderDAO


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
        project_root = Path(__file__).parent.parent.parent
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

    # DEBUG: 打印 embedding 配置
    print(f"\n[DEBUG] Embedding 配置:")
    print(f"  model: {config.embedding_model.model}")
    print(f"  api_base: {config.embedding_model.api_base}")

    # 初始化 DAO
    raw_anomaly_dao = RawAnomalyDAO(db_path)
    raw_ticket_dao = RawTicketDAO(db_path)
    index_builder_dao = IndexBuilderDAO(db_path)

    # 1. 读取原始异常
    print("\n[1/7] 读取原始异常...")
    raw_anomalies = raw_anomaly_dao.get_all()
    print(f"  共 {len(raw_anomalies)} 条原始异常")

    if not raw_anomalies:
        print("  [WARN] 没有原始异常数据，跳过重建")
        return

    # 2. 生成异常向量
    print("\n[2/7] 生成异常向量...")
    descriptions = [a["description"] for a in raw_anomalies]

    # 进度回调
    def embedding_progress(done: int, total: int, elapsed: float):
        print(f"\r  进度: {done}/{total} ({done*100//total}%), 本批耗时: {elapsed:.2f}s", end="", flush=True)

    embeddings = embedding_service.encode_batch(
        descriptions,
        progress_callback=embedding_progress,
    )
    print()  # 换行

    for i, anomaly in enumerate(raw_anomalies):
        anomaly["embedding"] = embeddings[i]

    print(f"  生成了 {len(embeddings)} 个向量")
    # DEBUG: 打印向量维度和前几个向量的范数
    if embeddings:
        print(f"  [DEBUG] 向量维度: {len(embeddings[0])}")
        norms = [np.linalg.norm(e) for e in embeddings[:5]]
        print(f"  [DEBUG] 前 5 个向量范数: {[f'{n:.4f}' for n in norms]}")

    # 3. 异常向量聚类
    print("\n[3/7] 异常向量聚类...")
    clusters = cluster_by_similarity(raw_anomalies, similarity_threshold)
    print(f"  聚类结果: {len(raw_anomalies)} 个异常 -> {len(clusters)} 个聚类")

    # 4. 生成标准现象
    print("\n[4/7] 生成标准现象...")
    phenomena = []
    anomaly_to_phenomenon = {}  # raw_anomaly_id -> phenomenon_id

    # 统计信息
    single_item_count = sum(1 for c in clusters if len(c) == 1)
    multi_item_count = len(clusters) - single_item_count
    print(f"  单项聚类: {single_item_count} 个（无需 LLM）")
    print(f"  多项聚类: {multi_item_count} 个（需要 LLM 生成标准描述）")

    llm_call_times = []

    for cluster_id, cluster_items in enumerate(tqdm(clusters, desc="  生成现象", unit="个")):
        phenomenon = _generate_phenomenon(
            cluster_id=cluster_id,
            cluster_items=cluster_items,
            llm_service=llm_service,
            llm_call_times=llm_call_times,
        )
        phenomena.append(phenomenon)

        # 记录映射关系
        for item in cluster_items:
            anomaly_to_phenomenon[item["id"]] = phenomenon["phenomenon_id"]

    print(f"  生成了 {len(phenomena)} 个标准现象")
    if llm_call_times:
        avg_time = sum(llm_call_times) / len(llm_call_times)
        total_time = sum(llm_call_times)
        print(f"  [DEBUG] LLM 调用: {len(llm_call_times)} 次, 总耗时: {total_time:.1f}s, 平均: {avg_time:.2f}s/次")

    # 5. 提取原始根因并生成向量
    print("\n[5/7] 提取原始根因...")
    raw_root_causes = _extract_raw_root_causes(raw_ticket_dao)
    print(f"  共 {len(raw_root_causes)} 个唯一原始根因")

    if raw_root_causes:
        print("  生成根因向量...")
        rc_descriptions = [rc["description"] for rc in raw_root_causes]

        def rc_embedding_progress(done: int, total: int, elapsed: float):
            print(f"\r  进度: {done}/{total} ({done*100//total}%), 本批耗时: {elapsed:.2f}s", end="", flush=True)

        rc_embeddings = embedding_service.encode_batch(
            rc_descriptions,
            progress_callback=rc_embedding_progress,
        )
        print()  # 换行

        for i, rc in enumerate(raw_root_causes):
            rc["embedding"] = rc_embeddings[i]

        print(f"  生成了 {len(rc_embeddings)} 个根因向量")

    # 6. 根因聚类 + 生成标准根因
    print("\n[6/7] 根因聚类...")
    if raw_root_causes:
        rc_clusters = cluster_by_similarity(raw_root_causes, similarity_threshold, debug=True)
        print(f"  聚类结果: {len(raw_root_causes)} 个原始根因 -> {len(rc_clusters)} 个聚类")

        # 统计信息
        rc_single_count = sum(1 for c in rc_clusters if len(c) == 1)
        rc_multi_count = len(rc_clusters) - rc_single_count
        print(f"  单项聚类: {rc_single_count} 个（无需 LLM）")
        print(f"  多项聚类: {rc_multi_count} 个（需要 LLM 生成标准描述）")

        root_causes = []
        raw_rc_to_standard = {}  # raw_root_cause_id -> root_cause_id
        rc_llm_times = []

        for cluster_id, cluster_items in enumerate(tqdm(rc_clusters, desc="  生成根因", unit="个")):
            root_cause = _generate_root_cause(
                cluster_id=cluster_id,
                cluster_items=cluster_items,
                llm_service=llm_service,
                llm_call_times=rc_llm_times,
            )
            root_causes.append(root_cause)

            # 记录映射关系
            for item in cluster_items:
                raw_rc_to_standard[item["id"]] = root_cause["root_cause_id"]

        print(f"  生成了 {len(root_causes)} 个标准根因")
        if rc_llm_times:
            avg_time = sum(rc_llm_times) / len(rc_llm_times)
            total_time = sum(rc_llm_times)
            print(f"  [DEBUG] LLM 调用: {len(rc_llm_times)} 次, 总耗时: {total_time:.1f}s, 平均: {avg_time:.2f}s/次")
    else:
        raw_root_causes = []
        root_causes = []
        raw_rc_to_standard = {}

    # 7. 保存到数据库
    print("\n[7/7] 保存到数据库...")
    try:
        stats = index_builder_dao.rebuild_all(
            phenomena=phenomena,
            raw_anomalies=raw_anomalies,
            anomaly_to_phenomenon=anomaly_to_phenomenon,
            raw_root_causes=raw_root_causes,
            root_causes=root_causes,
            raw_rc_to_standard=raw_rc_to_standard,
        )

        print(f"\n[OK] 索引重建完成")
        print(f"  raw_root_causes: {stats['raw_root_causes']}")
        print(f"  root_causes: {stats['root_causes']}")
        print(f"  phenomena: {stats['phenomena']}")
        print(f"  ticket_phenomena: {stats['ticket_phenomena']}")
        print(f"  phenomenon_root_causes: {stats['phenomenon_root_causes']}")
        print(f"  tickets: {stats['tickets']}")

    except Exception as e:
        print(f"\n[ERROR] 索引重建失败: {e}")
        raise

    # 8. 初始化 RAR 索引
    print("\n[8/8] 初始化 RAR 索引...")
    _init_rar_index(db_path, embedding_service)


def cluster_by_similarity(
    items: List[Dict[str, Any]],
    similarity_threshold: float,
    debug: bool = True,
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
        debug: 是否打印调试信息

    Returns:
        聚类列表，每个聚类是一个项列表
    """
    clusters: List[List[Dict[str, Any]]] = []
    cluster_centers: List[List[float]] = []

    # DEBUG: 记录聚类过程
    merge_log = []

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
            # DEBUG: 记录合并
            if debug:
                merge_log.append({
                    "item_id": item["id"],
                    "cluster_idx": matched_cluster_idx,
                    "similarity": max_similarity,
                })
        else:
            # 创建新聚类
            clusters.append([item])
            cluster_centers.append(embedding)

    # DEBUG: 打印聚类详情
    if debug:
        print(f"  [DEBUG] 聚类合并次数: {len(merge_log)}")
        # 打印多项聚类的详情
        multi_item_clusters = [(i, c) for i, c in enumerate(clusters) if len(c) > 1]
        print(f"  [DEBUG] 多项聚类数: {len(multi_item_clusters)}")
        for cluster_idx, cluster in multi_item_clusters[:10]:  # 只打印前 10 个
            item_ids = [item["id"] for item in cluster]
            print(f"    聚类 {cluster_idx}: {item_ids}")
        if len(multi_item_clusters) > 10:
            print(f"    ... 还有 {len(multi_item_clusters) - 10} 个多项聚类")

    return clusters


def _generate_phenomenon(
    cluster_id: int,
    cluster_items: List[Dict[str, Any]],
    llm_service: LLMService,
    llm_call_times: List[float] = None,
) -> Dict[str, Any]:
    """
    为聚类生成标准现象

    Args:
        cluster_id: 聚类 ID
        cluster_items: 聚类中的原始异常列表
        llm_service: LLM 服务
        llm_call_times: LLM 调用耗时列表（用于统计）

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
            start_time = time.time()
            standard_description = llm_service.generate_simple(prompt)
            elapsed = time.time() - start_time
            if llm_call_times is not None:
                llm_call_times.append(elapsed)
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


def _extract_raw_root_causes(raw_ticket_dao: RawTicketDAO) -> List[Dict[str, Any]]:
    """
    从 raw_tickets 提取唯一的原始根因

    Args:
        raw_ticket_dao: RawTicketDAO 实例

    Returns:
        原始根因列表，每项包含 id, description, solution, source_ticket_ids, ticket_count
    """
    # 获取所有工单
    tickets = raw_ticket_dao.get_all()

    # 按根因分组
    root_cause_map: Dict[str, Dict[str, Any]] = {}

    for ticket in tickets:
        rc_text = ticket["root_cause"]
        solution = ticket["solution"]
        ticket_id = ticket["ticket_id"]

        if rc_text not in root_cause_map:
            root_cause_map[rc_text] = {
                "description": rc_text,
                "solution": solution,
                "source_ticket_ids": [],
            }

        root_cause_map[rc_text]["source_ticket_ids"].append(ticket_id)
        # 取最长的 solution
        if len(solution) > len(root_cause_map[rc_text]["solution"]):
            root_cause_map[rc_text]["solution"] = solution

    # 转换为列表并分配 ID
    raw_root_causes = []
    for idx, (rc_text, data) in enumerate(root_cause_map.items()):
        raw_root_causes.append({
            "id": f"RRC-{idx + 1:04d}",
            "description": data["description"],
            "solution": data["solution"],
            "source_ticket_ids": data["source_ticket_ids"],
            "ticket_count": len(data["source_ticket_ids"]),
        })

    return raw_root_causes


def _generate_root_cause(
    cluster_id: int,
    cluster_items: List[Dict[str, Any]],
    llm_service: LLMService,
    llm_call_times: List[float] = None,
) -> Dict[str, Any]:
    """
    为聚类生成标准根因

    Args:
        cluster_id: 聚类 ID
        cluster_items: 聚类中的原始根因列表
        llm_service: LLM 服务
        llm_call_times: LLM 调用耗时列表（用于统计）

    Returns:
        标准根因字典
    """
    root_cause_id = f"RC-{cluster_id + 1:04d}"

    # 收集描述和解决方案
    descriptions = [item["description"] for item in cluster_items]
    solutions = [item["solution"] for item in cluster_items]

    # 合并工单 ID 和计算总数
    all_ticket_ids = []
    for item in cluster_items:
        all_ticket_ids.extend(item["source_ticket_ids"])
    total_ticket_count = len(all_ticket_ids)

    # 如果只有一个项，直接使用
    if len(cluster_items) == 1:
        standard_description = descriptions[0]
        standard_solution = solutions[0]
    else:
        # 使用 LLM 生成标准化根因描述
        desc_prompt = f"""以下是多个相似的数据库问题根因描述：
{chr(10).join(f'- {d}' for d in descriptions)}

请生成一个标准化的根因描述，要求：
1. 保留核心问题原因
2. 简洁明确
3. 不超过 50 字

只输出标准化描述，不要其他内容。"""

        try:
            start_time = time.time()
            standard_description = llm_service.generate_simple(desc_prompt)
            standard_description = standard_description.strip()

            # LLM 合并解决方案
            solution_prompt = f"""以下是针对同一根因的多个解决方案：
{chr(10).join(f'- {s}' for s in solutions if s)}

请合并生成一个综合的解决方案，要求：
1. 包含所有有效的解决步骤
2. 去除重复内容
3. 按执行顺序排列

只输出合并后的解决方案，不要其他内容。"""

            standard_solution = llm_service.generate_simple(solution_prompt)
            standard_solution = standard_solution.strip()

            elapsed = time.time() - start_time
            if llm_call_times is not None:
                llm_call_times.append(elapsed)

        except Exception as e:
            print(f"    [WARN] LLM 生成失败，使用第一个描述: {e}")
            standard_description = descriptions[0]
            standard_solution = max(solutions, key=lambda s: len(s) if s else 0)

    # 计算聚类中心向量
    embeddings = [item["embedding"] for item in cluster_items]
    center_embedding = np.mean(embeddings, axis=0).tolist()

    return {
        "root_cause_id": root_cause_id,
        "description": standard_description,
        "solution": standard_solution,
        "source_raw_root_cause_ids": [item["id"] for item in cluster_items],
        "cluster_size": len(cluster_items),
        "related_ticket_ids": all_ticket_ids,
        "ticket_count": total_ticket_count,
        "embedding": center_embedding,
    }


def _init_rar_index(
    db_path: str,
    embedding_service: EmbeddingService,
) -> None:
    """
    初始化 RAR 索引

    从 raw_tickets 读取数据，生成 embedding 后写入 rar_raw_tickets。

    Args:
        db_path: 数据库路径
        embedding_service: Embedding 服务实例
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. 读取 raw_tickets
        cursor.execute("""
            SELECT ticket_id, description, root_cause, solution
            FROM raw_tickets
        """)
        raw_tickets = cursor.fetchall()
        print(f"  共 {len(raw_tickets)} 条工单")

        if not raw_tickets:
            print("  [WARN] 没有数据，跳过 RAR 索引初始化")
            return

        # 2. 生成 combined_text 和 embedding
        records = []
        combined_texts = []

        for ticket_id, description, root_cause, solution in raw_tickets:
            combined_text = f"问题描述: {description}\n根因: {root_cause}\n解决方案: {solution}"
            combined_texts.append(combined_text)
            records.append({
                "ticket_id": ticket_id,
                "description": description,
                "root_cause": root_cause,
                "solution": solution,
                "combined_text": combined_text,
            })

        # 批量生成 embedding
        embeddings = embedding_service.encode_batch(combined_texts)
        print(f"  生成了 {len(embeddings)} 个向量")

        # 3. 写入 rar_raw_tickets
        # 先清空旧数据（幂等性）
        cursor.execute("DELETE FROM rar_raw_tickets")

        # 插入新数据
        for record, embedding in zip(records, embeddings):
            cursor.execute(
                """
                INSERT INTO rar_raw_tickets
                (ticket_id, description, root_cause, solution, combined_text, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record["ticket_id"],
                    record["description"],
                    record["root_cause"],
                    record["solution"],
                    record["combined_text"],
                    serialize_f32(embedding),
                ),
            )

        conn.commit()
        print(f"  [OK] RAR 索引初始化完成，共 {len(records)} 条记录")

    except Exception as e:
        print(f"  [ERROR] RAR 索引初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    config_path = sys.argv[2] if len(sys.argv) > 2 else None

    rebuild_index(db_path, config_path)
