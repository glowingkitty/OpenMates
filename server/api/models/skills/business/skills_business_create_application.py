from pydantic import BaseModel, Field
from typing import Literal, List, Optional, Dict, Any
from server.api.models.skills.ai.skills_ai_ask import Tool, ToolInputSchema

# POST /{team_slug}/skills/business/create_application

class Program(BaseModel):
    name: str = Field(..., description="What is the name of the program?")
    description: str = Field(..., description="What is this program about?")
    requirements: Optional[str] = Field(None, description="What are the requirements for applying to this program? Write a list that covers all requirements for applicants.")
    evaluation_criteria: Optional[str] = Field(None, description="Based on what criteria will the applications be evaluated? Write a list that covers all evaluation criteria.")
    examples: Optional[str] = Field(None, description="Any good examples of successful applications from other applicants? Write a list with various great examples.")
    avoid: Optional[str] = Field(None, description="Any don'ts or things to avoid in the application? Write a list that covers all the important donts.")

class Recipient(BaseModel):
    name: str = Field(..., description="What is the name of the recipient / organization?")
    writing_style: Optional[str] = Field(None, description="What writing style would be best for the recipient? Considering who is likely reading the application, what background / skills they have, etc.")
    programs: List[Program] = Field(..., description="What programs does the recipient offer?")

    @classmethod
    def to_tool(cls) -> Tool:
        schema = cls.model_json_schema()
        properties = schema.get('properties', {})
        required = schema.get('required', [])

        # Ensure the Program schema is included correctly
        program_schema = Program.model_json_schema()
        properties['programs']['items'] = program_schema

        return Tool(
            name="recipient_tool",
            description="Tool for recipient information",
            input_schema=ToolInputSchema(
                type="object",
                properties=properties,
                required=required
            )
        )

class TeamMember(BaseModel):
    name: str = Field(..., description="What is the name of the team member?")
    skills: str = Field(..., description="What are the skills of the team member?")
    projects: Optional[str] = Field(None, description="What previous projects has the team member worked on?")
    companies: Optional[str] = Field(None, description="What previous companies has the team member worked for and in what role?")

class RequestedFunding(BaseModel):
    amount: float = Field(..., description="How much funding are you requesting?")
    currency: str = Field(..., description="What is the currency of the funding?")
    usage: str = Field(..., description="How will the funding be used?")

class Applicant(BaseModel):
    what: Literal["project", "company"] = Field(..., description="Are you applying with a project or a company?")
    name: str = Field(..., description="What is the name of the project or company?")
    description: str = Field(..., description="What is your project or business about?")
    highlights: Optional[str] = Field(None, description="What products, services, or features are you most excited about?")
    users: Optional[str] = Field(None, description="Who are your target users? What are their pain points?")
    team: Optional[List[TeamMember]] = Field(None, description="Who is your team?")
    funding_needed: Optional[RequestedFunding] = Field(None, description="How much funding are you requesting and for what?")
    usps: Optional[str] = Field(None, description="What are your unique selling points? What makes you stand out?")
    competition: Optional[str] = Field(None, description="What are the main competitors of your project or business?")
    business_model: Optional[str] = Field(None, description="What is your business model?")

class ApplicationFormQuestion(BaseModel):
    question: str = Field(..., description="The question of the application form")
    description: Optional[str] = Field(None, description="The description of the question")
    answer: Optional[str] = Field(None, description="The answer to the question")

class BusinessCreateApplicationInput(BaseModel):
    recipient: Recipient = Field(..., description="The recipient of the application")
    applicant: Applicant = Field(..., description="The applicant of the application")
    application_form_questions: List[ApplicationFormQuestion] = Field(..., description="The questions of the application form")


business_create_application_input_example = {
    "recipient": {
        "name": "Tech Innovators Fund",
        "writing_style": "Formal",
        "programs": [
            {
                "name": "Startup Seed Funding",
                "description": "Funding for early-stage startups to help them grow.",
                "requirements": "Must be a registered business with a prototype.",
                "evaluation_criteria": "Innovation, market potential, and team strength.",
                "examples": "Previous recipients include XYZ Tech and ABC Innovations.",
                "avoid": "Avoid jargon and overly technical language."
            }
        ]
    },
    "applicant": {
        "what": "project",
        "name": "Green Energy Solutions",
        "description": "A project focused on developing sustainable energy solutions.",
        "highlights": "Developed a new solar panel technology with 20% more efficiency.",
        "users": "Residential and commercial property owners looking to reduce energy costs.",
        "team": [
            {
                "name": "Alice Johnson",
                "skills": "Renewable energy, project management",
                "projects": "Led the development of a wind turbine project.",
                "companies": "Worked at SolarTech as a project manager."
            }
        ],
        "funding_needed": {
            "amount": 500000,
            "currency": "USD",
            "usage": "To scale up production and marketing efforts."
        },
        "usps": "Unique solar panel technology with higher efficiency.",
        "competition": "Main competitors are SolarTech and GreenPower.",
        "business_model": "Selling solar panels directly to consumers and businesses."
    },
    "application_form_questions": [
        {
            "question": "What is the main goal of your project?",
            "description": "Describe the primary objective you aim to achieve."
        },
        {
            "question": "How will you use the funding?",
            "description": "Provide a detailed breakdown of how the funds will be allocated."
        }
    ]
}


class BusinessCreateApplicationOutput(BaseModel):
    selected_program: str = Field(..., description="The program that the application is for")
    application: List[ApplicationFormQuestion] = Field(..., description="The application for the project or company")


business_create_application_output_example = {
    "selected_program": "Startup Seed Funding",
    "application": [
        {
            "question": "What is the main goal of your project?",
            "description": "Describe the primary objective you aim to achieve.",
            "answer": "The main goal is to develop and commercialize a new solar panel technology that is 20% more efficient than current market offerings."
        },
        {
            "question": "How will you use the funding?",
            "description": "Provide a detailed breakdown of how the funds will be allocated.",
            "answer": "The funding will be used to scale up production, enhance marketing efforts, and expand our research and development team."
        }
    ]
}