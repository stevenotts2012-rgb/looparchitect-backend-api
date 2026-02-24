from sqlalchemy import Column, Integer, String

from app.models.base import Base  # noqa: F401 – re-exported for backward compatibility


class TestItem(Base):
    __tablename__ = "test_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
