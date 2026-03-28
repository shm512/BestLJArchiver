#!/usr/bin/env python3
"""
Тесты XML-экспорта LJ Archiver.
Запуск: python test_xml_export.py
"""

import os
import sys
import unittest
import tempfile
import shutil
from xml.etree import ElementTree

# Добавляем путь к скрипту
sys.path.insert(0, os.path.dirname(__file__))
from lj_archiver import export_xml, build_tree, _xml_escape, _collect_image_urls, VERSION


# ─── Тестовые данные (имитация реального журнала) ───────────────────────────

MOCK_JOURNAL = "test_varandej"

MOCK_POSTS = [
    {
        "ditemid": 1260352,
        "itemid": 4923,
        "anum": 64,
        "subject": "Улан-Удэ. Часть 6: Городское кольцо",
        "body": '<p>Продолжаем гулять по <a href="https://ru.wikipedia.org">столице Бурятии</a>.</p>'
               '<p><img src="img_abc123.jpg" alt="Вид на город"/></p>'
               '<p>Тут был <lj user="another_user"/> и писал об этом.</p>',
        "date": "2025-11-15 14:30:00",
        "url": "https://varandej.livejournal.com/1260352.html",
        "security": "public",
        "tags": ["Россия", "Бурятия", "Улан-Удэ"],
        "mood": "contemplative",
        "music": "Аквариум — Город золотой",
        "comments": [
            {
                "dtalkid": 5001,
                "username": "historian_pavel",
                "userpic": "",
                "subject": "",
                "body": "<p>Отличный репортаж! Был там в 2019, всё узнаю.</p>",
                "date": "November 15 2025, 16:00:00 UTC",
                "date_ts": 1731686400,
                "parent_dtalkid": 0,
                "level": 1,
                "loaded": 1,
                "deleted": False,
                "screened": False,
            },
            {
                "dtalkid": 5002,
                "username": "test_varandej",
                "userpic": "",
                "subject": "",
                "body": "<p>Спасибо! Да, город сильно изменился с тех пор.</p>",
                "date": "November 15 2025, 17:30:00 UTC",
                "date_ts": 1731691800,
                "parent_dtalkid": 5001,
                "level": 2,
                "loaded": 1,
                "deleted": False,
                "screened": False,
            },
            {
                "dtalkid": 5003,
                "username": "",
                "userpic": "",
                "subject": "Вопрос",
                "body": "<p>А как добирались? Поездом или самолётом?</p>",
                "date": "November 16 2025, 08:00:00 UTC",
                "date_ts": 1731744000,
                "parent_dtalkid": 0,
                "level": 1,
                "loaded": 1,
                "deleted": False,
                "screened": False,
            },
            {
                "dtalkid": 5004,
                "username": "deleted_user",
                "userpic": "",
                "subject": "",
                "body": "",
                "date": "November 16 2025, 09:00:00 UTC",
                "date_ts": 1731747600,
                "parent_dtalkid": 5003,
                "level": 2,
                "loaded": 1,
                "deleted": True,
                "screened": False,
            },
            {
                "dtalkid": 5005,
                "username": "secret_commenter",
                "userpic": "",
                "subject": "",
                "body": "<p>Скрытый комментарий</p>",
                "date": "November 16 2025, 10:00:00 UTC",
                "date_ts": 1731751200,
                "parent_dtalkid": 0,
                "level": 1,
                "loaded": 1,
                "deleted": False,
                "screened": True,
            },
        ],
        "comments_count": 5,
    },
    {
        "ditemid": 1253754,
        "itemid": 4898,
        "anum": 42,
        "subject": 'Тест "спецсимволов" <>&\' в заголовке',
        "body": '<p>Пост с &amp; и <em>курсивом</em>.</p>',
        "date": "2025-10-20 10:00:00",
        "url": "https://varandej.livejournal.com/1253754.html",
        "security": "public",
        "tags": [],
        "mood": "",
        "music": "",
        "comments": [],
        "comments_count": 0,
    },
    {
        "ditemid": 909694,
        "itemid": 3553,
        "anum": 126,
        "subject": "",  # пост без заголовка
        "body": "<p>Короткий пост без заголовка.</p>",
        "date": "2024-01-01 00:00:00",
        "url": "https://varandej.livejournal.com/909694.html",
        "security": "public",
        "tags": ["тест"],
        "mood": "",
        "music": "",
        "comments": [
            {
                "dtalkid": 9001,
                "username": "deep_threader",
                "userpic": "",
                "subject": "",
                "body": "<p>Уровень 1</p>",
                "date": "Jan 1 2024, 12:00:00 UTC",
                "date_ts": 1704110400,
                "parent_dtalkid": 0,
                "level": 1,
                "loaded": 1,
                "deleted": False,
                "screened": False,
            },
            {
                "dtalkid": 9002,
                "username": "deep_threader",
                "userpic": "",
                "subject": "",
                "body": "<p>Уровень 2</p>",
                "date": "Jan 1 2024, 12:01:00 UTC",
                "date_ts": 1704110460,
                "parent_dtalkid": 9001,
                "level": 2,
                "loaded": 1,
                "deleted": False,
                "screened": False,
            },
            {
                "dtalkid": 9003,
                "username": "deep_threader",
                "userpic": "",
                "subject": "",
                "body": "<p>Уровень 3</p>",
                "date": "Jan 1 2024, 12:02:00 UTC",
                "date_ts": 1704110520,
                "parent_dtalkid": 9002,
                "level": 3,
                "loaded": 1,
                "deleted": False,
                "screened": False,
            },
        ],
        "comments_count": 3,
    },
]


