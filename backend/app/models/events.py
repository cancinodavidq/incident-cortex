from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any
import uuid


class IncidentEvent(BaseModel):
    id: Optional[int] = None
    incident_id: str
    phase: str
    agent: str
    payload: Optional[dict] = None
    created_at: datetime = None

    def model_post_init(self, __context):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class SystemStatus(BaseModel):
    key: str
    value: str
    updated_at: datetime = None

    def model_post_init(self, __context):
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()
