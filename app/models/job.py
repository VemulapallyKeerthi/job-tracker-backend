from sqlalchemy import Column, Integer, String, Date
from app.database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String)
    posted_date = Column(Date)
    description = Column(String)
    apply_link = Column(String, nullable=False)
    status = Column(String, default="saved")  