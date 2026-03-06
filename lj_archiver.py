#!/usr/bin/env python3
"""
LJ Archiver v3.0 — Лучший архиватор LiveJournal.

Структура:
  archive/username/
    index.html
    style.css
    posts/
      123456/
        123456.html
        img_abc123.jpg
        img_def456.jpg
      789012/
        789012.html
        ...

Использование:
  python lj_archiver.py varandej              # все посты
  python lj_archiver.py varandej 0-99         # первые 100 (новые → старые)
  python lj_archiver.py varandej 25-49        # посты 25-49
  python lj_archiver.py varandej --no-images  # без картинок
  python lj_archiver.py varandej --no-comments
  python lj_archiver.py varandej -o ./backup
"""

import argparse, json, re, os, sys, time, hashlib, base64
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Установи зависимости: pip install requests lxml beautifulsoup4")
    sys.exit(1)

import warnings
warnings.filterwarnings("ignore")

UA = "LJArchiver/3.0 (best LJ archiver; respectful bot)"
MAX_RETRIES = 3

# ─── HTTP ───────────────────────────────────────────────────────────────────

class HTTP:
    def __init__(self, delay=1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self.delay = delay
        self._t = 0

    def _wait(self):
        d = time.time() - self._t
        if d < self.delay:
            time.sleep(self.delay - d)
        self._t = time.time()

    def get(self, url, binary=False):
        for a in range(MAX_RETRIES):
            self._wait()
            try:
                r = self.s.get(url, timeout=30)
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 60)))
                    continue
                if r.status_code == 503:
                    time.sleep(5)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.content if binary else r.text
            except Exception as e:
                if a == MAX_RETRIES - 1:
                    return None
                time.sleep(2 ** a)
        return None


# ─── Сбор ID постов ────────────────────────────────────────────────────────

def collect_post_ids(http, journal, max_count=None):
    """Собирает ditemid через HTML-пагинацию главной страницы."""
    print(f"\n📝 Собираю ID постов {journal}...")
    all_ids = []
    skip = 0
    while True:
        html = http.get(f"https://{journal}.livejournal.com/?skip={skip}")
        if not html:
            break
        ids = re.findall(
            rf'https://{re.escape(journal)}\.livejournal\.com/(\d+)\.html',
            html,
        )
        new_count = 0
        for i in ids:
            if i not in all_ids:
                all_ids.append(i)
                new_count += 1
        pct = f" ({len(all_ids)*100//max_count}%)" if max_count else ""
        print(f"  skip={skip}: +{new_count} (всего: {len(all_ids)}{pct})")
        if new_count == 0:
            break
        if max_count and len(all_ids) >= max_count:
            break
        if f"skip={skip + 10}" not in html:
            break
        skip += 10
    # Сортируем: больший ditemid = новее
    all_ids = sorted(set(all_ids), key=lambda x: int(x), reverse=True)
    if max_count:
        all_ids = all_ids[:max_count]
    print(f"  ✅ {len(all_ids)} постов (новые → старые)")
    return all_ids


# ─── Загрузка контента поста ────────────────────────────────────────────────

def fetch_post_content(http, journal, ditemid):
    """Загружает HTML страницы поста и извлекает контент."""
    url = f"https://{journal}.livejournal.com/{ditemid}.html"
    html = http.get(url)
    if not html or len(html) < 10000:
        return None

    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one(".aentry-post__title-text")
    body_el = soup.select_one(".aentry-post__text--view")
    tags_el = soup.select_one(".ljtags")

    if not body_el:
        return None

    return {
        "subject": title_el.get_text(strip=True) if title_el else "",
        "body": str(body_el),
        "tags": [a.get_text(strip=True) for a in tags_el.select("a")] if tags_el else [],
    }


# ─── Комментарии ────────────────────────────────────────────────────────────

