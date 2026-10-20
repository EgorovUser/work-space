"""Общие хелперы core (патч W): entities.owned_row и text.*.

Прямые юнит-проверки того, что раньше было размазано по пяти модулям
копиями: лоадер строки с проверками проекта и корзины, валидаторы
названий и лимитов, фильтр поиска, сниппет, каталог {id, label}.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-helpers-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "helpers-test-secret")
os.environ.setdefault("SEED_USERNAME", "tester")
os.environ.setdefault("SEED_PASSWORD", "tester-pass")
os.environ.setdefault("LOG_LEVEL", "ERROR")

from app.core.config import get as get_config  # noqa: E402

try:
    get_config()
except RuntimeError:
    from cryptography.fernet import Fernet

    os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
    from app.core.config import prepare

    prepare()

from fastapi import HTTPException  # noqa: E402

from app.main import app  # noqa: E402  (импорт поднимает init_db + seed + defs)
from app.core.db import SessionLocal, utcnow  # noqa: E402
from app.core.entities import owned_row  # noqa: E402
from app.core.text import (  # noqa: E402
    catalog_label,
    choices_catalog,
    clean_limited,
    clean_name,
    search_needle,
    snippet,
)
from app.modules.projects.models import Project  # noqa: E402
from app.modules.secrets.models import Secret  # noqa: E402


class CleanNameTest(unittest.TestCase):
    def test_strips_and_accepts(self):
        self.assertEqual(clean_name("secrets", "title.max_length", "  Название  "), "Название")

    def test_empty_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            clean_name("secrets", "title.max_length", "   ")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Укажите название")

    def test_long_rejected_with_limit(self):
        # Лимит из настроек модуля: у секретов title.max_length.
        from app.core.settings_store import get_int

        limit = get_int("secrets", "title.max_length")
        with self.assertRaises(HTTPException) as ctx:
            clean_name("secrets", "title.max_length", "я" * (limit + 1))
        self.assertIn(str(limit), ctx.exception.detail)

    def test_fallback_used_when_empty(self):
        self.assertEqual(
            clean_name("secrets", "title.max_length", "", fallback="Из имени файла"),
            "Из имени файла",
        )


class CleanLimitedTest(unittest.TestCase):
    def test_empty_passes(self):
        self.assertEqual(clean_limited("rdp", "note.max_length", ""), "")

    def test_strip_flag(self):
        self.assertEqual(clean_limited("rdp", "note.max_length", "  x  ", strip=True), "x")
        self.assertEqual(clean_limited("rdp", "note.max_length", "  x  ", strip=False), "  x  ")

    def test_long_prefix(self):
        from app.core.settings_store import get_int

        limit = get_int("examples", "note.max_length")
        with self.assertRaises(HTTPException) as ctx:
            clean_limited("examples", "note.max_length", "я" * (limit + 1), strip=False, long_prefix="Заметка длиннее ")
        self.assertTrue(ctx.exception.detail.startswith("Заметка длиннее "))


class SearchNeedleTest(unittest.TestCase):
    def test_casefold(self):
        self.assertEqual(search_needle("secrets", "list.query.min_length", " АБв ", None), "абв")

    def test_too_short_rejected(self):
        # Дефолтный минимум — 0; проверяем отсечку через проектную область.
        with SessionLocal() as session:
            project = Project(name="фильтр " + os.urandom(3).hex(), archived=False, created_at=utcnow(), updated_at=utcnow())
            session.add(project)
            session.flush()
            pid = project.id
            session.commit()
        try:
            from app.core.settings_store import set_value

            set_value("secrets", "list.query.min_length", "project", 2, project_id=pid, actor_id=1)
            with self.assertRaises(HTTPException) as ctx:
                search_needle("secrets", "list.query.min_length", "я", pid)
            self.assertIn("короче", ctx.exception.detail)
            self.assertEqual(search_needle("secrets", "list.query.min_length", "две", pid), "две")
        finally:
            with SessionLocal() as session:
                session.delete(session.get(Project, pid))
                session.commit()


class SnippetTest(unittest.TestCase):
    def test_around_match(self):
        text = "начало " + "с" * 50 + " игла " + "т" * 50 + " конец"
        chunk = snippet(text, "игла", 20)
        self.assertIn("игла", chunk)
        self.assertLessEqual(len(chunk), 21)

    def test_no_match_prefix(self):
        self.assertEqual(snippet("короткий текст", "нетути", 40), "короткий текст")


class CatalogTest(unittest.TestCase):
    def test_catalog_and_label(self):
        with SessionLocal() as session:
            project = Project(name="каталог " + os.urandom(3).hex(), archived=False, created_at=utcnow(), updated_at=utcnow())
            session.add(project)
            session.flush()
            pid = project.id
            session.commit()
        try:
            from app.core.settings_store import set_value

            set_value("secrets", "kinds", "project", [{"id": "db", "label": "База"}, "просто строка", {"id": ""}], project_id=pid, actor_id=1)
            items = choices_catalog("secrets", "kinds", project_id=pid)
            self.assertEqual(items, [{"id": "db", "label": "База"}, {"id": "просто строка", "label": "просто строка"}])
            self.assertEqual(catalog_label(items, "db"), "База")
            self.assertEqual(catalog_label(items, "нет-такого"), "нет-такого")
        finally:
            with SessionLocal() as session:
                session.delete(session.get(Project, pid))
                session.commit()


class OwnedRowTest(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as session:
            self.project = Project(name="лоадер " + os.urandom(3).hex(), archived=False, created_at=utcnow(), updated_at=utcnow())
            self.other = Project(name="чужой " + os.urandom(3).hex(), archived=False, created_at=utcnow(), updated_at=utcnow())
            session.add_all([self.project, self.other])
            session.flush()
            self.secret = Secret(
                project_id=self.project.id,
                title="живой",
                kind="",
                username_enc="",
                url_enc="",
                note_enc="",
                secret_enc="",
                archived=False,
                deleted_at=None,
            )
            self.trashed = Secret(
                project_id=self.project.id,
                title="в корзине",
                kind="",
                username_enc="",
                url_enc="",
                note_enc="",
                secret_enc="",
                archived=False,
                deleted_at=utcnow(),
            )
            session.add_all([self.secret, self.trashed])
            session.flush()
            self.secret_id = self.secret.id
            self.trashed_id = self.trashed.id
            self.project_id = self.project.id
            self.other_id = self.other.id
            session.commit()

    def tearDown(self):
        with SessionLocal() as session:
            for row_id in (self.secret_id, self.trashed_id):
                row = session.get(Secret, row_id)
                if row is not None:
                    session.delete(row)
            for project_id in (self.project_id, self.other_id):
                row = session.get(Project, project_id)
                if row is not None:
                    session.delete(row)
            session.commit()

    def _loader(self, session, secret_id, in_trash=False):
        return owned_row(
            session,
            Secret,
            self.project_id,
            secret_id,
            in_trash=in_trash,
            label="Секрет",
            not_found="Секрет не найден",
            deleted_to_trash="Секрет удалён в корзину",
        )

    def test_found(self):
        with SessionLocal() as session:
            row = self._loader(session, self.secret_id)
            self.assertEqual(row.title, "живой")

    def test_foreign_project_404(self):
        with SessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                owned_row(
                    session,
                    Secret,
                    self.other_id,
                    self.secret_id,
                    label="Секрет",
                    not_found="Секрет не найден",
                    deleted_to_trash="Секрет удалён в корзину",
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_trashed_hidden_from_live(self):
        with SessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                self._loader(session, self.trashed_id)
            self.assertEqual(ctx.exception.detail, "Секрет удалён в корзину")

    def test_live_hidden_from_trash(self):
        with SessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                self._loader(session, self.secret_id, in_trash=True)
            self.assertEqual(ctx.exception.detail, "Секрет не в корзине")

    def test_no_trash_support_skips_checks(self):
        # Примеры и заметки живут без корзины: удалённой строки не бывает,
        # проверки не делаются вовсе.
        with SessionLocal() as session:
            row = owned_row(session, Secret, self.project_id, self.trashed_id, label="Секрет", not_found="Секрет не найден")
            self.assertEqual(row.title, "в корзине")


if __name__ == "__main__":
    unittest.main()
