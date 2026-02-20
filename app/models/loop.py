from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.models.test_model import Base


class Loop(Base):
    __tablename__ = "loops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    tempo = Column(Float, nullable=True)
    key = Column(String, nullable=True)
    genre = Column(String, nullable=True)
    file_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