def fetch_comments(http, journal, ditemid):
    """Все комментарии через __rpc_get_thread + дозагрузка свёрнутых."""
    all_c = {}
    total_expected = 0
    for page in range(1, 100):
        url = (
            f"https://{journal}.livejournal.com/{journal}/__rpc_get_thread"
            f"?journal={journal}&itemid={ditemid}&expand_all=1&flat=&skip=&page={page}"
        )
        r = http.get(url)
        if not r:
            break
        try:
            data = json.loads(r)
        except (json.JSONDecodeError, TypeError):
            break
        cc = data.get("comments", [])
        if not cc:
            break
        total_expected = data.get("replycount", total_expected)
        new = 0
        for c in cc:
            cid = c.get("dtalkid", 0)
            if cid and cid not in all_c:
                all_c[cid] = _norm_comment(c)
                new += 1
        if total_expected > 0:
            pct = len(all_c) * 100 // max(total_expected, 1)
            print(f"\r    💬 стр.{page}: {len(all_c)}/{total_expected} ({pct}%)", end="", flush=True)
        if new == 0:
            break

    # Дозагрузка свёрнутых
    unloaded = [c for c in all_c.values() if c["loaded"] == 0 and not c["deleted"]]
    if unloaded:
        print(f" + {len(unloaded)} веток", end="", flush=True)
    for i, ul in enumerate(unloaded):
        tid = ul["dtalkid"]
        url = (
            f"https://{journal}.livejournal.com/{journal}/__rpc_get_thread"
            f"?journal={journal}&itemid={ditemid}&thread={tid}&expand_all=1"
        )
        r = http.get(url)
        if not r:
            continue
        try:
            data = json.loads(r)
        except:
            continue
        for nc in data.get("comments", []):
            ncid = nc.get("dtalkid", 0)
            if ncid:
                n = _norm_comment(nc)
                if ncid in all_c and all_c[ncid]["loaded"] == 0 and n["loaded"] == 1:
                    all_c[ncid] = n
                elif ncid not in all_c:
                    all_c[ncid] = n

    print()  # newline after progress
    return list(all_c.values())


def _norm_comment(r):
    return {
        "dtalkid": r.get("dtalkid", 0),
        "username": r.get("uname", "") or "",
        "userpic": r.get("userpic", "") or "",
        "subject": r.get("subject", "") or "",
        "body": r.get("article", "") or r.get("body", "") or "",
        "date": r.get("ctime", "") or "",
        "date_ts": r.get("ctime_ts", 0),
        "parent_dtalkid": r.get("above", 0) or 0,
        "level": r.get("level", 1),
        "loaded": r.get("loaded", 1),
        "deleted": bool(r.get("deleted", 0)),
        "screened": r.get("shown", 1) == 0,
    }


# ─── Картинки ───────────────────────────────────────────────────────────────

def download_images_for_post(http, post, post_dir):
    """Скачивает все картинки поста и комментариев в папку поста."""
    os.makedirs(post_dir, exist_ok=True)
    cache = {}

    # Собираем все URL
    urls = set()
    for m in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', post.get("body", ""), re.I):
        if m.startswith("http"):
            urls.add(m)
    for c in post.get("comments", []):
        # TODO: аватарки комментаторов — тысячи дубликатов.
        # Нужен глобальный кэш (username → файл), не per-post.
        # Пока пропускаем, отображаем только никнеймы.
        for m in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', c.get("body", ""), re.I):
            if m.startswith("http"):
                urls.add(m)

    if not urls:
        return cache

    total = len(urls)
    ok = 0
    fail = 0
    cached = 0
    total_bytes = 0

    for i, url in enumerate(urls, 1):
        h = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = ".jpg"
        for e in [".png", ".gif", ".webp", ".svg", ".jpeg"]:
            if e in url.lower():
                ext = e
                break
        fn = f"img_{h}{ext}"
        fp = os.path.join(post_dir, fn)

        if os.path.exists(fp) and os.path.getsize(fp) > 500:
            cache[url] = fn
            cached += 1
            total_bytes += os.path.getsize(fp)
        else:
            data = http.get(url, binary=True)
            if data and len(data) > 500:
                with open(fp, "wb") as f:
                    f.write(data)
                cache[url] = fn
                ok += 1
                total_bytes += len(data)
            else:
                fail += 1

        pct = i * 100 // total
        mb = total_bytes / 1024 / 1024
        print(f"\r    🖼️  {i}/{total} ({pct}%) | {ok} new, {cached} cached, {fail} fail | {mb:.1f}MB", end="", flush=True)

    print()  # newline after progress
    return cache


