from pydantic import BaseModel, Field
from typing import Literal, List, Optional

# POST /{team_slug}/skills/business/create_pitch

class BusinessCreatePitchInput(BaseModel):
    what: Literal["project", "company"] = Field(..., description="Is the pitch for a project or a company?")
    name: str = Field(..., description="What is the name of the project or company?")
    existing_pitch: Optional[str] = Field(None, description="If you already have a pitch, you can paste it here. Otherwise, leave it blank.")
    short_description: Optional[str] = Field(None, description="Provide a brief description of the project or company in one or two sentences.")
    in_depth_description: Optional[str] = Field(None, description="Provide an in-depth description of the project or company.")
    highlights: Optional[List[str]] = Field(None, description="List the highlights of the project or company that you are excited about.")
    impact: Optional[str] = Field(None, description="What is the impact of the project or company?")
    potential_future: Optional[str] = Field(None, description="What is the potential future of the project or company?")
    target_audience: Optional[str] = Field(None, description="Who is the target audience for the pitch?")
    unique_selling_proposition: Optional[str] = Field(None, description="What makes the project or company unique?")
    goals: Optional[str] = Field(None, description="What are the goals of the pitch? What should the audience do after hearing the pitch or take away?")
    market_analysis: Optional[str] = Field(None, description="Provide an analysis of the market, including size, trends, and competitive landscape.")
    users: Optional[str] = Field(None, description="Who are the users of the project or company?")
    problems: Optional[str] = Field(None, description="What problems does the project or company solve?")
    solutions: Optional[str] = Field(None, description="What solutions does the project or company offer?")
    team_information: Optional[str] = Field(None, description="Details about the team members and their expertise.")
    financial_projections: Optional[str] = Field(None, description="Basic financial projections or current financial status.")
    customer_testimonials: Optional[List[str]] = Field(None, description="Quotes or feedback from existing customers.")
    pitch_type: Literal[
        "elevator_pitch",
        "one_liner_pitch",
        "executive_summary_pitch",
        "investor_pitch",
        "sales_pitch",
        "product_demo_pitch",
        "visionary_pitch",
        "other"
    ] = Field("elevator_pitch", description=(
        "What type of pitch are you creating? "
        "Options are: "
        "elevator_pitch (a very short pitch, typically 30 seconds to 2 minutes), "
        "one_liner_pitch (a single sentence that captures the essence of the project), "
        "executive_summary_pitch (a concise summary, usually 1-2 paragraphs), "
        "investor_pitch (a detailed pitch aimed at potential investors, often including financials and business plans), "
        "sales_pitch (focused on selling a product or service to a customer), "
        "product_demo_pitch (a pitch that includes a demonstration of the product), "
        "visionary_pitch (focuses on the long-term vision and impact of the project)."
    ))
    pitch_type_other_use_case: Optional[str] = Field(None, description="If you selected 'other', describe for what use case you are using the pitch.")


business_create_pitch_input_example = {
    "what": "project",
    "name": "GreenThumb",
    "existing_pitch": None,
    "short_description": "GreenThumb is a mobile app that helps urban dwellers grow their own vegetables in small spaces.",
    "in_depth_description": "GreenThumb provides step-by-step guides, personalized tips, and a community platform for urban gardeners. Our app helps users maximize their small spaces, whether it's a balcony, rooftop, or windowsill, to grow their own fresh vegetables.",
    "highlights": [
        "User-friendly interface designed for beginners",
        "Personalized gardening tips based on location and season",
        "Community feature for sharing progress and tips"
    ],
    "impact": "GreenThumb aims to empower urban residents to grow their own food, promoting sustainability and healthy living.",
    "potential_future": "We plan to introduce premium features, such as advanced gardening techniques and exclusive content, and expand our user base globally.",
    "target_audience": "Urban residents with limited space who are interested in gardening and sustainable living.",
    "unique_selling_proposition": "GreenThumb's personalized tips and community support make it easier for beginners to start and succeed in urban gardening.",
    "goals": "We aim to acquire 50,000 users within the first year and secure $200,000 in seed funding to enhance app features and marketing efforts.",
    "market_analysis": "The urban gardening market is growing as more people seek sustainable living options. Our research shows a significant interest in gardening among urban residents, with few apps offering comprehensive support for small-space gardening.",
    "users": "Urban residents with limited space who are interested in gardening and sustainable living.",
    "problems": "Many urban residents struggle to find time and space for gardening, and there are few resources to help them get started.",
    "solutions": "GreenThumb provides a mobile app that offers step-by-step guides, personalized tips, and a community platform for urban gardeners.",
    "team_information": "Our team consists of a horticulturist, a software developer, and a marketing specialist, all passionate about urban gardening and sustainability.",
    "financial_projections": "We project revenues of $500,000 within the first two years, with a break-even point at year one.",
    "customer_testimonials": [
        "GreenThumb made it so easy for me to start my own balcony garden. - Jane D.",
        "I love the community feature where I can share my progress and get tips from others. - John S."
    ],
    "pitch_type": "investor_pitch",
    "pitch_type_other_use_case": None
}


class BusinessCreatePitchOutput(BaseModel):
    pitch: str = Field(..., description="The pitch for the project or company")
    pitch_type: Literal[
        "elevator_pitch",
        "one_liner_pitch",
        "executive_summary_pitch",
        "investor_pitch",
        "sales_pitch",
        "product_demo_pitch",
        "visionary_pitch",
        "other"
    ] = Field(..., description="The type of pitch that was created")
    pitch_type_other_use_case: Optional[str] = Field(None, description="If 'other' was selected, describes for what use case the pitch is being used.")

business_create_pitch_output_example = {
    "pitch": (
        "GreenThumb is transforming urban living by making it easy for city dwellers to grow their own vegetables in small spaces. "
        "Our mobile app provides step-by-step guides, personalized tips, and a supportive community platform for urban gardeners. "
        "With a user-friendly interface and tailored advice based on location and season, GreenThumb empowers beginners to succeed in urban gardening. "
        "We have already seen a strong interest in our app, with users praising its ease of use and community features. "
        "We are seeking $200,000 in seed funding to enhance our app features, expand our user base, and promote sustainable living in urban areas. "
        "Join us in our mission to bring the joy of gardening to city residents and promote a healthier, more sustainable lifestyle."
    ),
    "pitch_type": "investor_pitch",
    "pitch_type_other_use_case": None
}