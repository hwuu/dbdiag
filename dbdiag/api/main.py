"""FastAPI 主应用"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from dbdiag.api.chat import router as chat_router
from dbdiag.api.session import router as session_router
from dbdiag.api.websocket import router as websocket_router
from dbdiag.api.agent_chat import router as agent_chat_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 创建 FastAPI 应用
app = FastAPI(
    title="数据库运维问题诊断助手 API",
    description="基于多假设追踪的数据库问题诊断系统",
    version="0.1.0",
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(session_router, prefix="/api", tags=["session"])
app.include_router(websocket_router, tags=["websocket"])
app.include_router(agent_chat_router, prefix="/api", tags=["agent"])

# 静态文件服务
static_dir = Path(__file__).parent.parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    """根路径 - 返回 Web 控制台"""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "message": "数据库运维问题诊断助手 API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}
