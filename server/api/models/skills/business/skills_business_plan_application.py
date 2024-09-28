from pydantic import BaseModel, Field, HttpUrl
from typing import Literal, List, Optional
from server.api.models.skills.business.skills_business_create_application import Applicant, Recipient

# POST /{team_slug}/skills/business/plan_application

class BusinessPlanApplicationInput(BaseModel):
    applicant: Applicant = Field(..., description="The applicant of the application")
    recipient_website_urls: Optional[List[str]] = Field(None, description="Website URLs of recipient/programs.")
    recipient_pdf_documents: Optional[List[HttpUrl]] = Field(None, description="Links to PDF documents for of recipient/programs.")
    recipient_description: Optional[str] = Field(None, description="Description of the recipient")
    recipient_programs_description: Optional[str] = Field(None, description="Description of the programs")


class BusinessPlanApplicationOutput(BaseModel):
    recipient: Recipient = Field(..., description="The recipient of the application")

business_plan_application_input_example = {
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
    "recipient_website_urls": [
        "https://www.techinnovatorsfund.com",
        "https://www.techinnovatorsfund.com/programs"
    ],
    "recipient_pdf_documents": [
        "https://www.techinnovatorsfund.com/documents/report.pdf"
    ],
    "recipient_description": "Tech Innovators Fund is a venture capital firm that invests in early-stage startups focused on technology and innovation.",
    "recipient_programs_description": "Startup Seed Funding is a program that provides funding to early-stage startups with high growth potential."
}

business_plan_application_output_example = {
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
    }
}
