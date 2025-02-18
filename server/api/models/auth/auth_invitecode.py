from pydantic import BaseModel

class InviteCodeValidationInput(BaseModel):
    invite_code: str

class InviteCodeValidationOutput(BaseModel):
    valid: bool
