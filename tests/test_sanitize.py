"""Тесты HTML-санитайзера писем (app/modules/mail/parse.py::_sanitize).

Санитайзер — регекспы поверх непривилегированного HTML; фронтенд дополнительно
рендерит письма в iframe sandbox="", но API-клиенты без iframe полагаются
только на него. Тесты фиксируют фактическое поведение и известные атаки.
"""
from __future__ import annotations

import unittest

from app.modules.mail.parse import _sanitize, _html_text


class SanitizeScriptTagsTest(unittest.TestCase):
    def test_script_removed_with_body(self):
        self.assertNotIn("script", _sanitize("<script>alert(1)</script>после"))
        self.assertNotIn("alert", _sanitize("<script>alert(1)</script>"))

    def test_unclosed_script_removed(self):
        self.assertNotIn("script", _sanitize("<script src=//evil.com>"))

    def test_iframe_object_embed_removed(self):
        for tag in ("iframe", "object", "embed", "form", "base"):
            with self.subTest(tag=tag):
                self.assertNotIn(tag, _sanitize(f"<{tag} src='x'>тело</{tag}>"))

    def test_meta_refresh_removed(self):
        self.assertNotIn("meta", _sanitize('<meta http-equiv="refresh" content="0;url=javascript:1">'))


class SanitizeEventHandlersTest(unittest.TestCase):
    def test_onclick_removed(self):
        out = _sanitize('<div onclick="evil()">текст</div>')
        self.assertNotIn("onclick", out)
        self.assertIn("текст", out)

    def test_onerror_unquoted_removed(self):
        out = _sanitize("<img src=x onerror=alert(1)>")
        self.assertNotIn("onerror", out)

    def test_svg_slash_onload_removed(self):
        # Регрессия: старый регекс требовал \s перед on — <svg/onload=...>
        # проходил насквозь (см. аудит, P2).
        out = _sanitize("<svg/onload=alert(1)>")
        self.assertNotIn("onload", out)

    def test_quoted_onload_removed(self):
        out = _sanitize("<svg onload='alert(1)'>")
        self.assertNotIn("onload", out)

    def test_uppercase_mixed_removed(self):
        out = _sanitize('<div OnClIck=evil()>x</div>')
        self.assertNotIn("onclick", out.lower())


class SanitizeUrlsTest(unittest.TestCase):
    def test_javascript_href_quoted_removed(self):
        out = _sanitize('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn("javascript", out.lower())

    def test_javascript_href_unquoted_removed(self):
        out = _sanitize("<a href=javascript:alert(1)>x</a>")
        self.assertNotIn("javascript", out.lower())

    def test_normal_https_href_kept(self):
        src = '<a href="https://example.com/page">ссылка</a>'
        self.assertIn("https://example.com/page", _sanitize(src))


class SanitizeContentTest(unittest.TestCase):
    def test_plain_markup_kept(self):
        src = "<p>Привет</p><b>жирный</b><i>курсив</i>"
        self.assertEqual(_sanitize(src), src)

    def test_word_containing_on_is_not_mangled(self):
        # "season=summer" внутри текста не должно страдать от on[a-z]+-регекса
        src = "<p>season=summer</p>"
        self.assertEqual(_sanitize(src), src)

    def test_empty_and_none(self):
        self.assertEqual(_sanitize(""), "")
        self.assertEqual(_sanitize("   "), "")


class HtmlTextTest(unittest.TestCase):
    def test_tags_replaced_by_space(self):
        # Переносы от <br>/<p> схлопываются _SPACE в пробел — документируем фактическое поведение
        self.assertEqual(_html_text("<p>один</p><br/>два"), "один два")

    def test_tags_stripped_and_entities_unescaped(self):
        self.assertEqual(_html_text("<b>a</b>&amp;&lt;b&gt;"), "a &<b>")

    def test_plain_text_untouched(self):
        self.assertEqual(_html_text("просто текст"), "просто текст")


if __name__ == "__main__":
    unittest.main()
