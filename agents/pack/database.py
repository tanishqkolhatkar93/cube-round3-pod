import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./pack_manager.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PackRecord(Base):
    __tablename__ = "pack_records"
    record_id = Column(String, primary_key=True, index=True)
    unit_id = Column(String, index=True)
    org_id = Column(String, index=True, nullable=False) 
    operator_id = Column(String)
    order_id = Column(String)
    expected_order_lines = Column(Text)
    observed_in_box = Column(Text)
    checks_performed = Column(JSON)
    verdict = Column(String)
    reasoning = Column(Text)
    image_hash = Column(String)
    captured_at = Column(DateTime, default=datetime.utcnow)
    
Base.metadata.create_all(bind=engine)

class PackRecordDAO:
    def __init__(self, db_session, org_id: str):
        if not org_id:
            raise ValueError("org_id is mandatory")
        self.db = db_session
        self.org_id = org_id

    def create_record(self, record_data: dict):
        record_data["org_id"] = self.org_id 
        db_record = PackRecord(**record_data)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_record(self, record_id: str):
        return self.db.query(PackRecord).filter(
            PackRecord.record_id == record_id,
            PackRecord.org_id == self.org_id
        ).first()

    def list_records(self):
        return self.db.query(PackRecord).filter(PackRecord.org_id == self.org_id).all()
