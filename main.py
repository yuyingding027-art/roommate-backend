from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn

from database import create_tables
from routers import auth, users, matching, chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield

# ... 之前的导入保持不变 ...

app = FastAPI(title="留学生找舍友平台 API", version="1.0.0", lifespan=lifespan)

# --- 修改后的 CORS 配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://uniroomi.lovable.app",   # Lovable 的预览域名
        "http://localhost:5173",          # 本地开发环境常用端口
        "http://localhost:3000",
    ],
    allow_credentials=True,               # 必须为 True，前端才能发送 Token 或 Cookie
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
# -------------------------

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
# ... 后面的代码保持不变 ...
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/users", tags=["用户"])
app.include_router(matching.router, prefix="/api/matching", tags=["匹配"])
app.include_router(chat.router, prefix="/api/chat", tags=["聊天"])

@app.get("/")
async def root():
    return {"message": "留学生找舍友平台 API 运行中"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
