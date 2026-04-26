# 留学生找舍友平台 — 后端

## 技术栈
- **FastAPI** + **Python 3.12**
- **PostgreSQL** (数据存储)
- **SQLAlchemy async** (ORM)
- **Claude API** (AI匹配)
- **WebSocket** (实时聊天)
- **JWT** (认证)

---

## 本地开发

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，填入你的 PostgreSQL 和 Anthropic API Key
```

### 3. 启动 PostgreSQL（本地）
```bash
# macOS (Homebrew)
brew services start postgresql
createdb roommate_db

# 或用 Docker
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=password -e POSTGRES_DB=roommate_db postgres:16
```

### 4. 运行服务器
```bash
python main.py
```

访问 http://localhost:8000/docs 查看 Swagger 文档

---

## 部署到 Railway（推荐，免费）

1. 在 [railway.app](https://railway.app) 新建项目
2. 添加 PostgreSQL 插件（自动获得 DATABASE_URL）
3. 连接你的 GitHub 仓库
4. 在 Railway 环境变量中设置：
   - `ANTHROPIC_API_KEY` = 你的Claude API Key
   - `SECRET_KEY` = 随机字符串（至少32位）
   - `DATABASE_URL` = Railway自动注入（格式需改为 `postgresql+asyncpg://...`）
5. 部署完成后获得域名如 `https://your-app.railway.app`

---

## API 端点一览

### 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/register | 注册 |
| POST | /api/auth/login | 登录，获取JWT |

### 用户
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/users/profile | 创建/更新资料 |
| GET  | /api/users/profile/me | 查看自己资料 |
| GET  | /api/users/profile/{id} | 查看他人资料 |

### 匹配
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | /api/matching/ | 获取匹配列表（降序） |
| GET  | /api/matching/?refresh=true | 强制重新计算 |

### 聊天
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/chat/send | 发送消息 |
| GET  | /api/chat/history/{partner_id} | 获取聊天记录 |
| GET  | /api/chat/conversations | 会话列表 |
| POST | /api/chat/share-contact | 分享微信/WhatsApp |
| WS   | /api/chat/ws/{jwt_token} | WebSocket实时连接 |

---

## 匹配算法说明

```
总分 = 规则分×40% + AI分×40% + 性格分×20%
```

**规则分（0-100）**
- 同校同城：必须满足（否则0分）
- 作息相同 +20分
- 饮食习惯相同 +15-20分
- 预算区间有重叠 +20分
- 同住经历相近 +0-10分

**AI分（0-100）**
- 调用Claude分析两人的bio/兴趣爱好文本
- 判断兴趣契合度、生活方式相容度、性格互补性

**性格分（0-100）**
- 基于MBTI兼容性表
- 基于星座相合表
- 两者叠加

---

## 与 Lovable 前端对接

在 Lovable 项目中，所有 API 请求需要：
1. 登录后将 JWT token 存入 localStorage
2. 每次请求带上 Header：`Authorization: Bearer <token>`

```javascript
// Lovable 中的示例代码
const API_BASE = "https://your-app.railway.app"

// 登录
const res = await fetch(`${API_BASE}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password, name: "" })
})
const { access_token } = await res.json()
localStorage.setItem("token", access_token)

// 带认证的请求
const matches = await fetch(`${API_BASE}/api/matching/`, {
  headers: { "Authorization": `Bearer ${localStorage.getItem("token")}` }
}).then(r => r.json())

// WebSocket 连接
const ws = new WebSocket(`wss://your-app.railway.app/api/chat/ws/${token}`)
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data)
  // { type: "new_message", from: "uuid", content: "..." }
}
// 发送消息
ws.send(JSON.stringify({ type: "message", to: "receiver_uuid", content: "你好！" }))
```
