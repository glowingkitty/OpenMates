from pydantic import BaseModel, Field, ConfigDict, model_validator


class Pagination(BaseModel):
    page: int = Field(..., description="Current page number")
    pageSize: int = Field(..., description="Number of results per page")
    pageCount: int = Field(..., description="Total number of pages")
    total: int = Field(..., description="Total number of results")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_page_count(self):
        if self.page > self.pageCount:
            raise ValueError("Page number is greater than the total number of pages")
        return self

    @model_validator(mode="after")
    def validate_page_size(self):
        if self.pageSize > self.total:
            raise ValueError("Page size is greater than the total number of results")
        return self


class MetaData(BaseModel):
    pagination: Pagination = Field(..., description="Pagination metadata")

    model_config = ConfigDict(extra="forbid")
