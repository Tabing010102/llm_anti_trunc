# LLM API Relay with Anti-Truncation

一个支持透明代理真实IP和流式抗截断的多协议 LLM API 中继服务。

## 功能特性

- ✅ **多协议支持**：同时兼容 OpenAI、Gemini、Claude 三套 API
- ✅ **透明代理真实IP**：正确处理 `X-Forwarded-For`/`Forwarded`/`X-Real-IP` 等头部
- ✅ **流式抗截断**：自动检测输出截断并续写，直到完整输出或达到最大次数
- ✅ **完全透传**：默认不修改请求/响应，保留所有未知字段
- ✅ **可配置**：通过环境变量灵活配置所有行为

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境变量

复制 `.env.example` 为 `.env` 并根据需要修改：

```bash
cp .env.example .env
```

### 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 配置说明

### 上游地址

- `UPSTREAM_OPENAI_BASE_URL`: OpenAI 上游地址（默认：`https://api.openai.com`）
- `UPSTREAM_GEMINI_BASE_URL`: Gemini 上游地址（默认：`https://generativelanguage.googleapis.com`）
- `UPSTREAM_CLAUDE_BASE_URL`: Claude 上游地址（默认：`https://api.anthropic.com`）

### 抗截断配置

- `ANTI_TRUNCATION_ENABLED_DEFAULT`: 默认是否启用抗截断（默认：`false`）
- `ANTI_TRUNCATION_MAX_ATTEMPTS`: 最大续写次数（默认：`3`）
- `ANTI_TRUNCATION_DONE_MARKER`: 完成标记（默认：`[done]`）
- `ANTI_TRUNCATION_MODEL_PREFIX`: 模型名前缀触发抗截断（默认：`流式抗截断/`）

### 透明代理/真实IP

- `TRUST_PROXY_HEADERS`: 是否信任代理头（默认：`true`）
- `TRUSTED_PROXY_CIDRS`: 可信代理 CIDR 列表（默认：私网+本机）

⚠️ **安全提示**：如果 Relay 部署在可能被非可信客户端直连的环境，请显式配置 `TRUSTED_PROXY_CIDRS` 为反代/LB 的固定网段！

### HTTP 行为

- `UPSTREAM_TIMEOUT_SECONDS`: 上游请求超时（默认：`60`）
- `UPSTREAM_CONNECT_TIMEOUT_SECONDS`: 上游连接超时（默认：`10`）
- `MAX_BODY_SIZE_MB`: 最大请求体大小（默认：`50`）

## 支持的端点

### OpenAI Compatible

```
POST /v1/chat/completions
```

### Gemini

```
POST /v1/models/{model}:generateContent
POST /v1/models/{model}:streamGenerateContent
POST /v1beta/models/{model}:generateContent
POST /v1beta/models/{model}:streamGenerateContent
```

### Claude/Anthropic

```
POST /v1/messages
```

## 抗截断使用方式

抗截断功能仅对流式响应生效，有三种启用方式（任一满足即可）：

1. **模型名前缀**：将模型名设为 `流式抗截断/{实际模型名}`
2. **请求头**：添加 `X-Anti-Truncation: true`
3. **查询参数**：添加 `?anti_truncation=1`

示例（OpenAI）：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "流式抗截断/gpt-4",
    "messages": [{"role": "user", "content": "写一篇长文章"}],
    "stream": true
  }'
```

## 开发与测试

### 运行测试

```bash
pytest tests/ -v
```

### 项目结构

```
app/
├── __init__.py
├── main.py              # FastAPI 入口与路由
├── config.py            # 配置管理
├── headers.py           # 真实IP与 header 透传
├── upstream.py          # httpx 上游请求
├── anti_truncation.py   # 抗截断逻辑
├── injection.py         # done marker 注入
├── streaming.py         # 流式处理器
├── logging.py           # 日志工具
└── parsers/             # 协议解析器
    ├── __init__.py
    ├── openai_sse.py
    ├── gemini_sse.py
    └── claude_sse.py
tests/                   # 测试用例
```

## License

MIT