def apply_image_cache(post, cache):
    """Заменяет CDN-ссылки на локальные пути."""
    if not cache:
        return
    for url, fn in cache.items():
        post["body"] = post.get("body", "").replace(url, fn)
    for c in post.get("comments", []):
        for url, fn in cache.items():
            c["body"] = c.get("body", "").replace(url, fn)


# ─── LJ-теги ────────────────────────────────────────────────────────────────

def process_lj(h):
    if not h:
        return h
    h = re.sub(r'<lj-cut[^>]*>', '<div class="lj-cut"><details open><summary>▼ Читать дальше</summary>', h, flags=re.I)
    h = h.replace("</lj-cut>", "</details></div>")
    h = re.sub(r'<lj\s+user=["\']?([^"\'>\s]+)["\']?\s*/?>', r'<a href="https://\1.livejournal.com" class="lj-user">@\1</a>', h, flags=re.I)
    h = re.sub(r'<lj-embed[^>]*>.*?</lj-embed>', '<div class="lj-embed">[встроенный контент]</div>', h, flags=re.I | re.S)
    h = re.sub(r'<lj-like\s*/?>', '', h, flags=re.I)
    return h


# ─── Дерево комментариев ────────────────────────────────────────────────────

def build_tree(comments):
    by_id = {}
    roots = []
    for c in comments:
        c["replies"] = []
        cid = c.get("dtalkid", 0)
        if cid:
            by_id[cid] = c
    for c in comments:
        p = c.get("parent_dtalkid", 0)
        if p and p in by_id:
            by_id[p]["replies"].append(c)
        else:
            roots.append(c)
    return roots


# ─── HTML-генерация ─────────────────────────────────────────────────────────

CSS = """:root{--bg:#faf9f6;--text:#2c2c2c;--accent:#2266aa;--border:#e0ddd8;--cbg:#f5f3ef;--hbg:#2c3e50;--ht:#ecf0f1}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Georgia,'Times New Roman',serif;background:var(--bg);color:var(--text);line-height:1.7;font-size:17px}
.container{max-width:900px;margin:0 auto;padding:20px}
.header{background:var(--hbg);color:var(--ht);padding:40px 30px;border-radius:8px;margin-bottom:30px}
.header h1{font-size:1.8em;margin-bottom:10px}.header h1 a{color:var(--ht)}
.header .stats{opacity:.8;font-size:.9em}
.search-box{margin-bottom:20px}
.search-box input{width:100%;padding:10px 15px;border:1px solid var(--border);border-radius:6px;font-size:1em;font-family:inherit;background:#fff}
.search-box input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 2px rgba(34,102,170,.15)}
.post-item{padding:12px 0;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:12px;flex-wrap:nowrap}
.post-date{font-family:monospace;font-size:.85em;color:#888;min-width:90px;flex-shrink:0}
.post-info{flex:1;min-width:0}
.post-title{color:var(--accent);text-decoration:none;font-weight:bold;display:block}.post-title:hover{text-decoration:underline}
.post-snippet{font-size:.85em;color:#777;margin-top:2px;line-height:1.4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.post-meta{font-size:.8em;color:#999;margin-top:2px}
.nav{display:flex;justify-content:space-between;margin-bottom:20px;padding:10px 0;border-bottom:1px solid var(--border)}
.nav a{color:var(--accent);text-decoration:none}.nav a:hover{text-decoration:underline}
article.post{margin-bottom:40px}
.post h1.post-title{font-size:1.6em;margin-bottom:10px;line-height:1.3}
.post .post-meta{color:#888;font-size:.9em;margin-bottom:20px;padding-bottom:15px;border-bottom:1px solid var(--border);width:auto;padding-left:0}
.post-body{font-size:1em;line-height:1.8}
.post-body img{max-width:100%;height:auto;border-radius:4px;margin:10px 0}
.post-body a{color:var(--accent)}
.comments-section{border-top:2px solid var(--border);padding-top:20px;max-width:100vw;margin-left:calc(-50vw + 50%);margin-right:calc(-50vw + 50%);padding-left:20px;padding-right:20px}
.comments-section h2{margin-bottom:20px;font-size:1.2em;max-width:900px}
.comment{background:var(--cbg);border-radius:6px;padding:12px 16px;margin-bottom:10px;border-left:3px solid var(--border)}
.comment-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.comment-userpic{width:36px;height:36px;border-radius:4px;object-fit:cover}
.comment-author a{color:var(--accent);text-decoration:none}
.comment-date{color:#999;font-size:.8em;margin-left:8px}
.comment-subject{font-weight:bold;margin-bottom:4px}
.comment-body{font-size:.95em;line-height:1.6}
.comment-body img{max-width:100%;height:auto}
.deleted,.screened{color:#999;font-style:italic}
.no-comments{color:#999;font-style:italic}
.lj-cut{margin:15px 0}.lj-cut summary{cursor:pointer;color:var(--accent);font-style:italic}
.lj-user{color:var(--accent);font-weight:bold;text-decoration:none}.lj-user:hover{text-decoration:underline}
.lj-embed{background:#f0ede8;padding:10px 15px;border-radius:4px;color:#888;font-style:italic;margin:10px 0}
.post-nav{display:flex;justify-content:space-between;padding:20px 0;margin-top:30px;border-top:1px solid var(--border)}
.post-nav a{color:var(--accent);text-decoration:none;max-width:45%}.post-nav a:hover{text-decoration:underline}
footer{text-align:center;padding:30px;color:#aaa;font-size:.8em}
@media(max-width:600px){body{font-size:15px}.container{padding:10px}.comment{margin-left:0!important}.post-item{flex-direction:column;gap:4px}.post-meta{padding-left:0}}"""


