from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
import os
import json
from openai import OpenAI

router = APIRouter()

qwen_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
)

LANG_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}

# 语言检测关键词（粗略判断，够用）
def detect_lang(text: str) -> str:
    if not text:
        return "zh"
    # 统计各语系字符占比
    zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    ja_count = sum(1 for c in text if '\u3040' <= c <= '\u30ff')
    ko_count = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    en_count = sum(1 for c in text if c.isascii() and c.isalpha())
    total = len(text) or 1

    if ja_count / total > 0.1:
        return "ja"
    if ko_count / total > 0.1:
        return "ko"
    if zh_count / total > 0.1:
        return "zh"
    return "en"


def _translate_with_qwen(text: str, target_lang: str) -> str:
    """同步调用 Qwen 翻译，保留原意，不翻译专有名词"""
    if not text or not text.strip():
        return text

    # BASELINE MODE: 不翻译，原文返回
    import os
    if os.getenv("BASELINE_MODE", "false").lower() == "true":
        return text

    lang_name = LANG_NAMES.get(target_lang, "English")
    prompt = (
        f"请将以下文本翻译成{lang_name}。\n"
        "规则：\n"
        "1. 只输出翻译结果，不要任何解释或前缀\n"
        "2. 保留人名、学校名、城市名、品牌名等专有名词不翻译\n"
        "3. 保留emoji和标点符号\n"
        "4. 保持原文的语气和风格\n\n"
        f"原文：{text}"
    )
    try:
        resp = qwen_client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ 翻译失败: {e}")
        return text  # 失败返回原文


class TranslateRequest(BaseModel):
    texts: dict[str, str]   # {"bio": "...", "match_reason": "...", ...}
    target_lang: str         # "en" | "ja" | "ko" | "zh"


class TranslateResponse(BaseModel):
    translated: dict[str, str]
    skipped: list[str]       # 与目标语言相同、跳过翻译的字段


@router.post("/", response_model=TranslateResponse)
async def translate_texts(body: TranslateRequest):
    """
    批量翻译文本字段。
    - 检测每个字段的语言，与目标语言相同则跳过
    - 不同则调用 Qwen 翻译
    - 返回翻译结果 + 跳过的字段列表
    """
    if body.target_lang not in LANG_NAMES:
        raise HTTPException(status_code=400, detail=f"不支持的语言: {body.target_lang}")

    translated = {}
    skipped = []

    async def process_field(key: str, text: str):
        if not text or not text.strip():
            translated[key] = text
            skipped.append(key)
            return

        src_lang = detect_lang(text)
        if src_lang == body.target_lang:
            translated[key] = text
            skipped.append(key)
            return

        result = await asyncio.to_thread(_translate_with_qwen, text, body.target_lang)
        translated[key] = result

    tasks = [process_field(k, v) for k, v in body.texts.items()]
    await asyncio.gather(*tasks)

    return TranslateResponse(translated=translated, skipped=skipped)
