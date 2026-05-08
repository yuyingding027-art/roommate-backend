from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from database import create_tables
from routers import auth, users, matching, chat, translate, roommates

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield

app = FastAPI(
    title="留学生找舍友平台 API",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,   # ← 加这一行
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(auth.router,       prefix="/api/auth",       tags=["认证"])
app.include_router(users.router,      prefix="/api/users",      tags=["用户"])
app.include_router(matching.router,   prefix="/api/matching",   tags=["匹配"])
app.include_router(chat.router,       prefix="/api/chat",       tags=["聊天"])
app.include_router(translate.router,  prefix="/api/translate",  tags=["翻译"])
app.include_router(roommates.router,  prefix="/api/roommates",  tags=["锁定舍友"])

@app.get("/")
async def root():
    return {"message": "留学生找舍友平台 API 运行中"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
