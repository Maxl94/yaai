from pydantic import BaseModel


class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None
