"""
Done Marker 指令注入模块
"""
import logging
from typing import Dict, Any
import copy

from app.config import config

logger = logging.getLogger(__name__)


def inject_done_marker_instruction_openai(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    为 OpenAI 格式注入 done marker 指令
    
    在 messages 最前插入或合并 system 消息
    
    Args:
        body: 原始请求 body
        
    Returns:
        注入后的 body（新字典，不修改原字典）
    """
    body = copy.deepcopy(body)
    
    instruction = (
        f"重要：当你完成回答后，请在最后单独一行输出 {config.ANTI_TRUNCATION_DONE_MARKER}（不要有其他字符）。"
        f"这是一个完成标记，用于确认你的回答已经完整输出。"
    )
    
    messages = body.get("messages", [])
    
    # 检查是否已有 system 消息
    if messages and messages[0].get("role") == "system":
        # 合并到已有 system
        existing_content = messages[0].get("content", "")
        messages[0]["content"] = f"{instruction}\n\n{existing_content}"
        logger.debug("OpenAI: 合并到已有 system 消息")
    else:
        # 在最前插入新 system 消息
        messages.insert(0, {
            "role": "system",
            "content": instruction
        })
        logger.debug("OpenAI: 插入新 system 消息")
    
    body["messages"] = messages
    return body


def inject_done_marker_instruction_gemini(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    为 Gemini 格式注入 done marker 指令
    
    创建或追加到 systemInstruction.parts
    
    Args:
        body: 原始请求 body
        
    Returns:
        注入后的 body（新字典，不修改原字典）
    """
    body = copy.deepcopy(body)
    
    instruction = (
        f"重要：当你完成回答后，请在最后单独一行输出 {config.ANTI_TRUNCATION_DONE_MARKER}（不要有其他字符）。"
        f"这是一个完成标记，用于确认你的回答已经完整输出。"
    )
    
    # 获取或创建 systemInstruction
    system_instruction = body.get("systemInstruction", {})
    parts = system_instruction.get("parts", [])
    
    # 追加新的 text part
    parts.insert(0, {"text": instruction})
    
    system_instruction["parts"] = parts
    body["systemInstruction"] = system_instruction
    
    logger.debug("Gemini: 注入到 systemInstruction.parts")
    return body


def inject_done_marker_instruction_claude(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    为 Claude 格式注入 done marker 指令
    
    创建或追加到顶层 system
    
    Args:
        body: 原始请求 body
        
    Returns:
        注入后的 body（新字典，不修改原字典）
    """
    body = copy.deepcopy(body)
    
    instruction = (
        f"重要：当你完成回答后，请在最后单独一行输出 {config.ANTI_TRUNCATION_DONE_MARKER}（不要有其他字符）。"
        f"这是一个完成标记，用于确认你的回答已经完整输出。"
    )
    
    # 获取已有 system（可能是 string 或 array of blocks）
    existing_system = body.get("system", "")
    
    if isinstance(existing_system, str):
        # 如果是字符串，追加
        body["system"] = f"{instruction}\n\n{existing_system}" if existing_system else instruction
        logger.debug("Claude: 追加到 system string")
    elif isinstance(existing_system, list):
        # 如果是 blocks，插入新 text block
        existing_system.insert(0, {
            "type": "text",
            "text": instruction
        })
        body["system"] = existing_system
        logger.debug("Claude: 插入到 system blocks")
    else:
        # 创建新 system
        body["system"] = instruction
        logger.debug("Claude: 创建新 system")
    
    return body


def inject_continuation_openai(
    body: Dict[str, Any],
    collected_text: str,
    continuation_prompt: str
) -> Dict[str, Any]:
    """
    为 OpenAI 格式注入续写上下文
    
    Args:
        body: 原始请求 body
        collected_text: 已收集的文本
        continuation_prompt: 续写提示
        
    Returns:
        注入后的 body
    """
    body = copy.deepcopy(body)
    
    messages = body.get("messages", [])
    
    # 追加 assistant 的历史输出
    messages.append({
        "role": "assistant",
        "content": collected_text
    })
    
    # 追加 user 的续写请求
    messages.append({
        "role": "user",
        "content": continuation_prompt
    })
    
    body["messages"] = messages
    logger.debug(f"OpenAI: 注入续写上下文 ({len(collected_text)} chars)")
    return body


def inject_continuation_gemini(
    body: Dict[str, Any],
    collected_text: str,
    continuation_prompt: str
) -> Dict[str, Any]:
    """
    为 Gemini 格式注入续写上下文
    
    Args:
        body: 原始请求 body
        collected_text: 已收集的文本
        continuation_prompt: 续写提示
        
    Returns:
        注入后的 body
    """
    body = copy.deepcopy(body)
    
    contents = body.get("contents", [])
    
    # 追加 model 的历史输出
    contents.append({
        "role": "model",
        "parts": [{"text": collected_text}]
    })
    
    # 追加 user 的续写请求
    contents.append({
        "role": "user",
        "parts": [{"text": continuation_prompt}]
    })
    
    body["contents"] = contents
    logger.debug(f"Gemini: 注入续写上下文 ({len(collected_text)} chars)")
    return body


def inject_continuation_claude(
    body: Dict[str, Any],
    collected_text: str,
    continuation_prompt: str
) -> Dict[str, Any]:
    """
    为 Claude 格式注入续写上下文
    
    Args:
        body: 原始请求 body
        collected_text: 已收集的文本
        continuation_prompt: 续写提示
        
    Returns:
        注入后的 body
    """
    body = copy.deepcopy(body)
    
    messages = body.get("messages", [])
    
    # 追加 assistant 的历史输出
    messages.append({
        "role": "assistant",
        "content": collected_text
    })
    
    # 追加 user 的续写请求
    messages.append({
        "role": "user",
        "content": continuation_prompt
    })
    
    body["messages"] = messages
    logger.debug(f"Claude: 注入续写上下文 ({len(collected_text)} chars)")
    return body
