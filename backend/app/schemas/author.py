from pydantic import BaseModel


class AuthorResponse(BaseModel):
    id: str
    name: str
    institution: str
    department: str
    field: str
    email: str | None = None
