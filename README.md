# Ollama 本地模型工作台

## 启动

进入 `ollama_web_app` 项目目录后运行：

```powershell
python run.py
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 模块

- `main.py`、`__main__.py`：命令行参数和服务启动。
- `server.py`：HTTP 路由、聊天请求及 Ollama 接口。
- `auth.py`：注册、登录和会话认证。
- `chats.py`：聊天记录读写。
- `database.py`：SQLite 初始化与迁移。
- `attachments.py`：PDF、Office 文档解析。
- `config.py`：路径和应用配置。
- `static/openai_chat.html`：网页结构。
- `static/styles.css`：网页样式与浅色/暗黑主题。
- `static/app.js`：前端交互逻辑。

默认监听 `127.0.0.1:8000`，可通过 `--host`、`--port` 和 `--ollama-url`
调整，也支持 `OLLAMA_WEB_HOST`、`OLLAMA_WEB_PORT` 和 `OLLAMA_URL` 环境变量。

## git操作

切换分支 git checkout main

拉取： git pull origin main

提交:
git checkout dev
git pull：在提交代码之前需要先拉取代码

git add .
git add 文件名1 文件名2 …

git commit -m ""
git commit 文件名 -m “提交代码备注”

推送：git push origin main

合并代码 git merge main

检查一下是否合并成功，是否有冲突 git status

查看分支 git branch

git branch -a