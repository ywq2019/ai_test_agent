"""
RAG 知识库引擎
- 文档分段：按段落/句子，每段 500 字，overlap 100 字
- Embedding：复用大模型配置页的 API Key / URL，走 /v1/embeddings 接口
- 存储：PostgreSQL + pgvector（生产）/ 内存 + 关键词检索（SQLite 开发环境）
- 检索：余弦相似度 Top-K（pgvector）/ TF 关键词匹配（降级）
"""

import asyncio
import json
import re
from typing import List, Optional, Tuple
from loguru import logger


# ── 常量 ──────────────────────────────────────────────────────────────────────
CHUNK_SIZE    = 500   # 每段目标字符数
CHUNK_OVERLAP = 100   # 相邻段重叠字符数
EMBED_DIM     = 1536  # OpenAI text-embedding-3-small / DeepSeek 维度
TOP_K         = 5     # 默认检索返回段数


# ── HTML 清洗 ────────────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    """去除 HTML 标签、CSS 样式、脚本，保留纯文本内容。"""
    if not text:
        return ""
    # 去除 <style>...</style> 和 <script>...</script>
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # 去除所有 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 去除 HTML 实体
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    # 去除 CSS 属性值残留（如 font-size:13px 等）
    text = re.sub(r"[\w-]+\s*:\s*[\w\s,.'\"#%()/-]+;", ' ', text)
    # 合并多余空白行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


# ── 环境检测 ──────────────────────────────────────────────────────────────────
def _is_pg() -> bool:
    from tools.config import settings
    return "postgresql" in settings.DATABASE_URL


# ── 分段 ──────────────────────────────────────────────────────────────────────
def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """按段落优先分段，控制每段长度在 chunk_size ± 50% 之间，相邻段 overlap 字符重叠。"""
    if not text or not text.strip():
        return []

    # 先按双换行切自然段落
    paras = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]

    chunks: List[str] = []
    current = ""

    for para in paras:
        # 单段落超出 chunk_size 时再按句子切
        if len(para) > chunk_size * 1.5:
            sentences = re.split(r'(?<=[。！？.!?])\s*', para)
            for sent in sentences:
                if not sent.strip():
                    continue
                if len(current) + len(sent) <= chunk_size:
                    current += sent
                else:
                    if current:
                        chunks.append(current.strip())
                    # overlap：取上一段末尾
                    tail = current[-overlap:] if len(current) > overlap else current
                    current = tail + sent
            continue

        if len(current) + len(para) + 1 <= chunk_size:
            current = (current + "\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current.strip())
            tail = current[-overlap:] if len(current) > overlap else current
            current = (tail + "\n" + para).strip() if tail else para

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if len(c) >= 30]  # 过滤过短碎片


# ── Embedding ────────────────────────────────────────────────────────────────
async def get_embeddings(texts: List[str]) -> Optional[List[List[float]]]:
    """调用大模型配置页的 API 获取文本向量，走 /v1/embeddings 接口。
    返回 None 表示接口不支持或配置缺失，调用方应降级为关键词检索。
    """
    if not texts:
        return []
    from tools.config import settings
    import httpx

    api_key = settings.AI_API_KEY
    base_url = settings.AI_API_URL.rstrip("/")
    if not api_key or not base_url:
        logger.warning("RAG: AI_API_KEY 或 AI_API_URL 未配置，跳过 embedding")
        return None

    # Anthropic 不支持 /v1/embeddings，自动跳过
    if "anthropic.com" in base_url:
        logger.info("RAG: Anthropic API 不支持 embeddings，使用关键词检索降级")
        return None

    url = f"{base_url}/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 分批请求（每批最多 20 条，避免超限）
    batch_size = 20
    all_vectors: List[List[float]] = []

    try:
        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                # 优先用 text-embedding-3-small，若 model 本身支持 embedding 则跟随配置
                embed_model = "text-embedding-3-small"
                payload = {"model": embed_model, "input": batch}
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                vectors = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                all_vectors.extend(vectors)
        return all_vectors
    except Exception as e:
        logger.warning(f"RAG: embedding 请求失败 ({e})，使用关键词检索降级")
        return None