def _find_max_depth(comments, depth=0):
    """Находит максимальную глубину дерева комментариев."""
    if not comments:
        return depth
    return max(_find_max_depth(c.get("replies", []), depth + 1) for c in comments)


def _gen_comment_css(max_depth):
    """Генерирует CSS-классы .c0 ... .cN с нелинейными отступами."""
    if max_depth <= 0:
        return ""
    base = min(700 / max(max_depth, 1), 50)
    decay = 1.0 / max(max_depth * 0.4, 1)
    rules = []
    total = 0
    for d in range(max_depth + 1):
        if d > 0:
            step = max(2, base / (1 + d * decay))
            total += step
        rules.append(f".c{d}{{margin-left:{int(total)}px}}")
    return "<style>" + "\n".join(rules) + "</style>"


def render_tree(cc, depth=0):
    """Рендерит дерево как ПЛОСКИЙ список div'ов. Без вложенности.
    Уровень задаётся CSS-классом, родитель — в data-parent."""
    if not cc:
        return ""
    h = ""
    for c in cc:
        body = '<em class="deleted">[удалён]</em>' if c.get("deleted") else (
            '<em class="screened">[скрыт]</em>' if c.get("screened") else c.get("body", ""))
        u = c.get("username", "") or "Аноним"
        subj = f'<div class="comment-subject">{c["subject"]}</div>' if c.get("subject") else ""
        dtalkid = c.get("dtalkid", 0)
        parent = c.get("parent_dtalkid", 0)
        h += f'''<div class="comment c{depth}" data-id="{dtalkid}" data-parent="{parent}">
<div class="comment-header"><div class="comment-meta">
<strong class="comment-author"><a href="https://{u}.livejournal.com" target="_blank">{u}</a></strong>
<span class="comment-date">{c.get("date", "")}</span></div></div>
{subj}<div class="comment-body">{body}</div></div>
{render_tree(c.get("replies", []), depth + 1)}'''
    return h


