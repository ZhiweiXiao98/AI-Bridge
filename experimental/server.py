"""实验服务 (Experimental Server)

独立 FastAPI 服务，端口 8100，用于验证上下文管理系统
与主服务 :5000 完全隔离，零耦合

启动: uvicorn experimental.server:app --port 8100 --reload
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 路径修正
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.context_manager import ContextManager, ContextConfig
from app.core.llm_provider import create_provider, ProviderConfig
from app.core.conversation_store import ConversationStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
CONV_DIR = Path(__file__).resolve().parent / "conversations"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 数据模型
# ============================================================

class ChatRequest(BaseModel):
    message: str
    include_history: bool = True

class ChatResponse(BaseModel):
    reply: str
    tokens_used: dict

class CreateConversationRequest(BaseModel):
    title: str = "新对话"
    system_prompt: str = ""

class RenameRequest(BaseModel):
    title: str


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(title="Context Manager Experimental Server", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局状态
conv_store: Optional[ConversationStore] = None
llm_provider = None


@app.on_event("startup")
async def startup():
    global conv_store, llm_provider

    config_dict = load_config()

    # 构建 ContextConfig
    ctx_conf = ContextConfig(**config_dict["context"])

    # 初始化对话管理器
    conv_store = ConversationStore(
        storage_dir=str(CONV_DIR),
        config=ctx_conf,
    )

    # 如果没有任何对话，自动创建一个
    if not conv_store.list_conversations():
        system_prompt = """你是一个 AI 编程助手。
- 帮助用户编写、调试、优化代码
- 提供技术建议和最佳实践
- 清晰、简洁地解释概念
"""
        conv_store.create("默认对话", system_prompt=system_prompt)
        logger.info("创建默认对话")
    else:
        # 激活最近的对话
        convs = conv_store.list_conversations()
        conv_store.switch(convs[0]["id"])

    # 初始化 LLM Provider
    llm_provider = create_provider(config_dict)

    logger.info(f"✅ 服务启动完成")
    logger.info(f"   Provider: {config_dict['provider']}")
    logger.info(f"   Model: {config_dict['api']['model']}")
    logger.info(f"   Context Window: {ctx_conf.max_window_tokens} tokens")
    logger.info(f"   对话数: {len(conv_store.list_conversations())}")


def _get_cm() -> ContextManager:
    """获取当前活跃的 ContextManager"""
    if not conv_store or not conv_store.context_manager:
        raise HTTPException(status_code=503, detail="服务未初始化或无活跃对话")
    return conv_store.context_manager


# ============================================================
# 健康检查
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "context-manager-experimental"}


# ============================================================
# 对话管理
# ============================================================

@app.get("/conversations")
async def list_conversations():
    """列出所有对话"""
    if not conv_store:
        raise HTTPException(status_code=503, detail="服务未初始化")
    return {"conversations": conv_store.list_conversations()}


@app.post("/conversations")
async def create_conversation(req: CreateConversationRequest):
    """新建对话"""
    if not conv_store:
        raise HTTPException(status_code=503, detail="服务未初始化")
    system_prompt = req.system_prompt or "你是一个 AI 编程助手。请用中文回复，简洁专业。"
    conv_id = conv_store.create(req.title, system_prompt=system_prompt)
    return {"id": conv_id, "conversations": conv_store.list_conversations()}


@app.post("/conversations/{conv_id}/switch")
async def switch_conversation(conv_id: str):
    """切换对话"""
    if not conv_store:
        raise HTTPException(status_code=503, detail="服务未初始化")
    if not conv_store.switch(conv_id):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    return {"active": conv_id, "conversations": conv_store.list_conversations()}


@app.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    """删除对话"""
    if not conv_store:
        raise HTTPException(status_code=503, detail="服务未初始化")
    if not conv_store.delete(conv_id):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    # 如果删完没有活跃对话，自动创建一个
    if not conv_store.active_id:
        convs = conv_store.list_conversations()
        if convs:
            conv_store.switch(convs[0]["id"])
        else:
            conv_store.create("新对话")
    return {"deleted": conv_id, "conversations": conv_store.list_conversations()}


@app.put("/conversations/{conv_id}/rename")
async def rename_conversation(conv_id: str, req: RenameRequest):
    """重命名对话"""
    if not conv_store:
        raise HTTPException(status_code=503, detail="服务未初始化")
    if not conv_store.rename(conv_id, req.title):
        raise HTTPException(status_code=404, detail=f"对话不存在: {conv_id}")
    return {"id": conv_id, "title": req.title}


# ============================================================
# 聊天
# ============================================================

@app.post("/chat")
async def chat(req: ChatRequest):
    """发送消息，返回 AI 回复"""
    cm = _get_cm()
    cm.add_message("user", req.message)

    # 首条消息自动生成标题
    if conv_store.active_id and len(cm.get_history()) <= 2:
        conv_store.auto_title(conv_store.active_id, req.message)

    messages = cm.build_messages()
    try:
        reply = llm_provider.chat(messages)
        cm.add_message("assistant", reply)
        conv_store.save_current()
        return ChatResponse(reply=reply, tokens_used=cm.get_token_usage())
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式聊天，SSE 返回"""
    cm = _get_cm()
    cm.add_message("user", req.message)

    if conv_store.active_id and len(cm.get_history()) <= 2:
        conv_store.auto_title(conv_store.active_id, req.message)

    messages = cm.build_messages()

    async def generate():
        full_reply = ""
        try:
            async for chunk in llm_provider.stream_chat(messages):
                full_reply += chunk
                payload = json.dumps({"text": chunk}, ensure_ascii=False)
                yield f"data: {payload}" + "\n\n"
            cm.add_message("assistant", full_reply)
            conv_store.save_current()
            usage = cm.get_token_usage()
            done_payload = json.dumps({"done": True, "tokens": usage}, ensure_ascii=False)
            yield f"data: {done_payload}" + "\n\n"
        except Exception as e:
            logger.error(f"流式调用失败: {e}")
            err_payload = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {err_payload}" + "\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ============================================================