# ─── Тесты ──────────────────────────────────────────────────────────────────

class TestXmlEscape(unittest.TestCase):
    """Тесты экранирования спецсимволов."""

    def test_ampersand(self):
        self.assertEqual(_xml_escape("A & B"), "A &amp; B")

    def test_angle_brackets(self):
        self.assertEqual(_xml_escape("<tag>"), "&lt;tag&gt;")

    def test_quotes(self):
        self.assertIn("&quot;", _xml_escape('say "hello"'))
        self.assertIn("&apos;", _xml_escape("it's"))

    def test_empty(self):
        self.assertEqual(_xml_escape(""), "")
        self.assertEqual(_xml_escape(None), "")

    def test_plain_text(self):
        self.assertEqual(_xml_escape("просто текст"), "просто текст")

    def test_all_at_once(self):
        result = _xml_escape('<a href="x">&\'test\'</a>')
        self.assertNotIn("<", result.replace("&lt;", "").replace("&gt;", ""))
        self.assertNotIn("&", result.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "").replace("&quot;", "").replace("&apos;", ""))


class TestXmlExport(unittest.TestCase):
    """Тесты экспорта в XML."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _export_and_parse(self, posts=None):
        if posts is None:
            posts = MOCK_POSTS
        path = export_xml(posts, MOCK_JOURNAL, self.tmpdir)
        self.assertTrue(os.path.exists(path))
        tree = ElementTree.parse(path)
        return tree.getroot()

    # ── Структура ────────────────────────────────

    def test_file_created(self):
        """XML-файл создаётся."""
        path = export_xml(MOCK_POSTS, MOCK_JOURNAL, self.tmpdir)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".xml"))

    def test_valid_xml(self):
        """Результат — валидный XML."""
        root = self._export_and_parse()
        self.assertEqual(root.tag, "journal")

    def test_root_attributes(self):
        """Корневой элемент содержит атрибуты журнала."""
        root = self._export_and_parse()
        self.assertEqual(root.attrib["name"], MOCK_JOURNAL)
        self.assertIn("exported", root.attrib)
        self.assertEqual(root.attrib["version"], VERSION)

    def test_meta(self):
        """Блок <meta> с правильными счётчиками."""
        root = self._export_and_parse()
        meta = root.find("meta")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.find("posts_count").text, "3")
        self.assertEqual(meta.find("comments_count").text, "8")  # 5 + 0 + 3
        self.assertIn("livejournal.com", meta.find("url").text)

    def test_posts_count(self):
        """Правильное количество постов."""
        root = self._export_and_parse()
        posts = root.findall(".//post")
        self.assertEqual(len(posts), 3)

    # ── Посты ────────────────────────────────────

    def test_post_attributes(self):
        """Пост содержит id."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        self.assertIsNotNone(post)

    def test_post_title(self):
        """Заголовок поста."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        title = post.find("title").text
        self.assertIn("Улан-Удэ", title)

    def test_post_date(self):
        """Дата поста."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        self.assertEqual(post.find("date").text, "2025-11-15 14:30:00")

    def test_post_url(self):
        """URL поста."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        self.assertIn("1260352.html", post.find("url").text)

    def test_post_body_cdata(self):
        """Тело поста в CDATA (HTML сохраняется как есть)."""
        path = export_xml(MOCK_POSTS, MOCK_JOURNAL, self.tmpdir)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("<![CDATA[", raw)
        self.assertIn("столице Бурятии", raw)

    def test_post_tags(self):
        """Теги поста."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        tags = [t.text for t in post.findall(".//tag")]
        self.assertEqual(tags, ["Россия", "Бурятия", "Улан-Удэ"])

    def test_post_no_tags(self):
        """Пост без тегов — нет блока <tags>."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1253754']")
        self.assertIsNone(post.find("tags"))

    def test_post_mood_music(self):
        """Настроение и музыка."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        self.assertEqual(post.find("mood").text, "contemplative")
        self.assertIn("Аквариум", post.find("music").text)

    def test_post_no_mood_music(self):
        """Пост без mood/music — элементы отсутствуют."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1253754']")
        self.assertIsNone(post.find("mood"))
        self.assertIsNone(post.find("music"))

    def test_post_empty_title(self):
        """Пост без заголовка — пустой <title>."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='909694']")
        self.assertEqual(post.find("title").text or "", "")

    # ── Спецсимволы ──────────────────────────────

    def test_special_chars_in_title(self):
        """Спецсимволы в заголовке экранированы."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1253754']")
        title = post.find("title").text
        # ElementTree сам декодирует сущности, но оригинал не должен ломать парсинг
        self.assertIn('"', title)
        self.assertIn("<", title)
        self.assertIn("&", title)

    # ── Комментарии ──────────────────────────────

    def test_comments_count(self):
        """Количество комментариев у поста."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1260352']")
        comments = post.find("comments")
        self.assertEqual(comments.attrib["count"], "5")

    def test_comment_structure(self):
        """Структура комментария: id, parent, level, author, date, body."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5001']")
        self.assertIsNotNone(comment)
        self.assertEqual(comment.attrib["parent"], "0")
        self.assertEqual(comment.attrib["level"], "1")
        self.assertEqual(comment.find("author").text, "historian_pavel")
        self.assertIsNotNone(comment.find("date"))
        self.assertIsNotNone(comment.find("body"))

    def test_comment_date_ts(self):
        """Timestamp в атрибуте даты."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5001']")
        self.assertEqual(comment.find("date").attrib["ts"], "1731686400")

    def test_comment_parent_chain(self):
        """Цепочка parent: 5002 → 5001 → 0."""
        root = self._export_and_parse()
        c1 = root.find(".//comment[@id='5001']")
        c2 = root.find(".//comment[@id='5002']")
        self.assertEqual(c1.attrib["parent"], "0")
        self.assertEqual(c2.attrib["parent"], "5001")

    def test_comment_with_subject(self):
        """Комментарий с темой."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5003']")
        self.assertEqual(comment.find("subject").text, "Вопрос")

    def test_comment_without_subject(self):
        """Комментарий без темы — нет элемента <subject>."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5001']")
        self.assertIsNone(comment.find("subject"))

    def test_deleted_comment(self):
        """Удалённый комментарий — <deleted>true</deleted>."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5004']")
        self.assertEqual(comment.find("deleted").text, "true")
        self.assertIsNone(comment.find("body"))

    def test_screened_comment(self):
        """Скрытый комментарий — <screened>true</screened>."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5005']")
        self.assertEqual(comment.find("screened").text, "true")
        self.assertIsNone(comment.find("body"))

    def test_anonymous_comment(self):
        """Анонимный комментарий — пустой <author>."""
        root = self._export_and_parse()
        comment = root.find(".//comment[@id='5003']")
        self.assertEqual(comment.find("author").text or "", "")

    def test_no_comments(self):
        """Пост без комментариев — нет блока <comments>."""
        root = self._export_and_parse()
        post = root.find(".//post[@id='1253754']")
        self.assertIsNone(post.find("comments"))

    def test_comments_sorted_by_date(self):
        """Комментарии отсортированы по date_ts."""
        root = self._export_and_parse()
        comments = root.findall(".//post[@id='1260352']//comment")
        timestamps = [int(c.find("date").attrib["ts"]) for c in comments]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_deep_thread(self):
        """Глубокая ветка: 3 уровня, parent-цепочка."""
        root = self._export_and_parse()
        c1 = root.find(".//comment[@id='9001']")
        c2 = root.find(".//comment[@id='9002']")
        c3 = root.find(".//comment[@id='9003']")
        self.assertEqual(c1.attrib["parent"], "0")
        self.assertEqual(c2.attrib["parent"], "9001")
        self.assertEqual(c3.attrib["parent"], "9002")
        self.assertEqual(c1.attrib["level"], "1")
        self.assertEqual(c3.attrib["level"], "3")

    # ── Пустой экспорт ───────────────────────────

    def test_empty_journal(self):
        """Пустой журнал — валидный XML без постов."""
        root = self._export_and_parse(posts=[])
        self.assertEqual(root.find("meta/posts_count").text, "0")
        self.assertEqual(len(root.findall(".//post")), 0)

    # ── Размер и кодировка ───────────────────────

    def test_utf8_encoding(self):
        """Файл в UTF-8, кириллица сохраняется."""
        path = export_xml(MOCK_POSTS, MOCK_JOURNAL, self.tmpdir)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("Улан-Удэ", raw)
        self.assertIn("Аквариум", raw)
        self.assertIn('encoding="UTF-8"', raw)

    def test_body_html_preserved(self):
        """HTML в теле поста и комментариев сохраняется через CDATA."""
        path = export_xml(MOCK_POSTS, MOCK_JOURNAL, self.tmpdir)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("<img src=", raw)
        self.assertIn("href=", raw)
        self.assertIn("<em>курсивом</em>", raw)


