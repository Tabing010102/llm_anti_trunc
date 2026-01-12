"""
抗截断逻辑：启用条件判断、model 前缀处理
"""
import logging
from typing import Dict, Any, Tuple, Optional
from fastapi import Request

from app.config import config

logger = logging.getLogger(__name__)


def should_enable_anti_truncation(
    request: Request,
    request_body: Optional[Dict[str, Any]],
    is_streaming: bool
) -> bool:
    """
    判断是否应该启用抗截断
    
    启用条件（任一满足且必须是流式请求）：
    1. model 以 ANTI_TRUNCATION_MODEL_PREFIX 开头
    2. header X-Anti-Truncation: true
    3. query parameter anti_truncation=1
    
    Args:
        request: FastAPI Request 对象
        request_body: 请求 body（JSON）
        is_streaming: 是否为流式请求
        
    Returns:
        是否启用抗截断
    """
    # 必须是流式请求
    if not is_streaming:
        return False
    
    # 条件 1: model 前缀
    if request_body and "model" in request_body:
        model = request_body.get("model", "")
        if model.startswith(config.ANTI_TRUNCATION_MODEL_PREFIX):
            logger.debug(f"抗截断: 由 model 前缀触发 ({model})")
            return True
    
    # 条件 2: header
    anti_trunc_header = request.headers.get("x-anti-truncation", "").lower()
    if anti_trunc_header == "true":
        logger.debug("抗截断: 由 X-Anti-Truncation header 触发")
        return True
    
    # 条件 3: query parameter
    anti_trunc_query = request.query_params.get("anti_truncation", "")
    if anti_trunc_query == "1":
        logger.debug("抗截断: 由 anti_truncation query 触发")
        return True
    
    return False


def strip_model_prefix(model: str) -> Tuple[str, str]:
    """
    剥离 model 名称中的抗截断前缀
    
    Args:
        model: 原始 model 名称
        
    Returns:
        (剥离后的 model, 原始 model)
    """
    if model.startswith(config.ANTI_TRUNCATION_MODEL_PREFIX):
        stripped = model[len(config.ANTI_TRUNCATION_MODEL_PREFIX):]
        logger.debug(f"剥离 model 前缀: {model} -> {stripped}")
        return stripped, model
    return model, model


def get_continuation_prompt(collected_text: str, attempt: int) -> str:
    """
    生成续写提示
    
    Args:
        collected_text: 已收集的文本
        attempt: 当前尝试次数
        
    Returns:
        续写提示文本
    """
    text_length = len(collected_text)
    # 取最后 100 个字符作为上下文
    tail = collected_text[-100:] if len(collected_text) > 100 else collected_text
    
    prompt = (
        f"请从刚才被截断处继续输出，不要重复已输出的内容。"
        f"你已经输出了 {text_length} 个字符，末尾是：\n{tail}\n\n"
        f"完成后，请在最后单独一行输出 {config.ANTI_TRUNCATION_DONE_MARKER}（不要有其他字符）。"
    )
    
    return prompt
