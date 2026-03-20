#!/usr/bin/env python3
"""
LJ Archiver MCP Server — позволяет AI-ассистентам архивировать LiveJournal.

Запуск:
  pip install mcp[cli] requests lxml beautifulsoup4
  python lj_mcp_server.py                    # stdio (для Claude Code)
  mcp dev lj_mcp_server.py                   # MCP Inspector (отладка)

Подключение в Claude Desktop (claude_desktop_config.json):
  {
    "mcpServers": {
      "livejournal": {
        "command": "python",
        "args": ["path/to/lj_mcp_server.py"]
      }
    }
  }
"""

import json
import os
import re
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

from mcp.server.fastmcp import FastMCP

# Импортируем функции из основного скрипта
from lj_archiver import (
    HTTP,
    collect_post_ids,
    fetch_post_content,
    fetch_comments,
    download_images_for_post,
    apply_image_cache,
    export_xml,
    process_lj,
    generate_index,
    generate_post_html,
    build_tree,
    _find_max_depth,
)

mcp = FastMCP("livejournal_mcp")

DEFAULT_ARCHIVE_DIR = "./archive"


# ─── Модели ввода ───────────────────────────────────────────────────────────

class ListPostsInput(BaseModel):
    """Параметры для получения списка постов."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    journal: str = Field(..., description="Имя журнала ЖЖ (например 'varandej')", min_length=1, max_length=50)
    count: int = Field(default=20, description="Количество постов (новые первые)", ge=1, le=500)


class GetPostInput(BaseModel):
    """Параметры для получения конкретного поста."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    journal: str = Field(..., description="Имя журнала ЖЖ", min_length=1, max_length=50)
    ditemid: int = Field(..., description="ID поста (ditemid)")
    include_comments: bool = Field(default=True, description="Загрузить комментарии")


class ArchiveInput(BaseModel):
    """Параметры для архивации постов."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    journal: str = Field(..., description="Имя журнала ЖЖ", min_length=1, max_length=50)
    range_start: int = Field(default=0, description="Начало диапазона (0 = самый свежий)", ge=0)
    range_end: int = Field(default=9, description="Конец диапазона включительно", ge=0)
    post_ids: Optional[str] = Field(default=None, description="Конкретные ditemid через запятую (вместо диапазона)")
    download_images: bool = Field(default=True, description="Скачивать картинки из постов")
    download_comments: bool = Field(default=True, description="Скачивать комментарии")
    output_dir: str = Field(default=DEFAULT_ARCHIVE_DIR, description="Папка для архива")


class ExportXmlInput(BaseModel):
    """Параметры для XML-экспорта."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    journal: str = Field(..., description="Имя журнала (должен быть уже скачан)", min_length=1, max_length=50)
    output_dir: str = Field(default=DEFAULT_ARCHIVE_DIR, description="Папка архива")


