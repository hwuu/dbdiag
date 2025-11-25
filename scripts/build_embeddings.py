"""构建向量索引脚本

调用 Embedding API 为所有诊断步骤生成向量，并存储到数据库
"""
import sqlite3
import struct
from pathlib import Path
from typing import Optional, List
from tqdm import tqdm

from dbdiag.utils.config import load_config
from dbdiag.services.embedding_service import EmbeddingService


def serialize_f32(vector: List[float]) -> bytes:
    """
    将浮点向量序列化为 BLOB（float32 格式）

    Args:
        vector: 浮点向量

    Returns:
        序列化后的字节数据
    """
    return struct.pack(f"{len(vector)}f", *vector)


def build_embeddings(db_path: Optional[str] = None, config_path: Optional[str] = None) -> None:
    """
    构建向量索引

    Args:
        db_path: 数据库文件路径，默认为 data/tickets.db
        config_path: 配置文件路径，默认为 config.yaml
    """
    if db_path is None:
        # 默认使用项目根目录下的 data/tickets.db
        project_root = Path(__file__).parent.parent
        db_path = str(project_root / "data" / "tickets.db")

    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"数据库文件不存在: {db_path}\n"
            f"请先运行: python -m app init && python -m app import --data data/example_tickets.json"
        )

    # 加载配置
    config = load_config(config_path)
    print(f"使用 Embedding 模型: {config.embedding_model.model}")
    print(f"向量维度: {config.embedding_model.dimension}")

    # 初始化 Embedding 服务
    embedding_service = EmbeddingService(config)

    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 检查是否需要加载 sqlite-vec 扩展
        # 注意：sqlite-vec 需要单独安装和加载
        try:
            # 尝试加载 sqlite-vec 扩展（如果已安装）
            # conn.enable_load_extension(True)
            # conn.load_extension("vec0")
            # conn.enable_load_extension(False)
            print("[INFO] sqlite-vec 扩展加载跳过（暂时使用 BLOB 存储）")
        except Exception as e:
            print(f"[WARN] 无法加载 sqlite-vec 扩展: {e}")
            print("[INFO] 将使用 BLOB 格式存储向量（暂不支持向量检索）")

        # 获取所有需要生成向量的诊断步骤
        cursor.execute(
            """
            SELECT step_id, observed_fact, observation_method
            FROM diagnostic_steps
            WHERE fact_embedding IS NULL OR method_embedding IS NULL
            """
        )
        steps = cursor.fetchall()

        if not steps:
            print("[INFO] 所有步骤的向量已生成，无需重建")
            return

        print(f"\n正在为 {len(steps)} 个诊断步骤生成向量...")

        # 准备文本数据
        step_ids = [step[0] for step in steps]
        facts = [step[1] for step in steps]
        methods = [step[2] for step in steps]

        # 批量生成 fact_embedding
        print("\n[1/2] 生成 observed_fact 向量...")
        fact_embeddings = []
        for i in tqdm(range(0, len(facts), 32), desc="Encoding facts"):
            batch = facts[i : i + 32]
            batch_embeddings = embedding_service.encode_batch(batch, batch_size=32)
            fact_embeddings.extend(batch_embeddings)

        # 批量生成 method_embedding
        print("\n[2/2] 生成 observation_method 向量...")
        method_embeddings = []
        for i in tqdm(range(0, len(methods), 32), desc="Encoding methods"):
            batch = methods[i : i + 32]
            batch_embeddings = embedding_service.encode_batch(batch, batch_size=32)
            method_embeddings.extend(batch_embeddings)

        # 更新数据库
        print("\n正在保存向量到数据库...")
        for step_id, fact_emb, method_emb in tqdm(
            zip(step_ids, fact_embeddings, method_embeddings),
            total=len(step_ids),
            desc="Saving vectors",
        ):
            cursor.execute(
                """
                UPDATE diagnostic_steps
                SET fact_embedding = ?, method_embedding = ?
                WHERE step_id = ?
                """,
                (
                    serialize_f32(fact_emb),
                    serialize_f32(method_emb),
                    step_id,
                ),
            )

        conn.commit()

        print(f"\n[OK] 向量索引构建完成")
        print(f"  已处理步骤: {len(steps)}")
        print(f"  向量维度: {config.embedding_model.dimension}")

        # 统计信息
        cursor.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN fact_embedding IS NOT NULL THEN 1 ELSE 0 END) as fact_count,
                SUM(CASE WHEN method_embedding IS NOT NULL THEN 1 ELSE 0 END) as method_count
            FROM diagnostic_steps
            """
        )
        total, fact_count, method_count = cursor.fetchone()

        print(f"\n数据库向量统计:")
        print(f"  总步骤数: {total}")
        print(f"  fact_embedding 已生成: {fact_count}")
        print(f"  method_embedding 已生成: {method_count}")

    except Exception as e:
        print(f"\n[ERROR] 向量索引构建失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    config_path = sys.argv[2] if len(sys.argv) > 2 else None

    build_embeddings(db_path, config_path)
