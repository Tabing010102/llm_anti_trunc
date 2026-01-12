"""
OpenAI SSE 格式解析器
"""
import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class OpenAISSEParser:
    """OpenAI Server-Sent Events 解析器"""
    
    @staticmethod
    def parse_chunk(chunk: bytes) -> Tuple[Optional[str], bytes]:
        """
        解析 OpenAI SSE chunk，提取增量文本
        
        格式: data: {"choices":[{"delta":{"content":"文本"}}]}
        
        Args:
            chunk: 原始字节块
            
        Returns:
            (增量文本或None, 原始chunk)
        """
        try:
            text = chunk.decode("utf-8")
            
            # 跳过空行和注释
            if not text.strip() or text.strip().startswith(":"):
                return None, chunk
            
            # 检查是否是 data: [DONE]
            if "data: [DONE]" in text:
                logger.debug("OpenAI: 检测到 [DONE] 标记")
                return None, chunk
            
            # 解析 SSE
            if text.startswith("data: "):
                json_str = text[6:].strip()
                if not json_str:
                    return None, chunk
                
                try:
                    data = json.loads(json_str)
                    
                    # 提取 choices[].delta.content
                    choices = data.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content")
                        if content:
                            logger.debug(f"OpenAI: 提取到文本: {content[:50]}")
                            return content, chunk
                    
                except json.JSONDecodeError as e:
                    logger.debug(f"OpenAI: JSON 解析失败: {e}")
                    pass
            
            return None, chunk
            
        except Exception as e:
            logger.debug(f"OpenAI: chunk 解析异常: {e}")
            return None, chunk
    
    @staticmethod
    def strip_done_marker(chunk: bytes, done_marker: str) -> bytes:
        """
        从 chunk 中移除 done marker
        
        Args:
            chunk: 原始字节块
            done_marker: 要移除的标记
            
        Returns:
            处理后的 chunk
        """
        try:
            text = chunk.decode("utf-8")
            
            # 检查是否包含 done marker
            if done_marker not in text:
                return chunk
            
            # 如果是 SSE 格式
            if text.startswith("data: "):
                json_str = text[6:].strip()
                try:
                    data = json.loads(json_str)
                    
                    # 处理 choices[].delta.content
                    modified = False
                    choices = data.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        if "content" in delta:
                            content = delta["content"]
                            if done_marker in content:
                                # 移除 done marker
                                delta["content"] = content.replace(done_marker, "")
                                modified = True
                                logger.debug(f"OpenAI: 移除 done marker")
                    
                    if modified:
                        # 重新序列化
                        new_json = json.dumps(data, ensure_ascii=False)
                        new_chunk = f"data: {new_json}\n\n".encode("utf-8")
                        return new_chunk
                    
                except json.JSONDecodeError:
                    pass
            
            return chunk
            
        except Exception as e:
            logger.debug(f"OpenAI: strip_done_marker 异常: {e}")
            return chunk
