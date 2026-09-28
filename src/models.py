from pydantic import BaseModel

class ProblemDefinition(BaseModel):
    assignment_id: int
    sequence_number: int
    leetcode_id: int
    title: str
    difficulty: str = "TBD"
    language: str
