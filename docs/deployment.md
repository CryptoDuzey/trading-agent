# 部署指南(国内云服务器)

Trading Agent 用 Docker Compose 一键部署:前端(nginx)、后端(FastAPI)、数据库(PostgreSQL)三个容器。国内推荐阿里云 / 腾讯云轻量应用服务器。

## 1. 准备一台服务器

- 国内云:阿里云、腾讯云、华为云均可;海外可省去域名备案。
- 最低配置:**2 核 4G**、系统 Ubuntu 22.04 / Debian 12。
- 安全组放行:**80**(HTTP)、**443**(HTTPS)、**22**(SSH,建议只对你 IP 开放)。

> 注意:国内服务器上跑 DeepSeek API 调用没问题;但 Binance 公开行情接口在国内可能被墙或返回 451。届时行情工具会返回明确错误(不伪造数据),这是预期行为。

## 2. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
# 国内加速可参考阿里云/腾讯云 Docker 镜像加速文档
docker compose version
```

## 3. 上传代码并配置

```bash
# 把 trading-agent 目录上传到服务器(或用 git clone 你的私有仓库)
cd trading-agent
cp .env.example .env
vim .env
```

`.env` 里必填 / 建议改:

```text
POSTGRES_PASSWORD=一个强密码
DEEPSEEK_API_KEY=sk-你的密钥        # 必填,否则模型不可用
DEEPSEEK_MODEL=deepseek-v4-flash
FEISHU_WEBHOOK_URL=                 # 可选,飞书机器人提醒地址
```

## 4. 启动

```bash
docker compose up -d --build
docker compose ps          # 三个容器都应 running
docker compose logs -f api # 看后端日志,确认 alembic 迁移成功
```

启动后访问 `http://服务器IP:8080`。

## 5. 绑定域名 + HTTPS(推荐)

最简单用 Caddy,自动签 HTTPS 证书(需域名已解析到服务器 IP):

```bash
# 在服务器上装 Caddy,编辑 /etc/caddy/Caddyfile:
#   your-domain.com {
#       reverse_proxy 127.0.0.1:8080
#   }
```

或继续用 nginx + certbot。国内域名需要 ICP 备案后才能用 80/443 访问,海外服务器无需备案。

## 6. 日常运维

```bash
docker compose logs -f api     # 看日志
docker compose restart api     # 重启后端
docker compose down            # 停止(数据卷保留)
docker compose up -d           # 再启动
```

数据存在 `trading_postgres_data` 卷里,`docker compose down` 不会删数据;除非 `down -v`。

## 7. 安全须知

1. **POSTGRES_PASSWORD 一定要改成强密码**,不要用示例值。
2. `DEEPSEEK_API_KEY` 只写在服务器 `.env`,**绝不提交到 git**。
3. 首月只读:系统没有真实下单/提现/转账工具,模拟订单也要人工确认。
4. 如需限制访问,可在 nginx/Caddy 层加 Basic Auth 或只对可信来源开放。
