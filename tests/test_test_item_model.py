"""
Tests for app/models/test_model.py – the TestItem SQLAlchemy model.

This file has 0% coverage because it is a model definition that was never
imported or exercised by any test.  These tests bring it to full coverage by:
- Importing and inspecting the class
- Creating/querying TestItem rows via an in-memory SQLite database
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
def test_item_session():
    """Create a fresh in-memory SQLite DB and return a session."""
    from app.models.base import Base
    from app.models.test_model import TestItem  # noqa: F401 – ensures table registered

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class TestTestItemModel:
    def test_table_name_is_test_items(self):
        from app.models.test_model import TestItem

        assert TestItem.__tablename__ == "test_items"

    def test_has_id_column(self):
        from app.models.test_model import TestItem

        cols = {c.key for c in inspect(TestItem).mapper.column_attrs}
        assert "id" in cols

    def test_has_name_column(self):
        from app.models.test_model import TestItem

        cols = {c.key for c in inspect(TestItem).mapper.column_attrs}
        assert "name" in cols

    def test_create_and_query(self, test_item_session):
        from app.models.test_model import TestItem

        item = TestItem(name="hello")
        test_item_session.add(item)
        test_item_session.commit()
        test_item_session.refresh(item)

        assert item.id is not None
        fetched = test_item_session.query(TestItem).filter_by(name="hello").first()
        assert fetched is not None
        assert fetched.name == "hello"

    def test_id_is_primary_key(self):
        from sqlalchemy import inspect as sa_inspect
        from app.models.test_model import TestItem

        mapper = sa_inspect(TestItem)
        pk_cols = [col.name for col in mapper.mapper.primary_key]
        assert "id" in pk_cols

    def test_inherits_from_base(self):
        from app.models.base import Base
        from app.models.test_model import TestItem

        assert issubclass(TestItem, Base)

    def test_multiple_items_have_different_ids(self, test_item_session):
        from app.models.test_model import TestItem

        item_a = TestItem(name="alpha")
        item_b = TestItem(name="beta")
        test_item_session.add_all([item_a, item_b])
        test_item_session.commit()

        assert item_a.id != item_b.id

    def test_name_can_be_none(self, test_item_session):
        from app.models.test_model import TestItem

        item = TestItem(name=None)
        test_item_session.add(item)
        test_item_session.commit()
        test_item_session.refresh(item)
        assert item.id is not None
        assert item.name is None
