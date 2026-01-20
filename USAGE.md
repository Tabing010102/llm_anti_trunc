# 使用说明

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并根据实际情况修改：

```bash
cp .env.example .env
```

关键配置项：

- `UPSTREAM_OPENAI_BASE_URL`: OpenAI 上游地址
- `UPSTREAM_GEMINI_BASE_URL`: Gemini 上游地址
- `UPSTREAM_CLAUDE_BASE_URL`: Claude 上游地址
- `TRUST_PROXY_HEADERS`: 是否信任代理头（默认 `true`）
- `TRUSTED_PROXY_CIDRS`: 可信代理 CIDR 列表（默认私网+本机）
- `ANTI_TRUNCATION_KEEPALIVE_INTERVAL_SECONDS`: 流式 keepalive 间隔秒数（默认 `5`；避免中间层空闲断开）
- `ANTI_TRUNCATION_UPSTREAM_IDLE_TIMEOUT_SECONDS`: 上游开始有输出后连续无数据超时秒数（默认 `30`；超时后触发重试/续写；首个 chunk 到来前不会触发该重试）

### 3. 启动服务

方式一：使用 run.py

```bash
python run.py
```

方式二：使用 uvicorn

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 验证服务

```bash
curl http://localhost:8000/health
```

## 使用示例

### OpenAI API（不启用抗截断）

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

### OpenAI API（启用抗截断 - 方式1：model 前缀）

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

### OpenAI API（启用抗截断 - 方式2：header）

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "X-Anti-Truncation: true" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "写一篇长文章"}],
    "stream": true
  }'
```

### OpenAI API（启用抗截断 - 方式3：query）

```bash
curl -X POST "http://localhost:8000/v1/chat/completions?anti_truncation=1" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "写一篇长文章"}],
    "stream": true
  }'
```

### Gemini API

```bash
# 非流式
curl -X POST "http://localhost:8000/v1/models/gemini-pro:generateContent?key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"role": "user", "parts": [{"text": "你好"}]}]
  }'

# 流式（启用抗截断）
curl -X POST "http://localhost:8000/v1/models/流式抗截断/gemini-pro:streamGenerateContent?key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"role": "user", "parts": [{"text": "写一篇长文章"}]}]
  }'
```

### Claude API

```bash
# 非流式
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-opus-20240229",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 1024
  }'

# 流式（启用抗截断）
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "X-Anti-Truncation: true" \
  -d '{
    "model": "claude-3-opus-20240229",
    "messages": [{"role": "user", "content": "写一篇长文章"}],
    "max_tokens": 4096,
    "stream": true
  }'
```

## 抗截断工作原理

1. **启用条件**（任一满足即可，且必须是流式请求）：
   - model 名以 `流式抗截断/` 开头
   - 请求头 `X-Anti-Truncation: true`
   - 查询参数 `anti_truncation=1`

2. **注入 done marker 指令**：
   - Relay 会在请求中注入一个系统指令，要求模型在完成回答后输出 `[done]`（可配置）

3. **边转发边监测**：
   - 每个 chunk 立刻转发给客户端
   - 同时收集文本内容，检测是否出现 `[done]`
   - 对客户端隐藏 `[done]` 标记

4. **自动续写**：
   - 如果上游流结束但未检测到 `[done]`，则认为被截断
   - 自动发起续写请求，附带已输出内容作为上下文
   - 最多续写 N 次（默认 3 次，可配置）

5. **结束条件**：
   - 检测到 `[done]`：正常结束
   - 达到最大续写次数：强制结束并添加响应头 `X-Anti-Truncation-Max-Attempts-Reached`

## 透明代理真实 IP

Relay 会自动处理以下头部，让上游能拿到最终客户端真实 IP：

- `X-Forwarded-For`: 追加客户端 IP（不覆盖已有）
- `Forwarded`: 追加标准 RFC 7239 格式
- `X-Real-IP`: 设置为客户端真实 IP
- `X-Forwarded-Proto/Host/Port`: 补齐缺失的字段

### 可信代理配置

- `TRUST_PROXY_HEADERS=false`: 不信任任何代理头，直接使用连接 IP
- `TRUST_PROXY_HEADERS=true` + `TRUSTED_PROXY_CIDRS`: 仅信任来自指定网段的代理头

⚠️ **安全提示**：默认配置信任私网和本机，适合内网/本地部署。如果 Relay 部署在公网或可能被非可信客户端直连，请显式配置 `TRUSTED_PROXY_CIDRS` 为反代/LB 的固定网段！

## 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest tests/test_headers.py -v

# 生成覆盖率报告
pytest --cov=app --cov-report=html
```

## 日志与调试

日志字段包含：

- `request_id`: 请求唯一标识
- `path`: 请求路径
- `upstream_url`: 上游 URL
- `anti_truncation_enabled`: 是否启用抗截断
- `client_ip`: 客户端 IP
- `xff`: X-Forwarded-For 值
- `attempt`: 抗截断尝试次数
- `done_marker_found`: 是否找到 done marker
- `collected_chars`: 已收集字符数

响应头包含：

- `X-Request-Id`: 请求 ID
- `X-Anti-Truncation`: 抗截断启用状态（`enabled` / 无）
- `X-Anti-Truncation-Ignored`: 未启用原因（如 `non-streaming`）
- `X-Anti-Truncation-Max-Attempts-Reached`: 达到最大尝试次数标志

## 生产部署建议

### 1. 使用 Docker

创建 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

构建并运行：

```bash
docker build -t llm-api-relay .
docker run -p 8000:8000 --env-file .env llm-api-relay
```

### 2. 使用 Nginx 反向代理

```nginx
upstream relay {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://relay;
        proxy_http_version 1.1;
        
        # 保留原始头
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 流式支持
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
    }
}
```

### 3. 配置可信代理

如果使用 Nginx，配置：

```bash
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_CIDRS=127.0.0.1/32  # Nginx 的 IP
```

### 4. 监控与告警

- 关注 `X-Anti-Truncation-Max-Attempts-Reached` 响应头数量
- 监控平均 attempt 次数
- 关注上游错误率

## 故障排查

### 问题：抗截断未生效

1. 检查是否为流式请求（`stream=true`）
2. 检查是否正确设置了启用条件（model 前缀/header/query）
3. 查看响应头 `X-Anti-Truncation-Ignored` 获取未启用原因

### 问题：上游看不到真实 IP

1. 检查 `TRUST_PROXY_HEADERS` 配置
2. 检查 `TRUSTED_PROXY_CIDRS` 是否包含反代 IP
3. 查看日志中的 `client_ip` 和 `xff` 字段

### 问题：续写次数过多

1. 检查上游模型是否真的输出了 `[done]`
2. 考虑调整 `ANTI_TRUNCATION_MAX_ATTEMPTS`
3. 检查解析器是否正确提取文本

## 许可证

MIT