# ── 存储 ──────────────────────────────────────────────────────────────────────
async def index_document(
    source_id: int,
    source_type: str,
    text: str,
    db=None,
) -> int:
    """将文档分段并存入 document_chunks 表。返回写入的段数。
    同一 source_id + source_type 的旧记录先删除（重建索引）。
    """
    chunks = split_text(clean_text(text))
    if not chunks:
        return 0

    # 获取向量（失败则 None，降级为关键词检索）
    vectors = await get_embeddings(chunks)

    from tools.database import DocumentChunk, async_session_maker
    from sqlalchemy import delete

    async with (db or async_session_maker()) as session:
        # 删除旧索引
        await session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.source_id == source_id,
                DocumentChunk.source_type == source_type,
            )
        )

        # 写入新分段
        for i, chunk in enumerate(chunks):
            vec = vectors[i] if vectors else None
            embedding_val = None
            if vec is not None and _is_pg():
                embedding_val = vec  # pgvector 直接存 list[float]
            session.add(DocumentChunk(
                source_id=source_id,
                source_type=source_type,
                chunk_index=i,
                content=chunk,
                embedding=embedding_val,
            ))

        await session.commit()

    logger.info(f"RAG: indexed {len(chunks)} chunks for {source_type}:{source_id}"
                f"{'(with vectors)' if vectors else '(keyword-only)'}")
    return len(chunks)


# ── 检索 ──────────────────────────────────────────────────────────────────────
async def search_chunks(
    query: str,
    source_id: int,
    source_type: str,
    top_k: int = TOP_K,
    db=None,
) -> List[str]:
    """检索与 query 最相关的文档段落。
    PostgreSQL + 有向量：余弦相似度。
    SQLite / 无向量：TF 关键词匹配降级。
    返回空列表表示无可用索引，调用方应回退到原始截断逻辑。
    """
    from tools.database import DocumentChunk, async_session_maker
    from sqlalchemy import select

    async with (db or async_session_maker()) as session:
        result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.source_id == source_id,
                DocumentChunk.source_type == source_type,
            ).order_by(DocumentChunk.chunk_index)
        )
        chunks = result.scalars().all()

    if not chunks:
        return []

    # 尝试向量检索
    if _is_pg() and chunks[0].embedding is not None:
        vecs = await get_embeddings([query])
        if vecs:
            q_vec = vecs[0]
            scored = _cosine_rank(q_vec, chunks)
            return [c.content for c in scored[:top_k]]

    # 降级：关键词 TF 匹配
    return _keyword_rank(query, chunks, top_k)


def _cosine_rank(q_vec: List[float], chunks) -> list:
    """余弦相似度排序（本地计算，避免额外 SQL）。"""
    import math

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb + 1e-9)

    scored = []
    for c in chunks:
        if c.embedding:
            vec = c.embedding if isinstance(c.embedding, list) else list(c.embedding)
            scored.append((cosine(q_vec, vec), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def _keyword_rank(query: str, chunks, top_k: int) -> List[str]:
    """简单 TF 关键词匹配降级。"""
    keywords = set(re.findall(r'[一-龥a-zA-Z0-9]+', query.lower()))
    scored = []
    for c in chunks:
        text_lower = c.content.lower()
        score = sum(text_lower.count(kw) for kw in keywords)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    # 无命中时返回前 top_k 段（保底）
    if not scored:
        return [c.content for c in chunks[:top_k]]
    return [c.content for _, c in scored[:top_k]]


# ── 便捷函数：删除索引 ────────────────────────────────────────────────────────
async def delete_index(source_id: int, source_type: str, db=None) -> None:
    from tools.database import DocumentChunk, async_session_maker
    from sqlalchemy import delete
    async with (db or async_session_maker()) as session:
        await session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.source_id == source_id,
                DocumentChunk.source_type == source_type,
            )
        )
        await session.commit()
