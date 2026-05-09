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

# Lightweight language detection (rough but sufficient)
def detect_lang(text: str) -> str:
    if not text:
        return "zh"
    # Count character ratios across language families
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
    """Synchronously call Qwen for translation; preserve meaning, do not translate proper nouns."""
    if not text or not text.strip():
        return text

    # BASELINE MODE: skip translation, return original text
    import os
    if os.getenv("BASELINE_MODE", "false").lower() == "true":
        return text

    lang_name = LANG_NAMES.get(target_lang, "English")
    # System prompt — kept in Chinese.
    # English translation:
    # "Translate the following text to {lang_name}.
    #  Rules:
    #  1. Output only the translation; no explanation or prefix
    #  2. Keep proper nouns (people names, school names, cities, brands) untranslated
    #  3. Preserve emojis and punctuation
    #  4. Match the tone and style of the original
    #  Source: {text}"
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
        print(f"❌ Translation failed: {e}")
        return text  # return original on failure


class TranslateRequest(BaseModel):
    texts: dict[str, str]   # {"bio": "...", "match_reason": "...", ...}
    target_lang: str         # "en" | "ja" | "ko" | "zh"


class TranslateResponse(BaseModel):
    translated: dict[str, str]
    skipped: list[str]       # fields skipped (same language as target)


@router.post("/", response_model=TranslateResponse)
async def translate_texts(body: TranslateRequest):
    """
    Batch-translate text fields.
    - For each field, detect language; skip if it matches the target language.
    - Otherwise call Qwen for translation.
    - Returns the translated map + a list of skipped field keys.
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
