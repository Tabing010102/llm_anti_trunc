"""
FastAPI 主入口与路由定义
"""
import logging
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager

from app.config import config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时输出配置警告
    config.log_startup_warnings()
    logger.info("🚀 API Relay 启动完成")
    logger.info(f"   - OpenAI 上游: {config.UPSTREAM_OPENAI_BASE_URL}")
    logger.info(f"   - Gemini 上游: {config.UPSTREAM_GEMINI_BASE_URL}")
    logger.info(f"   - Claude 上游: {config.UPSTREAM_CLAUDE_BASE_URL}")
    logger.info(f"   - 抗截断: {'默认启用' if config.ANTI_TRUNCATION_ENABLED_DEFAULT else '默认禁用'}")
    yield
    logger.info("👋 API Relay 关闭")


app = FastAPI(
    title="LLM API Relay with Anti-Truncation",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "llm-api-relay",
        "version": "1.0.0",
        "features": ["openai", "gemini", "claude", "anti-truncation", "transparent-proxy"]
    }


@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "healthy"}


# ==================== OpenAI Compatible API ====================

@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI Chat Completions API"""
    from app.routes import handle_openai_chat_completions
    return await handle_openai_chat_completions(request)


# ==================== Gemini API ====================

@app.post("/v1/models/{model}:generateContent")
async def gemini_generate_content(request: Request, model: str):
    """Gemini generateContent API（非流式）"""
    from app.routes import handle_gemini_generate_content
    return await handle_gemini_generate_content(request, model, is_streaming=False, is_beta=False)


@app.post("/v1/models/{model}:streamGenerateContent")
async def gemini_stream_generate_content(request: Request, model: str):
    """Gemini streamGenerateContent API（流式）"""
    from app.routes import handle_gemini_generate_content
    return await handle_gemini_generate_content(request, model, is_streaming=True, is_beta=False)


@app.post("/v1beta/models/{model}:generateContent")
async def gemini_beta_generate_content(request: Request, model: str):
    """Gemini beta generateContent API（非流式）"""
    from app.routes import handle_gemini_generate_content
    return await handle_gemini_generate_content(request, model, is_streaming=False, is_beta=True)


@app.post("/v1beta/models/{model}:streamGenerateContent")
async def gemini_beta_stream_generate_content(request: Request, model: str):
    """Gemini beta streamGenerateContent API（流式）"""
    from app.routes import handle_gemini_generate_content
    return await handle_gemini_generate_content(request, model, is_streaming=True, is_beta=True)


# ==================== Claude/Anthropic API ====================

@app.post("/v1/messages")
async def claude_messages(request: Request):
    """Claude Messages API"""
    from app.routes import handle_claude_messages
    return await handle_claude_messages(request)
