from datetime import datetime

from pydantic import BaseModel


class IndexingStatusResponse(BaseModel):
    state: str
    progress: int = 0
    total: int = 0
    processed: int = 0
    indexed: int = 0
    skipped: int = 0
    ready: int = 0
    failed: int = 0


class IndexingAccountTestResponse(BaseModel):
    connected: bool
    account_email: str
    property_url: str
    verified_at: datetime