class SearchArchiveInput(BaseModel):
    """Параметры для поиска по скачанному архиву."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    journal: str = Field(..., description="Имя журнала", min_length=1, max_length=50)
    query: str = Field(..., description="Текст для поиска (в заголовках и телах постов)", min_length=1)
    output_dir: str = Field(default=DEFAULT_ARCHIVE_DIR, description="Папка архива")


# ─── Инструменты ────────────────────────────────────────────────────────────

@mcp.tool(
    name="lj_list_posts",
    annotations={
        "title": "Список постов журнала ЖЖ",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def lj_list_posts(params: ListPostsInput) -> str:
    """Получает список постов из журнала LiveJournal. Возвращает ID и заголовки,
    отсортированные от новых к старым. Не скачивает контент — только обнаружение.

    Args:
        params: journal (имя журнала), count (количество, по умолчанию 20)

    Returns:
        JSON со списком постов: ditemid, url
    """
    http = HTTP(delay=1.0)
    try:
        ids = collect_post_ids(http, params.journal, max_count=params.count)
        posts = [
            {"ditemid": int(did), "url": f"https://{params.journal}.livejournal.com/{did}.html"}
            for did in ids
        ]
        return json.dumps({
            "journal": params.journal,
            "count": len(posts),
            "posts": posts,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool(
    name="lj_get_post",
    annotations={
        "title": "Получить пост ЖЖ с комментариями",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def lj_get_post(params: GetPostInput) -> str:
    """Загружает конкретный пост из LiveJournal: заголовок, тело, теги.
    Опционально загружает все комментарии включая свёрнутые ветки.

    Args:
        params: journal, ditemid, include_comments

    Returns:
        JSON с данными поста и комментариями
    """
    http = HTTP(delay=1.0)
    try:
        content = fetch_post_content(http, params.journal, params.ditemid)
        if not content:
            return f"Ошибка: пост {params.ditemid} не найден или недоступен."

        result = {
            "ditemid": params.ditemid,
            "subject": content.get("subject", ""),
            "body_length": len(content.get("body", "")),
            "body_preview": re.sub(r"<[^>]+>", "", content.get("body", ""))[:500],
            "tags": content.get("tags", []),
            "images": len(re.findall(r"<img", content.get("body", ""), re.I)),
        }

        if params.include_comments:
            comments = fetch_comments(http, params.journal, params.ditemid)
            result["comments_count"] = len(comments)
            result["comments_preview"] = [
                {
                    "id": c["dtalkid"],
                    "author": c.get("username", ""),
                    "parent": c.get("parent_dtalkid", 0),
                    "preview": re.sub(r"<[^>]+>", "", c.get("body", ""))[:100],
                    "deleted": c.get("deleted", False),
                }
                for c in comments[:20]
            ]
            if len(comments) > 20:
                result["comments_note"] = f"Показано 20 из {len(comments)}. Архивируйте пост для полной версии."

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool(
    name="lj_archive_posts",
    annotations={
        "title": "Архивировать посты ЖЖ на диск",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def lj_archive_posts(params: ArchiveInput) -> str:
    """Скачивает посты из LiveJournal на диск: контент, комментарии, картинки.
    Генерирует офлайн-HTML с поиском и навигацией.
    Поддерживает resume — прерванная загрузка продолжится с того же места.

    Args:
        params: journal, range_start, range_end (или post_ids), download_images, download_comments

    Returns:
        Отчёт: сколько постов, комментариев, картинок скачано
    """
    journal = params.journal.lower().strip()
    outdir = os.path.join(params.output_dir, journal)
    os.makedirs(outdir, exist_ok=True)
    http = HTTP(delay=1.0)

    try:
        # Определяем ID
        if params.post_ids:
            ids = [i.strip() for i in params.post_ids.split(",")]
        else:
            all_ids = collect_post_ids(http, journal, max_count=params.range_end + 1)
            ids = all_ids[params.range_start : params.range_end + 1]

        posts = {}
        total_comments = 0
        total_images = 0

        for i, did_str in enumerate(ids):
            did = int(did_str)
            post_dir = os.path.join(outdir, "posts", did_str)
            os.makedirs(post_dir, exist_ok=True)

            # Контент
            content = fetch_post_content(http, journal, did)
            if content:
                posts[did_str] = {
                    "ditemid": did, "itemid": did // 256, "anum": did % 256,
                    "url": f"https://{journal}.livejournal.com/{did}.html",
                    "security": "public", "mood": "", "music": "",
                    "comments": [], "comments_count": 0,
                    **content,
                }
            else:
                posts[did_str] = {
                    "ditemid": did, "subject": "", "body": "", "date": "",
                    "url": f"https://{journal}.livejournal.com/{did}.html",
                    "security": "public", "tags": [], "mood": "", "music": "",
                    "comments": [], "comments_count": 0,
                }

            post = posts[did_str]

            # Комментарии
            if params.download_comments:
                comments = fetch_comments(http, journal, did)
                post["comments"] = comments
                post["comments_count"] = len(comments)
                total_comments += len(comments)

            # Картинки
            if params.download_images:
                cache = download_images_for_post(http, post, post_dir)
                apply_image_cache(post, cache)
                total_images += len(cache)

            # LJ-теги
            post["body"] = process_lj(post.get("body", ""))
            for c in post.get("comments", []):
                c["body"] = process_lj(c.get("body", ""))

        # HTML
        ordered = [posts[d] for d in ids if d in posts]
        generate_index(ordered, journal, outdir)
        for i, post in enumerate(ordered):
            did = post["ditemid"]
            post_dir = os.path.join(outdir, "posts", str(did))
            os.makedirs(post_dir, exist_ok=True)
            prev_p = ordered[i - 1] if i > 0 else None
            next_p = ordered[i + 1] if i < len(ordered) - 1 else None
            generate_post_html(post, journal, post_dir, prev_p, next_p)

        filled = sum(1 for p in ordered if p.get("body"))

        return json.dumps({
            "status": "ok",
            "journal": journal,
            "posts_total": len(ordered),
            "posts_with_content": filled,
            "comments_total": total_comments,
            "images_downloaded": total_images,
            "archive_path": os.path.abspath(outdir),
            "index_html": os.path.abspath(os.path.join(outdir, "index.html")),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool(
    name="lj_export_xml",
    annotations={
        "title": "Экспорт архива ЖЖ в XML",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def lj_export_xml(params: ExportXmlInput) -> str:
    """Экспортирует уже скачанный архив в XML для импорта на другие платформы.
    Журнал должен быть предварительно скачан через lj_archive_posts.

    Args:
        params: journal, output_dir

    Returns:
        Путь к XML-файлу
    """
    journal = params.journal.lower().strip()
    outdir = os.path.join(params.output_dir, journal)
    json_path = os.path.join(outdir, "archive.json")

    # Пробуем загрузить из JSON если есть
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        posts = data.get("posts", [])
    else:
        # Сканируем папку posts/
        from bs4 import BeautifulSoup
        posts = []
        posts_dir = os.path.join(outdir, "posts")
        if not os.path.isdir(posts_dir):
            return f"Ошибка: архив {journal} не найден в {outdir}. Сначала скачайте через lj_archive_posts."

        for folder in sorted(os.listdir(posts_dir)):
            html_path = os.path.join(posts_dir, folder, f"{folder}.html")
            if not os.path.isfile(html_path):
                continue
            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html = f.read()
                soup = BeautifulSoup(html, "lxml")
                title_el = soup.select_one("h1.post-title")
                body_el = soup.select_one(".post-body")
                posts.append({
                    "ditemid": int(folder),
                    "subject": title_el.get_text(strip=True) if title_el else "",
                    "body": str(body_el) if body_el else "",
                    "date": "",
                    "url": f"https://{journal}.livejournal.com/{folder}.html",
                    "security": "public",
                    "tags": [],
                    "mood": "", "music": "",
                    "comments": [],
                })
            except Exception:
                continue

    if not posts:
        return f"Ошибка: нет постов в архиве {journal}."

    try:
        xml_path = export_xml(posts, journal, outdir)
        return json.dumps({
            "status": "ok",
            "xml_path": os.path.abspath(xml_path),
            "posts_count": len(posts),
            "comments_count": sum(len(p.get("comments", [])) for p in posts),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Ошибка: {e}"


@mcp.tool(
    name="lj_search_archive",
    annotations={
        "title": "Поиск по скачанному архиву ЖЖ",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def lj_search_archive(params: SearchArchiveInput) -> str:
    """Ищет текст в уже скачанном архиве журнала — по заголовкам и телам постов.

    Args:
        params: journal, query, output_dir

    Returns:
        Список найденных постов с контекстом совпадения
    """
    from bs4 import BeautifulSoup

    journal = params.journal.lower().strip()
    posts_dir = os.path.join(params.output_dir, journal, "posts")

    if not os.path.isdir(posts_dir):
        return f"Ошибка: архив {journal} не найден. Сначала скачайте через lj_archive_posts."

    query_lower = params.query.lower()
    results = []

    for folder in sorted(os.listdir(posts_dir), reverse=True):
        html_path = os.path.join(posts_dir, folder, f"{folder}.html")
        if not os.path.isfile(html_path):
            continue
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            text = re.sub(r"<[^>]+>", " ", html)
            text_lower = text.lower()

            if query_lower not in text_lower:
                continue

            soup = BeautifulSoup(html, "lxml")
            title_el = soup.select_one("h1.post-title")
            title = title_el.get_text(strip=True) if title_el else ""

            # Контекст совпадения
            idx = text_lower.find(query_lower)
            start = max(0, idx - 80)
            end = min(len(text), idx + len(params.query) + 80)
            context = text[start:end].strip()

            results.append({
                "ditemid": int(folder),
                "title": title,
                "context": f"...{context}...",
                "url": f"https://{journal}.livejournal.com/{folder}.html",
            })
        except Exception:
            continue

    return json.dumps({
        "journal": journal,
        "query": params.query,
        "results_count": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)


# ─── Запуск ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