class TestImageCollection(unittest.TestCase):
    """Тесты сбора URL картинок: <img src> + <a href> обёртки."""

    def test_img_src_basic(self):
        """Простая <img src> ловится."""
        urls = _collect_image_urls('<img src="https://example.com/photo.jpg">')
        self.assertIn("https://example.com/photo.jpg", urls)

    def test_img_src_various_extensions(self):
        """Разные расширения картинок."""
        for ext in [".jpg", ".png", ".gif", ".webp", ".jpeg", ".svg"]:
            html = f'<img src="https://cdn.example.com/img{ext}">'
            urls = _collect_image_urls(html)
            self.assertTrue(len(urls) >= 1, f"Не нашёл {ext}")

    def test_a_href_full_size(self):
        """<a href="full.jpg"><img src="thumb.jpg"></a> — ловит обе."""
        html = '<a href="https://cdn.com/full.jpg"><img src="https://cdn.com/thumb.jpg"></a>'
        urls = _collect_image_urls(html)
        self.assertIn("https://cdn.com/full.jpg", urls)
        self.assertIn("https://cdn.com/thumb.jpg", urls)
        self.assertEqual(len(urls), 2)

    def test_a_href_not_image_skipped(self):
        """<a href> на обычную страницу — не ловится."""
        html = '<a href="https://example.com/article">текст</a>'
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 0)

    def test_a_href_lj_photo_hosting(self):
        """Ссылки на фото-хостинги ЖЖ без расширения — ловятся."""
        for host_url in [
            "https://ic.pics.livejournal.com/user/12345/67890/67890_original",
            "https://img-fotki.yandex.ru/get/123/user.1a/0_abc_def_orig",
            "https://content.foto.my.mail.ru/mail/user/album/h-12345",
            "https://pics.livejournal.com/user/pic/001abc",
        ]:
            html = f'<a href="{host_url}"><img src="https://x.com/thumb.jpg"></a>'
            urls = _collect_image_urls(html)
            self.assertIn(host_url, urls, f"Не нашёл LJ-хостинг: {host_url}")

    def test_mail_ru_full_and_thumb(self):
        """mail.ru: h-12345.jpg (full) + s-12345.jpg (thumb) — обе."""
        html = '''<a href="https://content.foto.my.mail.ru/mail/user/album/h-12345.jpg">
                  <img src="https://content.foto.my.mail.ru/mail/user/album/s-12345.jpg"></a>'''
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 2)
        self.assertTrue(any("h-12345" in u for u in urls))
        self.assertTrue(any("s-12345" in u for u in urls))

    def test_query_string_ignored_for_extension(self):
        """URL с query string: расширение определяется до '?'."""
        html = '<a href="https://cdn.com/photo.jpg?width=800&quality=90">click</a>'
        urls = _collect_image_urls(html)
        self.assertIn("https://cdn.com/photo.jpg?width=800&quality=90", urls)

    def test_relative_urls_skipped(self):
        """Относительные URL (без http) — пропускаются."""
        html = '<img src="/local/photo.jpg"><a href="relative/pic.png">x</a>'
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 0)

    def test_empty_and_none(self):
        """Пустой HTML и None — пустой set."""
        self.assertEqual(len(_collect_image_urls("")), 0)
        self.assertEqual(len(_collect_image_urls(None)), 0)

    def test_multiple_images_in_post(self):
        """Пост с несколькими картинками — все собираются."""
        html = '''
        <a href="https://cdn.com/full1.jpg"><img src="https://cdn.com/t1.jpg"></a>
        <p>текст между</p>
        <img src="https://cdn.com/standalone.png">
        <a href="https://cdn.com/full2.jpg"><img src="https://cdn.com/t2.jpg"></a>
        '''
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 5)  # 2 full + 2 thumb + 1 standalone

    def test_deduplication(self):
        """Одинаковые URL не дублируются."""
        html = '''
        <img src="https://cdn.com/same.jpg">
        <img src="https://cdn.com/same.jpg">
        <a href="https://cdn.com/same.jpg">link</a>
        '''
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 1)

    def test_mixed_a_href_image_and_page(self):
        """Микс ссылок на картинки и на страницы — только картинки."""
        html = '''
        <a href="https://example.com/article">статья</a>
        <a href="https://cdn.com/photo.jpg"><img src="https://cdn.com/thumb.jpg"></a>
        <a href="https://google.com">гугл</a>
        <a href="https://cdn.com/doc.pdf">pdf</a>
        '''
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 2)  # только photo.jpg и thumb.jpg

    def test_comment_images(self):
        """Картинки из комментариев — тот же механизм."""
        comment_html = '<a href="https://ic.pics.livejournal.com/user/1/2/2_original.jpg"><img src="https://ic.pics.livejournal.com/user/1/2/2_300.jpg"></a>'
        urls = _collect_image_urls(comment_html)
        self.assertEqual(len(urls), 2)
        self.assertTrue(any("original" in u for u in urls))
        self.assertTrue(any("300" in u for u in urls))

    def test_case_insensitive_extensions(self):
        """Расширения регистронезависимы: .JPG, .Png."""
        html = '<a href="https://cdn.com/PHOTO.JPG"><img src="https://cdn.com/thumb.PNG">'
        urls = _collect_image_urls(html)
        self.assertEqual(len(urls), 2)


# ─── Запуск ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
