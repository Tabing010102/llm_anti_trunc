"""
Claude/Anthropic SSE 格式解析器
"""
import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ClaudeSSEParser:
    """Claude/Anthropic Server-Sent Events 解析器"""
    
    @staticmethod
    def parse_chunk(chunk: bytes) -> Tuple[Optional[str], bytes]:
        """
        解析 Claude SSE chunk，提取增量文本
        
        Claude 使用标准 SSE 格式，有不同的事件类型：
        - event: content_block_delta
          data: {"delta":{"text":"文本"}}
        - event: message_delta
        - event: message_stop
        
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
            
            # 检查是否是结束事件
            if "event: message_stop" in text or "event: done" in text:
                logger.debug("Claude: 检测到结束事件")
                return None, chunk
            
            # 解析 SSE（Claude 使用 event: 和 data: 两行）
            lines = text.strip().split("\n")
            event_type = None
            data_json = None
            
            for line in lines:
                line = line.strip()
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_json = line[6:].strip()
            
            # 只处理 content_block_delta 事件
            if event_type == "content_block_delta" and data_json:
                try:
                    data = json.loads(data_json)
                    
                    # 提取 delta.text
                    delta = data.get("delta", {})
                    delta_text = delta.get("text")
                    if delta_text:
                        logger.debug(f"Claude: 提取到文本: {delta_text[:50]}")
                        return delta_text, chunk
                    
                except json.JSONDecodeError as e:
                    logger.debug(f"Claude: JSON 解析失败: {e}")
                    pass
            
            return None, chunk
            
        except Exception as e:
            logger.debug(f"Claude: chunk 解析异常: {e}")
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
            
            # 解析 SSE
            lines = text.strip().split("\n")
            event_type = None
            data_line_idx = None
            
            for idx, line in enumerate(lines):
                line_stripped = line.strip()
                if line_stripped.startswith("event: "):
                    event_type = line_stripped[7:].strip()
                elif line_stripped.startswith("data: "):
                    data_line_idx = idx
            
            # 只处理 content_block_delta 事件
            if event_type == "content_block_delta" and data_line_idx is not None:
                data_line = lines[data_line_idx]
                data_json = data_line[6:].strip()
                
                try:
                    data = json.loads(data_json)
                    
                    # 处理 delta.text
                    delta = data.get("delta", {})
                    if "text" in delta:
                        delta_text = delta["text"]
                        if done_marker in delta_text:
                            # 移除 done marker
                            delta["text"] = delta_text.replace(done_marker, "")
                            logger.debug(f"Claude: 移除 done marker")
                            
                            # 重新序列化
                            new_json = json.dumps(data, ensure_ascii=False)
                            lines[data_line_idx] = f"data: {new_json}"
                            
                            # 重新组装
                            new_text = "\n".join(lines) + "\n\n"
                            return new_text.encode("utf-8")
                    
                except json.JSONDecodeError:
                    pass
            
            return chunk
            
        except Exception as e:
            logger.debug(f"Claude: strip_done_marker 异常: {e}")
            return chunk
