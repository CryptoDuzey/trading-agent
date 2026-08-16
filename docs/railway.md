# Railway 部署(免费起步,GitHub 一键)

Railway 从 GitHub 仓库直接部署,自动识别根目录 `Dockerfile`(单容器:前端 + 后端 + 静态),再挂一个 PostgreSQL。

## 1. 推代码到 GitHub

```bash
cd trading-agent
git init   # 已是 git 仓库则跳过
git add -A
git commit -m "init"
# 在 GitHub 新建私有仓库,然后:
git remote add origin https://github.com/你的用户名/trading-agent.git
git branch -M main
git push -u origin main
```

## 2. Railway 部署

1. 打开 [railway.com](https://railway.com),用 GitHub 账号登录。
2. **New Project → Deploy from GitHub repo** → 授权并选择 `trading-agent` 仓库。
3. Railway 会自动构建根目录 `Dockerfile`(单容器)。
4. 点 **New → Database → PostgreSQL**,给项目加一个数据库,Railway 会自动注入 `DATABASE_URL`。
5. 在服务的 **Variables** 里补一个环境变量:

   ```
   DEEPSEEK_API_KEY=sk-你的密钥
   ```

6. 等待构建 + 部署完成,Railway 会生成一个域名(形如 `xxx.up.railway.app`)。

## 3. 访问

- 免费域名:`https://xxx.up.railway.app`
- 绑定自定义域名:在服务 Settings → Networking → Generate Domain / Custom Domain。

## 4. 注意

1. Railway 免费额度每月有限(约 5 美元或 500 小时),够个人试用;长期用建议充一点或切到 Hobby 计划。
2. `DEEPSEEK_API_KEY` 只写在 Railway Variables,不进代码仓库。
3. 数据库由 Railway 的 PostgreSQL 托管,数据自动持久化,`DATABASE_URL` 自动注入,无需手动配。
4. Binance 行情接口在国内/部分区域可能 451,系统会返回明确错误而不是伪造数据。
5. 想回到国内云服务器自托管,用 [deployment.md](deployment.md) 的 Docker Compose 方案。
