# LJ Archiver

**лучший архиватор LiveJournal | the best LiveJournal archiver**

Скачивает посты, комментарии и картинки из любого публичного журнала ЖЖ в офлайн-архив с красивым HTML.

Downloads posts, comments and images from any public LiveJournal blog into an offline archive with clean HTML.

---

## 🇷🇺 Русский

### Зачем

ЖЖ не вечен. Серверы переезжают, владельцы меняются, сервисы закрываются. Существующие архиваторы (ljdump, ljArchive, livejournal-export) либо мертвы, либо не скачивают комментарии полностью — свёрнутые ветки, динамическая подгрузка, пагинация теряются.

LJ Archiver решает это. Проверен на реальных журналах с тысячами комментариев и десятками фотографий на пост.

### Возможности

- Все посты с полным форматированием, тегами, настроением, музыкой
- Все комментарии включая свёрнутые ветки и глубокую вложенность
- Картинки из постов скачиваются локально (аватарки — в планах)
- Работает для любого публичного журнала, не только своего
- Продолжение после обрыва (Ctrl+C → запусти снова)
- Красивый офлайн-HTML с поиском и навигацией

### Установка

```bash
pip install requests lxml beautifulsoup4
```

### Использование

```bash
# Последние 10 постов
python lj_archiver.py varandej 0-9

# Все посты
python lj_archiver.py varandej

# Конкретные посты по ID
python lj_archiver.py varandej --id 1260352,1253754

# Без картинок (быстрее)
python lj_archiver.py varandej 0-9 --no-images

# Без комментариев
python lj_archiver.py varandej 0-9 --no-comments

# Задержка между запросами (по умолчанию 1 сек)
python lj_archiver.py varandej 0-99 -d 2.0

# Другая папка
python lj_archiver.py varandej -o ./backup
```

### Как это работает

**Сбор ID постов.** Парсит главную страницу журнала с пагинацией (`?skip=0`, `?skip=10`, ...). Собирает все ditemid, дедуплицирует, сортирует по убыванию (новые первые).

**Контент постов.** Для каждого ditemid загружает полную HTML-страницу. BeautifulSoup извлекает заголовок (`.aentry-post__title-text`), тело (`.aentry-post__text--view`) и теги (`.ljtags`).

**Комментарии.** Основной канал — внутренний JSON API `__rpc_get_thread` с пагинацией (`page=1,2,3...`). Это тот же эндпоинт, который использует JavaScript в браузере. Свёрнутые ветки (`loaded: 0`) дозагружаются отдельными запросами с `&thread=DTALKID`. Fallback — `?view=flat&nojs=1`.

**Картинки.** Прямой бинарный download каждой `<img>` из тела поста и комментариев. Сохраняются в папку поста, URL в HTML заменяются на локальные пути. Аватарки комментаторов пока пропускаются (тысячи дубликатов — нужен глобальный кэш).

**Обработка LJ-тегов.** `<lj-cut>` раскрывается, `<lj user="name">` → ссылка, `<lj-embed>` и `<lj-poll>` → плейсхолдеры.

### Структура архива

```
archive/varandej/
  index.html              ← список всех постов с поиском и сниппетами
  style.css
  posts/
    1260352/
      1260352.html         ← пост + плоский список комментариев
      img_a1b2c3d4e5f6.jpg ← картинки из поста
      img_f7e8d9c0b1a2.jpg
    1253754/
      1253754.html
      ...
```

Индекс при каждом запуске сканирует папку `posts/` и собирает все ранее скачанные посты, даже из предыдущих запусков.

### HTML комментариев

Комментарии — плоский список `<div>` без вложенности. Уровень задаётся CSS-классом (`.c0`, `.c1`, ...), родитель хранится в `data-parent`. Отступы нелинейные: первые уровни — широкие шаги, дальше затухают. CSS генерируется под конкретную глубину дерева каждого поста.

```html
<div class="comment c0" data-id="100" data-parent="0">...</div>
<div class="comment c1" data-id="101" data-parent="100">...</div>
<div class="comment c2" data-id="102" data-parent="101">...</div>
<div class="comment c0" data-id="103" data-parent="0">...</div>
```

