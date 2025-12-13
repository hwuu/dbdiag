"""上游数据转换脚本

将上游原始工单数据转换为 example_tickets.json 格式。
支持断点续传：中断后重新运行会跳过已转换的工单。

上游格式:
{
    "流程ID": "...",
    "问题描述": "...",
    "问题根因": "...",
    "恢复方法和规避措施": "...",
    "分析过程": "...",
    ...
}

目标格式:
{
    "ticket_id": "...",
    "metadata": {...},
    "description": "...",
    "root_cause": "...",
    "solution": "...",
    "anomalies": [...]
}
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from tqdm import tqdm

from dbdiag.utils.config import load_config
from dbdiag.services.llm_service import LLMService


# LLM 提取 anomalies 的 Prompt
EXTRACT_ANOMALIES_PROMPT = """你是数据库运维专家。请从以下分析过程中提取异常现象列表。

## 分析过程
{analysis_process}

## 输出要求
请提取所有观察到的异常现象，每个现象包含：
1. description: 异常现象的描述（如"wait_io 事件占比 65%"）
2. observation_method: 观察方法或 SQL 查询（如果有的话）
3. why_relevant: 为什么这个现象与问题相关

输出 JSON 数组格式，示例：
[
  {{
    "description": "wait_io 事件占比 65%",
    "observation_method": "SELECT wait_event_type, wait_event FROM pg_stat_activity",
    "why_relevant": "IO 等待高说明磁盘存在瓶颈"
  }}
]

如果分析过程中没有明确的异常现象，返回空数组 []。
只输出 JSON 数组，不要其他内容。"""

# LLM 推断 metadata 的 Prompt
INFER_METADATA_PROMPT = """你是数据库运维专家。请根据以下工单内容推断元数据。

## 工单内容
问题描述: {description}
根因: {root_cause}
解决方案: {solution}

## 输出要求
请推断以下字段：
1. db_type: 数据库类型（如 PostgreSQL, MySQL, Oracle 等，默认 PostgreSQL）
2. version: 数据库版本（如 14.5，如果无法推断则为空字符串）
3. module: 问题所属模块（如 query_optimizer, connection_pool, replication, vacuum, wal 等）
4. severity: 严重程度（critical/high/medium/low）

输出 JSON 对象格式：
{{
  "db_type": "PostgreSQL",
  "version": "",
  "module": "query_optimizer",
  "severity": "medium"
}}

