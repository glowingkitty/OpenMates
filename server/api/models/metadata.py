from pydantic import BaseModel, Field, ConfigDict


class Pagination(BaseModel):
    page: int = Field(..., description="Current page number")
    pageSize: int = Field(..., description="Number of results per page")
    pageCount: int = Field(..., description="Total number of pages")
    total: int = Field(..., description="Total number of results")

    model_config = ConfigDict(extra="forbid")


class MetaData(BaseModel):
    pagination: Pagination = Field(..., description="Pagination metadata")

    model_config = ConfigDict(extra="forbid")
