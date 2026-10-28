# TVBox 聚合源 —— 部署与使用手册

目标：把多个大佬的 TVBox 源自动聚合成一个文件，托管到 Cloudflare Pages，
最终给电视提供一个稳定公网地址：

    https://vip.xox.wang/tvbox.json

---

## 项目文件说明

| 文件 | 作用 |
|---|---|
| `fetch_sources.py` | 聚合脚本：抓取→测试→合并点播/直播源→生成 tvbox.json（跨平台 Python） |
| `sources.txt` | 候选源地址清单（每行一个，# 开头为注释；失效源自动跳过不用删） |
| `tvbox.json` | 生成的聚合结果（部署后即为电视读取的文件） |
| `jars/` | 自动下载的播放插件（源里引用的 jar，已本地化） |
| `.github/workflows/update.yml` | GitHub 定时任务：每 6 小时自动重跑聚合脚本并更新 |

---

## 一、本地试运行（可选，验证用）

```bash
python fetch_sources.py
python -m http.server 8000
# 电视配置 http://<本机IP>:8000/tvbox.json
```

---

## 二、部署到 Cloudflare Pages（正式方案）

### 第 1 步：GitHub 创建仓库并上传文件

1. 登录 https://github.com ，点右上角 **+ → New repository**
2. 仓库名随意（如 `tvbox`），**选 Public**（公开），不要初始化 README
3. 创建后，在仓库页面点 **"Add file → Upload files"**
4. 把本文件夹里的全部内容拖上去：`fetch_sources.py`、`sources.txt`、`tvbox.json`、`jars/` 文件夹、`.github/` 文件夹（含 update.yml）
5. 点 **Commit changes** 提交

### 第 2 步：确认 GitHub Actions 能自动跑

1. 仓库页面点 **Actions** 标签
2. 若显示 "I understand my workflows, go ahead and enable them" → 点它启用
3. 点左侧 **Update TVBox Sources** → 右上 **Run workflow** 手动跑一次
4. 等跑完（1-2 分钟），确认 `tvbox.json` 有更新提交

### 第 3 步：Cloudflare Pages 连接仓库

1. 登录 https://dash.cloudflare.com/
2. 左侧选你的域名 **xox.wang** → 左侧菜单找 **Workers 和 Pages**（或 Workers & Pages）
3. 点 **创建** → **Pages** → **连接到 Git**
4. 授权连接你的 GitHub 账号 → 选择刚建的仓库（tvbox）
5. 构建设置：
   - **生产分支**：`main`
   - **框架预设**：选 **None**（不构建）
   - **构建命令**：留空
   - **输出目录**：留空（保持默认 /）
6. 点 **保存并部署**

### 第 4 步：绑定 vip.xox.wang

1. 部署成功后，在 Pages 项目 → **自定义域** → **设置自定义域**
2. 输入 `vip.xox.wang` → 点继续
3. CF 会自动添加 DNS 记录（CNAME）→ 等几秒验证生效
4. 浏览器访问 `https://vip.xox.wang/tvbox.json` 应返回 JSON 内容

### 第 5 步：电视配置

1. 打开 OK影视 / 影视仓
2. 设置 → **配置地址** → 输入：`https://vip.xox.wang/tvbox.json`
3. 保存 → 完成，源永久生效，以后每 6 小时自动更新

---

## 三、日常维护

- **换源**：编辑 `sources.txt` 加地址 → 推到 GitHub → 自动部署（或手动 Run workflow）
- **手动立即更新**：GitHub 仓库 → Actions → Update TVBox Sources → Run workflow
- **源全失效排查**：本地跑 `python fetch_sources.py` 看哪个源通了，把能用的加进 `sources.txt`