def page_wrap(title, body, journal, css_path="style.css"):
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — {journal}</title>
<link rel="stylesheet" href="{css_path}"></head>
<body><div class="container">{body}</div>
<footer>Архив: <strong>LJ Archiver v3.0</strong></footer></body></html>'''


def _extract_snippet(body_html, max_len=120):
    """Извлекает первое предложение из HTML тела поста."""
    if not body_html:
        return ""
    text = re.sub(r'<[^>]+>', ' ', body_html)
    text = re.sub(r'\s+', ' ', text).strip()
    # Первое предложение
    m = re.match(r'(.{20,}?[.!?])\s', text)
    if m:
        snippet = m.group(1)
    else:
        snippet = text
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(' ', 1)[0] + '…'
    return snippet


def generate_index(current_posts, journal, outdir):
    """Генерирует index.html со ВСЕМИ скачанными постами (включая предыдущие запуски)."""
    # Собираем текущие посты в dict
    posts_dict = {}
    for p in current_posts:
        posts_dict[str(p["ditemid"])] = p

    # Сканируем папку posts/ на предыдущие загрузки
    posts_dir = os.path.join(outdir, "posts")
    if os.path.isdir(posts_dir):
        for folder_name in os.listdir(posts_dir):
            if folder_name in posts_dict:
                continue
            html_path = os.path.join(posts_dir, folder_name, f"{folder_name}.html")
            if not os.path.isfile(html_path):
                continue
            # Парсим заголовок и тело из сохранённого HTML
            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html = f.read()
                soup = BeautifulSoup(html, "lxml")
                title_el = soup.select_one("h1.post-title")
                body_el = soup.select_one(".post-body")
                subject = title_el.get_text(strip=True) if title_el else ""
                body = str(body_el) if body_el else ""
                # Дату и комментарии из мета
                meta_el = soup.select_one(".post-meta")
                date_str = ""
                if meta_el:
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', meta_el.get_text())
                    if m:
                        date_str = m.group(1)
                comment_count = 0
                cm = re.search(r'Комментарии\s*\((\d+)\)', html)
                if cm:
                    comment_count = int(cm.group(1))

                posts_dict[folder_name] = {
                    "ditemid": int(folder_name),
                    "subject": subject,
                    "body": body,
                    "date": date_str,
                    "tags": [],
                    "comments": [None] * comment_count,  # placeholder for count
                }
            except Exception:
                continue

    # Сортируем все посты: новые сверху
    all_posts = sorted(posts_dict.values(), key=lambda p: p.get("ditemid", 0), reverse=True)

    items = ""
    for p in all_posts:
        d = p.get("date", "")[:10]
        s = p.get("subject") or "(без темы)"
        snippet = _extract_snippet(p.get("body", ""))
        t = ", ".join(p.get("tags", []))
        cc = len(p.get("comments", []))
        did = p["ditemid"]
        snippet_html = f'<div class="post-snippet">{snippet}</div>' if snippet else ""
        items += (
            f'<div class="post-item">'
            f'<span class="post-date">{d}</span>'
            f'<div class="post-info">'
            f'<a href="posts/{did}/{did}.html" class="post-title">{s}</a>'
            f'{snippet_html}'
            f'<span class="post-meta">💬 {cc}{f" | 🏷️ {t}" if t else ""}</span>'
            f'</div>'
            f'</div>\n'
        )

    body = f'''<div class="header"><h1>📖 <a href="https://{journal}.livejournal.com">{journal}</a></h1>
<p class="stats">Постов: {len(all_posts)} | {datetime.now().strftime("%Y-%m-%d %H:%M")}</p></div>
<div class="posts-list">
<div class="search-box"><input type="text" placeholder="🔍 Поиск..."
oninput="document.querySelectorAll('.post-item').forEach(e=>e.style.display=e.textContent.toLowerCase().includes(this.value.toLowerCase())?'':'none')"></div>
{items}</div>'''

    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_wrap(f"Архив {journal}", body, journal))
    with open(os.path.join(outdir, "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)


def generate_post_html(post, journal, post_dir, prev_p=None, next_p=None):
    tree = build_tree(post.get("comments", []))
    max_depth = _find_max_depth(tree)
    comment_css = _gen_comment_css(max_depth)
    cmts = render_tree(tree)
    tags = f'🏷️ {", ".join(post["tags"])}' if post.get("tags") else ""
    mood = f'🎭 {post["mood"]}' if post.get("mood") else ""
    music = f'🎵 {post["music"]}' if post.get("music") else ""
    meta = " | ".join(filter(None, [tags, mood, music]))

    nav_parts = []
    if prev_p:
        nav_parts.append(f'<a href="../{prev_p["ditemid"]}/{prev_p["ditemid"]}.html">← {(prev_p.get("subject") or "…")[:40]}</a>')
    nav_parts.append("<span></span>")
    if next_p:
        nav_parts.append(f'<a href="../{next_p["ditemid"]}/{next_p["ditemid"]}.html">{(next_p.get("subject") or "…")[:40]} →</a>')
    nav = f'<div class="post-nav">{"".join(nav_parts)}</div>' if prev_p or next_p else ""

    body = f'''<div class="nav"><a href="../../index.html">← К списку</a>
