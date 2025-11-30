"""RAR 索引初始化脚本

从 raw_tickets 表读取数据，生成向量后写入 rar_raw_tickets 表。

用法：python -m dbdiag.scripts.init_rar_index
"""
import sqlite3
from pathlib import Path
from typing import Optional, List

from tqdm import tqdm

from dbdiag.utils.config import load_config
from dbdiag.services.embedding_service import EmbeddingService
from dbdiag.utils.vector_utils import serialize_f32


def init_rar_index(
    db_path: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:
    """
    初始化 RAR 索引

    从 raw_tickets 读取数据，生成 embedding 后写入 rar_raw_tickets。

    Args:
        db_path: 数据库路径，默认 data/tickets.db
        config_path: 配置文件路径，默认 config.yaml
    """
    if db_path is None:
        project_root = Path(__file__).parent.parent.parent
        db_path = str(project_root / "data" / "tickets.db")

    if not Path(db_path).exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    print(f"[init-rar-index] 开始初始化 RAR 索引...")
    print(f"数据库: {db_path}")

    # 加载配置和服务
    config = load_config(config_path)
    embedding_service = EmbeddingService(config)

    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. 读取 raw_tickets
        print("\n[1/3] 读取 raw_tickets...")
        cursor.execute("""
            SELECT ticket_id, description, root_cause, solution
            FROM raw_tickets
        """)
        raw_tickets = cursor.fetchall()
        print(f"  共 {len(raw_tickets)} 条工单")

        if not raw_tickets:
            print("  [WARN] 没有数据，跳过初始化")
            return

        # 2. 生成 combined_text 和 embedding
        print("\n[2/3] 生成向量...")
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
        print("\n[3/3] 写入 rar_raw_tickets...")

        # 先清空旧数据（幂等性）
        cursor.execute("DELETE FROM rar_raw_tickets")

        # 插入新数据
        for record, embedding in tqdm(zip(records, embeddings), total=len(records)):
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
        print(f"\n[OK] RAR 索引初始化完成，共 {len(records)} 条记录")

    except Exception as e:
        print(f"[ERROR] 初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_rar_index()
