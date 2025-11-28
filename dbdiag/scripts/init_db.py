"""数据库初始化脚本

创建 SQLite 数据库的所有表结构

V2 架构变更：
- 新增原始数据表：raw_tickets, raw_anomalies
- 新增处理后数据表：phenomena, ticket_anomalies
- 保留 V1 表（diagnostic_steps）用于向后兼容，标记为 deprecated
"""
import sqlite3
from pathlib import Path
from typing import Optional


# 数据库 schema SQL
SCHEMA_SQL = """
-- ============================================
-- V2 原始数据表（专家标注的原始数据）
-- ============================================

-- 原始工单表
CREATE TABLE IF NOT EXISTS raw_tickets (
    ticket_id TEXT PRIMARY KEY,
    metadata_json TEXT,                -- JSON: {"version": "...", "module": "...", "severity": "..."}
    description TEXT NOT NULL,         -- 问题描述
    root_cause TEXT NOT NULL,          -- 根因
    solution TEXT NOT NULL,            -- 解决方案
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 原始异常表
CREATE TABLE IF NOT EXISTS raw_anomalies (
    id TEXT PRIMARY KEY,                       -- 格式: {ticket_id}_anomaly_{index}
    ticket_id TEXT NOT NULL,
    anomaly_index INTEGER NOT NULL,            -- 异常在工单中的序号
    description TEXT NOT NULL,                 -- 原始异常描述
    observation_method TEXT NOT NULL,          -- 原始观察方法
    why_relevant TEXT NOT NULL,                -- 原始相关性解释
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES raw_tickets(ticket_id)
);

-- 为 raw_anomalies 创建索引
CREATE INDEX IF NOT EXISTS idx_raw_anomalies_ticket_id ON raw_anomalies(ticket_id);

-- ============================================
-- V2 处理后数据表（聚类标准化后的数据）
-- ============================================

-- 标准现象表（核心表，聚类去重后的标准化现象）
CREATE TABLE IF NOT EXISTS phenomena (
    phenomenon_id TEXT PRIMARY KEY,            -- 格式: P-{序号}，如 P-0001
    description TEXT NOT NULL,                 -- 标准化描述（LLM 生成）
    observation_method TEXT NOT NULL,          -- 标准观察方法（选最佳）
    source_anomaly_ids TEXT NOT NULL,          -- 来源的原始 anomaly IDs（JSON 数组）
    cluster_size INTEGER NOT NULL,             -- 聚类中的异常数量
    embedding BLOB,                            -- 向量表示
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 工单-现象关联表
CREATE TABLE IF NOT EXISTS ticket_anomalies (
    id TEXT PRIMARY KEY,                       -- 格式: {ticket_id}_anomaly_{index}
    ticket_id TEXT NOT NULL,
    phenomenon_id TEXT NOT NULL,               -- 关联的标准现象
    why_relevant TEXT NOT NULL,                -- 该工单上下文中的相关性解释
    raw_anomaly_id TEXT,                       -- 关联的原始异常ID（用于溯源）
    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id),
    FOREIGN KEY (phenomenon_id) REFERENCES phenomena(phenomenon_id),
    FOREIGN KEY (raw_anomaly_id) REFERENCES raw_anomalies(id)
);

-- 为 ticket_anomalies 创建索引
CREATE INDEX IF NOT EXISTS idx_ticket_anomalies_ticket_id ON ticket_anomalies(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_anomalies_phenomenon_id ON ticket_anomalies(phenomenon_id);

-- 现象全文检索虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS phenomena_fts USING fts5(
    phenomenon_id UNINDEXED,
    description,
    observation_method,
    content=phenomena,
    content_rowid=rowid
);

-- 现象全文检索触发器（保持 FTS 同步）
CREATE TRIGGER IF NOT EXISTS phenomena_ai AFTER INSERT ON phenomena BEGIN
    INSERT INTO phenomena_fts(rowid, phenomenon_id, description, observation_method)
    VALUES (new.rowid, new.phenomenon_id, new.description, new.observation_method);
END;

CREATE TRIGGER IF NOT EXISTS phenomena_ad AFTER DELETE ON phenomena BEGIN
    DELETE FROM phenomena_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS phenomena_au AFTER UPDATE ON phenomena BEGIN
    DELETE FROM phenomena_fts WHERE rowid = old.rowid;
    INSERT INTO phenomena_fts(rowid, phenomenon_id, description, observation_method)
    VALUES (new.rowid, new.phenomenon_id, new.description, new.observation_method);
END;

-- ============================================
-- V1 表（保留兼容，标记为 deprecated）
-- ============================================

-- 工单表（V1，保留兼容）
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    metadata_json TEXT NOT NULL,      -- JSON: {"db_type": "...", "version": "...", "module": "...", "severity": "..."}
    description TEXT NOT NULL,        -- 问题描述
    root_cause_id TEXT,               -- 关联根因 ID（V2 新增）
    root_cause TEXT NOT NULL,         -- 根因描述（保留兼容）
    solution TEXT NOT NULL,           -- 解决方案
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (root_cause_id) REFERENCES root_causes(root_cause_id)
);

-- 诊断步骤表（V1，DEPRECATED - 请使用 phenomena 表）
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

-- 全文检索虚拟表（V1，保留兼容）
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

-- ============================================
-- 共享表
-- ============================================

-- 根因表（V2 重构：从 root_cause_patterns 改名）
CREATE TABLE IF NOT EXISTS root_causes (
    root_cause_id TEXT PRIMARY KEY,        -- 格式: RC-{序号}，如 RC-0001
    description TEXT NOT NULL,             -- 根因描述
    solution TEXT,                         -- 典型解决方案（聚合自工单）
    key_phenomenon_ids TEXT,               -- 关键现象 ID 列表（JSON 数组）
    related_ticket_ids TEXT,               -- 相关工单 ID 列表（JSON 数组）
    ticket_count INTEGER NOT NULL DEFAULT 0, -- 支持该根因的工单数量
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