Картинка или видео внутри комментария растягивает только свой блок, не ломает соседей.

### Resume

Состояние сохраняется каждые 5 постов в `.state.json`. Прервал — запустил снова — продолжит с того же места. Готовые посты пропускаются.

### Rate limits

Пауза между запросами (по умолчанию 1 сек), автоматическая обработка 429 и 503, ретраи с exponential backoff.

---

## 🇬🇧 English

### Why

LiveJournal won't last forever. Servers migrate, owners change, services shut down. Existing archivers (ljdump, ljArchive, livejournal-export) are either dead or don't fully download comments — collapsed threads, dynamic loading, and pagination are lost.

LJ Archiver solves this. Tested on real journals with thousands of comments and dozens of photos per post.

### Features

- All posts with full formatting, tags, mood, music
- All comments including collapsed threads and deep nesting
- Post images downloaded locally (userpics — planned)
- Works for any public journal, not just your own
- Resume after interruption (Ctrl+C → run again)
- Clean offline HTML with search and navigation

### Installation

```bash
pip install requests lxml beautifulsoup4
```

### Usage

```bash
# Latest 10 posts
python lj_archiver.py varandej 0-9

# All posts
python lj_archiver.py varandej

# Specific posts by ID
python lj_archiver.py varandej --id 1260352,1253754

# Without images (faster)
python lj_archiver.py varandej 0-9 --no-images

# Without comments
python lj_archiver.py varandej 0-9 --no-comments

# Custom delay between requests (default 1 sec)
python lj_archiver.py varandej 0-99 -d 2.0

# Custom output directory
python lj_archiver.py varandej -o ./backup
```

### How it works

**Post ID collection.** Parses the journal's main page with pagination (`?skip=0`, `?skip=10`, ...). Collects all ditemids, deduplicates, sorts descending (newest first).

**Post content.** For each ditemid, downloads the full HTML page. BeautifulSoup extracts the title (`.aentry-post__title-text`), body (`.aentry-post__text--view`), and tags (`.ljtags`).

**Comments.** Primary channel — LJ's internal JSON API `__rpc_get_thread` with pagination (`page=1,2,3...`). This is the same endpoint the browser's JavaScript calls. Collapsed threads (`loaded: 0`) are expanded via separate requests with `&thread=DTALKID`. Fallback — `?view=flat&nojs=1`.

**Images.** Direct binary download of every `<img>` from post body and comment bodies. Saved to the post's folder, URLs in HTML replaced with local paths. Commenter userpics are currently skipped (thousands of duplicates — global cache needed).

**LJ tag processing.** `<lj-cut>` is expanded, `<lj user="name">` → link, `<lj-embed>` and `<lj-poll>` → placeholders.

### Archive structure

```
archive/varandej/
  index.html              ← all posts with search and snippets
  style.css
  posts/
    1260352/
      1260352.html         ← post + flat comment list
      img_a1b2c3d4e5f6.jpg ← images from post
      img_f7e8d9c0b1a2.jpg
    1253754/
      1253754.html
      ...
```

The index scans the `posts/` folder on every run and includes all previously downloaded posts.

### Comment HTML

Comments are a flat list of `<div>` elements — zero nesting. Depth is set via CSS class (`.c0`, `.c1`, ...), parent is stored in `data-parent`. Indents are non-linear: wide steps at first, tapering off. CSS is generated per post based on actual tree depth.

```html
<div class="comment c0" data-id="100" data-parent="0">...</div>
<div class="comment c1" data-id="101" data-parent="100">...</div>
<div class="comment c2" data-id="102" data-parent="101">...</div>
<div class="comment c0" data-id="103" data-parent="0">...</div>
```

An image or video inside a comment only stretches its own block, never breaks neighbors.

### Resume

State is saved every 5 posts to `.state.json`. Interrupted → run again → picks up where it left off. Completed posts are skipped.

### Rate limits

Delay between requests (default 1 sec), automatic 429 and 503 handling, retries with exponential backoff.

---

### TODO

- [ ] Userpic global cache (username → file, no duplicates)
- [ ] Date extraction from HTML for posts not in Atom feed
- [ ] Export to EPUB / PDF
- [ ] Proxy mode for sandboxed environments

### License

MIT