<a href="{post.get("url","")}" target="_blank">Оригинал ↗</a></div>
<article class="post"><h1 class="post-title">{post.get("subject") or "(без темы)"}</h1>
<div class="post-meta">📅 {post.get("date","")}{" | " + meta if meta else ""}</div>
<div class="post-body">{post.get("body","")}</div></article>
{comment_css}
<div class="comments-section"><h2>💬 Комментарии ({len(post.get("comments",[]))})</h2>
{cmts or '<p class="no-comments">Нет комментариев</p>'}</div>{nav}'''

    did = post["ditemid"]
    with open(os.path.join(post_dir, f"{did}.html"), "w", encoding="utf-8") as f:
        f.write(page_wrap(post.get("subject") or "(без темы)", body, journal, css_path="../../style.css"))


# ─── Главный процесс ────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="LJ Archiver v3.0 — лучший архиватор LiveJournal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Примеры:\n"
               "  python lj_archiver.py varandej\n"
               "  python lj_archiver.py varandej 0-99\n"
               "  python lj_archiver.py varandej 0-9 --no-images\n"
               "  python lj_archiver.py varandej --id 1260352\n"
               "  python lj_archiver.py varandej --id 1260352,1253754,909694\n",
    )
    p.add_argument("journal", help="Имя журнала")
    p.add_argument("range", nargs="?", default=None, help="Диапазон постов, напр. 0-99 (новые→старые)")
    p.add_argument("-o", "--output-dir", default="./archive")
    p.add_argument("-d", "--delay", type=float, default=1.0, help="Задержка между запросами (сек)")
    p.add_argument("--no-images", action="store_true", help="Не скачивать картинки")
    p.add_argument("--no-comments", action="store_true", help="Не скачивать комментарии")
    p.add_argument("--id", dest="post_ids", default=None, help="Конкретные ditemid через запятую")
    args = p.parse_args()

    journal = args.journal.lower().strip()
    outdir = os.path.join(args.output_dir, journal)
    os.makedirs(outdir, exist_ok=True)

    # Парсим диапазон
    range_start, range_end = 0, None
    if args.range:
        parts = args.range.split("-")
        range_start = int(parts[0])
        range_end = int(parts[1]) + 1 if len(parts) > 1 else range_start + 1

    # Режим --id: конкретные посты
    explicit_ids = None
    if args.post_ids:
        explicit_ids = [i.strip() for i in args.post_ids.split(",") if i.strip()]

    http = HTTP(delay=args.delay)

    mode_str = f"ID: {','.join(explicit_ids)}" if explicit_ids else f"Диапазон: {range_start}-{(range_end - 1) if range_end else '∞'}"
    print(f"{'=' * 60}")
    print(f"  LJ Archiver v3.0")
    print(f"  Журнал: {journal}")
    print(f"  {mode_str}")
    print(f"  Картинки: {'да' if not args.no_images else 'нет'}")
    print(f"  Комментарии: {'да' if not args.no_comments else 'нет'}")
    print(f"  Папка: {os.path.abspath(outdir)}")
    print(f"{'=' * 60}")

    # State file для resume
    state_file = os.path.join(outdir, ".state.json")
    state = {}
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)

    # 1. Собираем ID
    if explicit_ids:
        ids = explicit_ids
        print(f"\n📋 Указано вручную: {len(ids)} постов")
    else:
        max_needed = range_end if range_end else None
        all_ids = state.get("all_ids") or collect_post_ids(http, journal, max_needed)
        state["all_ids"] = all_ids
        ids = all_ids[range_start:range_end]
        print(f"\n📋 Постов в диапазоне: {len(ids)}")

    # 2. Загрузка контента + комментарии + картинки для каждого поста
    posts = state.get("posts", {})
    total_comments = 0
    total_images = 0

    for i, did_str in enumerate(ids):
        did = int(did_str)
        post_dir = os.path.join(outdir, "posts", did_str)
        os.makedirs(post_dir, exist_ok=True)

        # Проверяем завершён ли пост
        if did_str in posts and posts[did_str].get("_done"):
            p = posts[did_str]
            total_comments += len(p.get("comments", []))
            total_images += p.get("_img_count", 0)
            continue

        print(f"\n  [{i + 1}/{len(ids)}] Пост {did}...")

        # 2a. Контент
        if did_str not in posts or not posts[did_str].get("body"):
            print(f"    📝 Загрузка контента... ", end="", flush=True)
            content = fetch_post_content(http, journal, did)
            if content:
                posts[did_str] = {
                    "ditemid": did, "itemid": did // 256, "anum": did % 256,
                    "url": f"https://{journal}.livejournal.com/{did}.html",
                    "security": "public", "mood": "", "music": "",
                    "comments": [], "comments_count": 0,
                    **content,
                }
                subj = (content["subject"] or "—")[:40]
                imgs = len(re.findall(r'<img', content.get("body", ""), re.I))
                print(f"✅ «{subj}» ({imgs} img)")
            else:
                print(f"❌ не удалось")
                posts[did_str] = {
                    "ditemid": did, "itemid": did // 256, "anum": did % 256,
                    "subject": "", "body": "", "date": "",
                    "url": f"https://{journal}.livejournal.com/{did}.html",
                    "security": "public", "tags": [], "mood": "", "music": "",
                    "comments": [], "comments_count": 0,
                }
        else:
            print(f"    📝 Контент из кэша")

        post = posts[did_str]

        # 2b. Комментарии
        if not args.no_comments and not post.get("comments"):
            try:
                comments = fetch_comments(http, journal, did)
                post["comments"] = comments
                post["comments_count"] = len(comments)
            except KeyboardInterrupt:
                print(f"\n⚠️  Прервано. Сохраняю состояние...")
                state["posts"] = posts
                with open(state_file, "w") as f:
                    json.dump(state, f)
                print(f"  Запустите снова для продолжения.")
                return
            except Exception as e:
                print(f"    💬 ❌ {e}")

        total_comments += len(post.get("comments", []))

        # 2c. Картинки
        img_count = 0
        if not args.no_images:
            cache = download_images_for_post(http, post, post_dir)
            apply_image_cache(post, cache)
            img_count = len(cache)
            total_images += img_count

        # 2d. LJ-теги
        post["body"] = process_lj(post.get("body", ""))
        for c in post.get("comments", []):
            c["body"] = process_lj(c.get("body", ""))

        post["_done"] = True
        post["_img_count"] = img_count
        posts[did_str] = post

        # Сохраняем state каждые 5 постов
        if (i + 1) % 5 == 0:
            state["posts"] = posts
            with open(state_file, "w") as f:
                json.dump(state, f)
            print(f"    💾 Состояние сохранено")

    # 3. Генерация HTML
    print(f"\n🌐 Генерирую HTML...")

    # Собираем посты в порядке ids (новые → старые)
    ordered_posts = [posts[did_str] for did_str in ids if did_str in posts]

    # Добавляем date если нет (из Atom или из порядка)
    for p in ordered_posts:
        if not p.get("date"):
            p["date"] = ""

    generate_index(ordered_posts, journal, outdir)

    for i, post in enumerate(ordered_posts):
        did = post["ditemid"]
        post_dir = os.path.join(outdir, "posts", str(did))
        os.makedirs(post_dir, exist_ok=True)
        prev_p = ordered_posts[i - 1] if i > 0 else None
        next_p = ordered_posts[i + 1] if i < len(ordered_posts) - 1 else None
        generate_post_html(post, journal, post_dir, prev_p, next_p)

    # Cleanup state
    if os.path.exists(state_file):
        os.remove(state_file)

    # Итоги
    filled = sum(1 for p in ordered_posts if p.get("body"))
    print(f"\n{'=' * 60}")
    print(f"  ✅ Готово!")
    print(f"  📝 {filled}/{len(ordered_posts)} постов с контентом")
    print(f"  💬 {total_comments} комментариев")
    print(f"  🖼️  {total_images} картинок скачано")
    print(f"  📁 {os.path.abspath(outdir)}")
    print(f"  🌐 Открой: {os.path.abspath(outdir)}/index.html")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