只输出 JSON 对象，不要其他内容。"""


class CheckpointManager:
    """检查点管理器，支持断点续传"""

    def __init__(self, output_path: str):
        """初始化检查点管理器

        Args:
            output_path: 输出文件路径
        """
        self.output_path = output_path
        self.checkpoint_path = f"{output_path}.checkpoint.json"
        self.completed_ticket_ids: Set[str] = set()
        self.results: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def load(self) -> bool:
        """加载检查点

        Returns:
            是否存在检查点
        """
        if not os.path.exists(self.checkpoint_path):
            return False

        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.completed_ticket_ids = set(data.get("completed_ticket_ids", []))
            self.results = data.get("results", [])
            return True
        except Exception as e:
            print(f"[WARN] 加载检查点失败: {e}")
            return False

    def save(self) -> None:
        """保存检查点"""
        try:
            data = {
                "completed_ticket_ids": list(self.completed_ticket_ids),
                "results": self.results,
            }
            with open(self.checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] 保存检查点失败: {e}")

    async def add_result(self, result: Dict[str, Any]) -> None:
        """添加转换结果（线程安全）

        Args:
            result: 转换后的工单数据
        """
        async with self._lock:
            ticket_id = result.get("ticket_id", "")
            if ticket_id and ticket_id not in self.completed_ticket_ids:
                self.completed_ticket_ids.add(ticket_id)
                self.results.append(result)
                self.save()

    def is_completed(self, ticket_id: str) -> bool:
        """检查工单是否已转换

        Args:
            ticket_id: 工单 ID

        Returns:
            是否已转换
        """
        return ticket_id in self.completed_ticket_ids

    def cleanup(self) -> None:
        """清理检查点文件"""
        if os.path.exists(self.checkpoint_path):
            os.remove(self.checkpoint_path)

    def get_results(self) -> List[Dict[str, Any]]:
        """获取所有结果（按 ticket_id 排序）

        Returns:
            转换结果列表
        """
        return sorted(self.results, key=lambda x: x.get("ticket_id", ""))


class UpstreamConverter:
    """上游数据转换器"""

    def __init__(
        self,
        llm_service: LLMService,
        concurrency: int = 4,
        checkpoint: Optional[CheckpointManager] = None,
    ):
        """初始化转换器

        Args:
            llm_service: LLM 服务实例
            concurrency: 并发数（1-16）
            checkpoint: 检查点管理器（用于断点续传）
        """
        self.llm_service = llm_service
        self.concurrency = max(1, min(16, concurrency))
        self.checkpoint = checkpoint
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def convert_all(
        self,
        upstream_data: List[Dict[str, Any]],
        progress_callback: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """转换所有工单

        Args:
            upstream_data: 上游工单列表
            progress_callback: 进度回调函数 (completed, total)

        Returns:
            转换后的工单列表
        """
        self._semaphore = asyncio.Semaphore(self.concurrency)

        # 过滤已完成的工单（断点续传）
        pending_data = upstream_data
        skipped_count = 0
        if self.checkpoint:
            pending_data = [
                item for item in upstream_data
                if not self.checkpoint.is_completed(item.get("流程ID", ""))
            ]
            skipped_count = len(upstream_data) - len(pending_data)
            if skipped_count > 0:
                print(f"  [断点续传] 跳过已完成: {skipped_count} 条")

        # 创建任务
        tasks = []
        for item in pending_data:
            task = self._convert_one_with_semaphore(item)
            tasks.append(task)

        # 并发执行并收集结果
        completed = skipped_count  # 从已跳过的数量开始
        total = len(upstream_data)

        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None and self.checkpoint:
                await self.checkpoint.add_result(result)
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        # 返回所有结果（包括之前保存的）
        if self.checkpoint:
            return self.checkpoint.get_results()

        # 如果没有 checkpoint，收集本次结果
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                results.append(result)
        results.sort(key=lambda x: x.get("ticket_id", ""))
        return results

    async def _convert_one_with_semaphore(
        self,
        upstream_item: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """带信号量的单条转换"""
        async with self._semaphore:
            return await self._convert_one(upstream_item)

    async def _convert_one(
        self,
        upstream_item: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """转换单条工单

        Args:
            upstream_item: 上游工单数据

        Returns:
            转换后的工单数据，失败返回 None
        """
        try:
            # 直接映射字段
            ticket_id = upstream_item.get("流程ID", "")
            description = upstream_item.get("问题描述", "")
            root_cause = upstream_item.get("问题根因", "")
            solution = upstream_item.get("恢复方法和规避措施", "")
            analysis_process = upstream_item.get("分析过程", "")

            if not ticket_id:
                return None

            # LLM 提取 anomalies
            anomalies = await self._extract_anomalies(analysis_process)

            # LLM 推断 metadata
            metadata = await self._infer_metadata(description, root_cause, solution)

            return {
                "ticket_id": ticket_id,
                "metadata": metadata,
                "description": description,
                "root_cause": root_cause,
                "solution": solution,
                "anomalies": anomalies,
            }

        except Exception as e:
            print(f"[WARN] 转换失败 {upstream_item.get('流程ID', 'unknown')}: {e}")
            return None

    async def _extract_anomalies(
        self,
        analysis_process: str,
    ) -> List[Dict[str, str]]:
        """从分析过程中提取异常现象

        Args:
            analysis_process: 分析过程文本

        Returns:
            异常现象列表
        """
        if not analysis_process or not analysis_process.strip():
            return []

        prompt = EXTRACT_ANOMALIES_PROMPT.format(analysis_process=analysis_process)

        try:
            # 使用线程池执行同步 LLM 调用
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.llm_service.generate,
                prompt,
            )

            # 清理响应
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            elif response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            # 解析 JSON
            anomalies = json.loads(response)
            if not isinstance(anomalies, list):
                return []

            # 验证格式
            valid_anomalies = []
            for a in anomalies:
                if isinstance(a, dict) and "description" in a:
                    valid_anomalies.append({
                        "description": a.get("description", ""),
                        "observation_method": a.get("observation_method", ""),
                        "why_relevant": a.get("why_relevant", ""),
                    })
            return valid_anomalies

        except Exception as e:
            print(f"[WARN] 提取 anomalies 失败: {e}")
            return []

    async def _infer_metadata(
        self,
        description: str,
        root_cause: str,
        solution: str,
    ) -> Dict[str, Any]:
        """推断 metadata

        Args:
            description: 问题描述
            root_cause: 根因
            solution: 解决方案

        Returns:
            metadata 字典
        """
        default_metadata = {
            "db_type": "PostgreSQL",
            "version": "",
            "module": "unknown",
            "severity": "medium",
        }

        if not description and not root_cause:
            return default_metadata

        prompt = INFER_METADATA_PROMPT.format(
            description=description,
            root_cause=root_cause,
            solution=solution,
        )

        try:
            # 使用线程池执行同步 LLM 调用
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.llm_service.generate,
                prompt,
            )

            # 清理响应
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            elif response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            # 解析 JSON
            metadata = json.loads(response)
            if not isinstance(metadata, dict):
                return default_metadata

            # 合并默认值
            return {
                "db_type": metadata.get("db_type", default_metadata["db_type"]),
                "version": metadata.get("version", default_metadata["version"]),
                "module": metadata.get("module", default_metadata["module"]),
                "severity": metadata.get("severity", default_metadata["severity"]),
            }

        except Exception as e:
            print(f"[WARN] 推断 metadata 失败: {e}")
            return default_metadata


def convert_upstream_data(
    upstream_path: str,
    output_path: str,
    config_path: Optional[str] = None,
    concurrency: int = 4,
) -> None:
    """转换上游数据（支持断点续传）

    Args:
        upstream_path: 上游数据文件路径
        output_path: 输出文件路径
        config_path: 配置文件路径
        concurrency: 并发数
    """
    print(f"[convert] 开始转换上游数据...")
    print(f"  输入: {upstream_path}")
    print(f"  输出: {output_path}")
    print(f"  并发: {concurrency}")

    # 加载配置
    config = load_config(config_path)
    llm_service = LLMService(config)

    # 初始化检查点管理器
    checkpoint = CheckpointManager(output_path)
    has_checkpoint = checkpoint.load()
    if has_checkpoint:
        print(f"  [断点续传] 检测到检查点，已完成 {len(checkpoint.completed_ticket_ids)} 条")

    # 读取上游数据
    print(f"\n[1/3] 读取上游数据...")
    with open(upstream_path, "r", encoding="utf-8") as f:
        upstream_data = json.load(f)

    if not isinstance(upstream_data, list):
        raise ValueError("上游数据必须是 JSON 数组")

    print(f"  共 {len(upstream_data)} 条工单")

    # 创建转换器
    converter = UpstreamConverter(llm_service, concurrency, checkpoint)

    # 使用 tqdm 显示进度
    print(f"\n[2/3] 转换工单...")
    pbar = tqdm(total=len(upstream_data), desc="  转换进度", unit="条")

    # 如果有检查点，设置初始进度
    if has_checkpoint:
        pbar.n = len(checkpoint.completed_ticket_ids)
        pbar.refresh()

    def progress_callback(completed: int, total: int):
        pbar.n = completed
        pbar.refresh()

    # 执行异步转换
    results = asyncio.run(converter.convert_all(upstream_data, progress_callback))
    pbar.close()

    print(f"  成功转换: {len(results)} 条")
    print(f"  失败: {len(upstream_data) - len(results)} 条")

    # 写入输出文件
    print(f"\n[3/3] 写入输出文件...")
    output_dir = Path(output_path).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 清理检查点
    checkpoint.cleanup()
    print(f"\n[OK] 转换完成: {output_path}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python -m dbdiag.scripts.convert_upstream <upstream_path> <output_path> [concurrency]")
        sys.exit(1)

    upstream_path = sys.argv[1]
    output_path = sys.argv[2]
    concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    convert_upstream_data(upstream_path, output_path, concurrency=concurrency)