# 上下文查看
# ============================================================

@app.get("/history")
async def get_history():
    """查看当前对话历史"""
    cm = _get_cm()
    return {"history": cm.get_history(), "conversation_id": conv_store.active_id}


@app.get("/context/status")
async def context_status():
    """Token 用量和上下文状态"""
    cm = _get_cm()
    return cm.get_token_usage()


@app.get("/context/detail")
async def context_detail():
    """各层记忆的详细内容"""
    cm = _get_cm()
    return {
        "conversation_id": conv_store.active_id,
        "system": {
            "prompt": cm._system_content or "",
            "tokens": cm._system_tokens,
        },
        "long_term": {
            "count": len(cm._long_term_fragments),
            "tokens": cm._long_term_tokens,
            "items": cm._long_term_fragments,
        },
        "working": {
            "count": len(cm._working_memory),
            "tokens": cm._working_tokens,
            "items": cm._working_memory,
        },
        "short_term": {
            "turns": len([m for m in cm.get_history() if m["role"] == "user"]),
            "messages": len(cm.get_history()),
            "tokens": cm._history_tokens,
            "items": cm.get_history(),
        },
        "token_usage": cm.get_token_usage(),
    }


@app.post("/context/clear")
async def context_clear():
    """清空当前对话上下文"""
    cm = _get_cm()
    cm.clear()
    conv_store.save_current()
    return {"status": "cleared", "tokens": cm.get_token_usage()}


@app.post("/config/update")
async def update_config(updates: dict):
    """更新 LLM 配置"""
    if not llm_provider:
        raise HTTPException(status_code=503, detail="服务未初始化")
    llm_provider.update_config(**updates)
    return {"status": "updated", "config": updates}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
