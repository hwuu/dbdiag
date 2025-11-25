"""数据库初始化脚本

创建 SQLite 数据库的所有表结构
"""
import sqlite3
from pathlib import Path
from typing import Optional


# 数据库 schema SQL
SCHEMA_SQL = """
-- 工单表
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,      -- JSON: {"db_type": "...", "version": "...", "module": "...", "severity": "..."}
    description TEXT NOT NULL,        -- 问题描述
    root_cause TEXT NOT NULL,         -- 根因
    solution TEXT NOT NULL,           -- 解决方案
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 诊断步骤表（核心表）
CREATE TABLE IF NOT EXISTS diagnostic_steps (
    step_id TEXT PRIMARY KEY,              -- 格式: {ticket_id}_step_{index}
    ticket_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,           -- 步骤在工单中的顺序

    -- 步骤内容
    observed_fact TEXT NOT NULL,           -- 观察到的现象
    observation_method TEXT NOT NULL,      -- 具体操作（SQL、命令等）
    analysis_result TEXT NOT NULL,         -- 推理结果

    -- 冗余字段（便于检索）
    ticket_description TEXT NOT NULL,      -- 冗余工单描述
    ticket_root_cause TEXT NOT NULL,       -- 冗余根因

    -- 向量字段（暂时为 NULL，在 rebuild-index 时填充）
    fact_embedding BLOB,                   -- observed_fact 的向量表示
    method_embedding BLOB,                 -- observation_method 的向量表示

    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
);

-- 为 diagnostic_steps 创建索引
CREATE INDEX IF NOT EXISTS idx_diagnostic_steps_ticket_id ON diagnostic_steps(ticket_id);
CREATE INDEX IF NOT EXISTS idx_diagnostic_steps_step_index ON diagnostic_steps(step_index);

-- 全文检索虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS steps_fts USING fts5(
    step_id UNINDEXED,
    observed_fact,
    observation_method,
    analysis_result,
    content=diagnostic_steps,
    content_rowid=rowid
);

-- 全文检索触发器（保持 FTS 同步）
CREATE TRIGGER IF NOT EXISTS diagnostic_steps_ai AFTER INSERT ON diagnostic_steps BEGIN
    INSERT INTO steps_fts(rowid, step_id, observed_fact, observation_method, analysis_result)
    VALUES (new.rowid, new.step_id, new.observed_fact, new.observation_method, new.analysis_result);
END;

CREATE TRIGGER IF NOT EXISTS diagnostic_steps_ad AFTER DELETE ON diagnostic_steps BEGIN
    DELETE FROM steps_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS diagnostic_steps_au AFTER UPDATE ON diagnostic_steps BEGIN
    DELETE FROM steps_fts WHERE rowid = old.rowid;
    INSERT INTO steps_fts(rowid, step_id, observed_fact, observation_method, analysis_result)
    VALUES (new.rowid, new.step_id, new.observed_fact, new.observation_method, new.analysis_result);
END;

-- 根因模式表
CREATE TABLE IF NOT EXISTS root_cause_patterns (
    pattern_id TEXT PRIMARY KEY,
    root_cause TEXT NOT NULL,              -- 根因描述
    key_symptoms TEXT NOT NULL,            -- 关键症状列表（JSON 数组）
    related_step_ids TEXT NOT NULL,        -- 相关步骤 ID 列表（JSON 数组）
    ticket_count INTEGER NOT NULL,         -- 支持该根因的工单数量
    embedding BLOB                         -- 根因的向量表示
);

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_problem TEXT NOT NULL,            -- 用户初始问题描述
    state_json TEXT NOT NULL,              -- 会话状态（JSON）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 为 sessions 创建索引
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);
"""


def init_database(db_path: Optional[str] = None) -> None:
    """
    初始化数据库，创建所有表结构

    Args:
        db_path: 数据库文件路径，默认为 data/tickets.db
    """
    if db_path is None:
        # 默认使用项目根目录下的 data/tickets.db
        # __file__ 是 scripts/init_db.py，parent 是 scripts/，parent.parent 是项目根目录
        project_root = Path(__file__).parent.parent
        data_dir = project_root / "data"
        data_dir.mkdir(exist_ok=True)
        db_path = str(data_dir / "tickets.db")

    print(f"正在初始化数据库: {db_path}")

    # 连接数据库（如果不存在会自动创建）
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 执行 schema SQL
        cursor.executescript(SCHEMA_SQL)
        conn.commit()
        print("[OK] 数据库表结构创建成功")

        # 显示创建的表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        print(f"\n已创建的表 ({len(tables)}):")
        for table in tables:
            print(f"  - {table[0]}")

        # 显示虚拟表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%fts5%'")
        fts_tables = cursor.fetchall()
        if fts_tables:
            print(f"\n全文检索表 ({len(fts_tables)}):")
            for table in fts_tables:
                print(f"  - {table[0]}")

    except Exception as e:
        print(f"[ERROR] 数据库初始化失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"\n数据库初始化完成: {db_path}")


if __name__ == "__main__":
    init_database()
