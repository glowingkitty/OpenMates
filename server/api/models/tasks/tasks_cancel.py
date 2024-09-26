
from pydantic import BaseModel, Field

class TasksCancelOutput(BaseModel):
    status: str = Field("successfully cancelled", description="Status of the cancellation request")


tasks_cancel_output_example = {
    "status": "successfully cancelled"
}