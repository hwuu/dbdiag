"""FastAPI 主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.session import router as session_router

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


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "数据库运维问题诊断助手 API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}
