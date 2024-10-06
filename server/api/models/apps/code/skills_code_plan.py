from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator
import base64

# POST /{team_slug}/apps/code/plan (plan code structure and logic)

class Question(BaseModel):
    question: Optional[str] = Field(None, description="The question text")
    answer: Optional[str] = Field(None, description="The answer to the question")

    @model_validator(mode='after')
    def check_question_or_answer(self):
        if self.question is None and self.answer is None:
            raise ValueError("At least one of 'question' or 'answer' must be provided")
        return self


class QAndABasics(BaseModel):
    short_description: Optional[Question] = Field(
        default=Question(question="Provide a brief description of the project in one or two sentences."),
        description="A brief description of the project"
    )
    main_features: Optional[Question] = Field(
        default=Question(question="What are the main features of the project?"),
        description="What are the main features of the project?"
    )
    target_platform: Optional[Question] = Field(
        default=Question(question="What is the target platform for the project?"),
        description="What is the target platform for the project?"
    )
    target_users: Optional[Question] = Field(
        default=Question(question="Who are the target users and what are their needs?"),
        description="Who are the target users and what are their needs?"
    )
    infrastructure_context: Optional[Question] = Field(
        default=Question(question="What is the infrastructure context (server, cloud provider, services, etc.)?"),
        description="What is the infrastructure context (server, cloud provider, services, etc.)"
    )
    specific_tech: Optional[Question] = Field(
        default=Question(question="What specific technologies will be used (programming languages, frameworks, APIs, dependencies, etc.)?"),
        description="What specific technologies will be used (programming languages, frameworks, APIs, dependencies, etc.)"
    )
    security_requirements: Optional[Question] = Field(
        default=Question(question="What are the security and data privacy requirements?"),
        description="What are the security and data privacy requirements?"
    )
    error_handling: Optional[Question] = Field(
        default=Question(question="What are the error handling requirements?"),
        description="What are the error handling requirements?"
    )
    testing_requirements: Optional[Question] = Field(
        default=Question(question="What are the testing implementation requirements?"),
        description="What are the testing implementation requirements?"
    )
    scaling_requirements: Optional[Question] = Field(
        default=Question(question="What are the scaling and performance requirements?"),
        description="What are the scaling and performance requirements?"
    )
    naming_conventions: Optional[Question] = Field(
        default=Question(question="What naming conventions should be followed?"),
        description="What naming conventions should be followed?"
    )
    existing_templates: Optional[Question] = Field(
        default=Question(question="Are there any existing templates to be used?"),
        description="Are there any existing templates to be used?"
    )
    documentation_requirements: Optional[Question] = Field(
        default=Question(question="What are the comments and documentation requirements?"),
        description="What are the comments and documentation requirements?"
    )
    other_requirements: Optional[Question] = Field(
        default=Question(question="Are there any other requirements?"),
        description="Are there any other requirements?"
    )

    @model_validator(mode='after')
    def set_default_questions(self):
        for field, value in self.__dict__.items():
            if value is not None and value.question is None:
                default_question = self.model_fields[field].default.question
                setattr(self, field, Question(question=default_question, answer=value.answer))
        return self

def is_base64(s):
    try:
        return base64.b64encode(base64.b64decode(s)).decode() == s
    except Exception:
        return False

class FileContext(BaseModel):
    path: str = Field(..., description="Path of the file")
    content: str = Field(..., description="Content of the file")

    @model_validator(mode='after')
    def validate_file_extension(self):
        # List of potentially dangerous file extensions
        dangerous_extensions = [
            '.exe', '.dll', '.so', '.dylib',  # Executable files
            '.bat', '.cmd', '.sh', '.ps1',    # Script files that could execute on the system
            '.msi', '.pkg', '.deb', '.rpm',   # Installation packages
            '.jar', '.war',                   # Java archives (can be executable)
            '.app',                           # macOS application bundle
            '.vbs', '.vbe',                   # Visual Basic scripts
            '.sys',                           # System files
            '.com',                           # DOS command files
        ]

        file_extension = os.path.splitext(self.path.lower())[1]
        if file_extension in dangerous_extensions:
            raise ValueError(f"File type not allowed: {file_extension}")

        return self


class CodePlanInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/apps/code/plan"""
    q_and_a_basics: QAndABasics = Field(..., description="Basic questions to clearify requirements.")
    q_and_a_followup: Optional[dict[str,Question]] = Field(None, description="Follow up questions to clearify requirements.")
    code_git_url: Optional[str] = Field(None, description="URL of the Git repository. Must end with .git.")
    code_zip: Optional[str] = Field(None, description="Base64 encoded ZIP file containing a code repo. Can contain folders and files.")
    code_file: Optional[FileContext] = Field(None, description="Code file for context.")
    other_context_files: Optional[List[FileContext]] = Field(None, description="Other context files (e.g., JPGs, PNGs, PDFs) as base64 encoded strings")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def check_code_source(self):
        sources = [self.code_git_url, self.code_zip, self.code_file]
        if sum(source is not None for source in sources) > 1:
            raise ValueError("Only one of 'code_git_url', 'code_zip', or 'code_file' should be provided.")
        if self.code_git_url and not self.code_git_url.lower().endswith('.git'):
            raise ValueError("Git URL must end with .git")
        return self

    @model_validator(mode='after')
    def check_code_zip(self):
        if self.code_zip and not is_base64(self.code_zip):
            raise ValueError("'code_zip' must be a base64 encoded string.")
        return self



class CodePlanOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/apps/code/plan"""
    q_and_a_followup: Optional[dict[str,Question]] = Field(None, description="Second round of questions to clearify requirements.")
    requirements: Optional[str] = Field(None, description="Final requirements in markdown format")
    coding_guidelines: Optional[str] = Field(None, description="Coding guidelines in markdown format")
    code_logic_draft: Optional[str] = Field(None, description="Code logic draft in markdown format")
    files_for_context: Optional[List[FileContext]] = Field(None, description="Files for context")
    file_tree_for_context: Optional[Dict[str, Any]] = Field(None, description="File tree for context")
    costs_in_credits: int = Field(..., description="The total costs of the requests, in credits.")

code_plan_input_example = {
    "q_and_a_basics": {
        "short_description": {"answer": "A task management web application for small to medium-sized businesses with real-time updates and user authentication."},
        "main_features": {"answer": "User authentication, task management, real-time updates"},
        "target_platform": {"answer": "Web application"},
        "target_users": {"answer": "Small to medium-sized businesses"},
        "infrastructure_context": {"answer": "AWS, serverless architecture"},
        "specific_tech": {"answer": "React, Node.js, DynamoDB, AWS Lambda"},
        "security_requirements": {"answer": "HTTPS, JWT authentication, data encryption at rest"},
        "error_handling": {"answer": "Graceful error handling with user-friendly messages"},
        "testing_requirements": {"answer": "Unit tests, integration tests, end-to-end tests"},
        "scaling_requirements": {"answer": "Should handle up to 10,000 concurrent users"},
        "naming_conventions": {"answer": "camelCase for variables, PascalCase for components"},
        "documentation_requirements": {"answer": "JSDoc for functions, README.md for project overview"},
        "other_requirements": {"answer": "Accessibility compliance (WCAG 2.1)"}
    },
    "code_git_url": "https://github.com/example/project.git"
}

code_plan_input_example_2 = {
    "q_and_a_basics": {
        "short_description": {"answer": "A task management web application for small to medium-sized businesses with real-time updates and user authentication."},
        "main_features": {"answer": "User authentication, task management, real-time updates"},
        "target_platform": {"answer": "Web application"},
        "target_users": {"answer": "Small to medium-sized businesses"},
        "infrastructure_context": {"answer": "AWS, serverless architecture"},
        "specific_tech": {"answer": "React, Node.js, DynamoDB, AWS Lambda"},
        "security_requirements": {"answer": "HTTPS, JWT authentication, data encryption at rest"},
        "error_handling": {"answer": "Graceful error handling with user-friendly messages"},
        "testing_requirements": {"answer": "Unit tests, integration tests, end-to-end tests"},
        "scaling_requirements": {"answer": "Should handle up to 10,000 concurrent users"},
        "naming_conventions": {"answer": "camelCase for variables, PascalCase for components"},
        "documentation_requirements": {"answer": "JSDoc for functions, README.md for project overview"},
        "other_requirements": {"answer": "Accessibility compliance (WCAG 2.1)"}
    },
    "q_and_a_followup": {
        "task_manager_features": {"question": "What specific task management features are required?", "answer": "Task creation, assignment, due dates, priority levels, and status tracking"},
        "real_time_updates": {"question": "How should real-time updates be implemented?", "answer": "Use WebSockets for instant task updates and notifications"},
        "authentication_method": {"question": "What authentication method should be used for user login?", "answer": "Email/password login with option for OAuth 2.0 (Google and GitHub)"},
        "data_model": {"question": "What data model should be used for tasks and users?", "answer": "Tasks should have fields for title, description, assignee, due date, priority, and status. Users should have fields for name, email, role, and associated tasks."},
        "offline_functionality": {"question": "How should the application handle offline functionality?", "answer": "Implement offline caching for recent tasks and user data, with sync functionality when connection is restored"}
    },
    "code_git_url": "https://github.com/example/project.git"
}

code_plan_output_example = {
    "q_and_a_followup": {
        "task_manager_features": {"question": "What specific task management features are required?"},
        "real_time_updates": {"question": "How should real-time updates be implemented?"},
        "authentication_method": {"question": "What authentication method should be used for user login?"},
        "data_model": {"question": "What data model should be used for tasks and users?"},
        "offline_functionality": {"question": "How should the application handle offline functionality?"}
    },
    "costs_in_credits": 10
}

# This example will be used by the plan.py file for the endpoint processing to generate the full plan. The content of the files and the file_tree will be added via hardcoding.
code_plan_processing_output_example = {
    "requirements": "{project requirements as markdown text}",
    "coding_guidelines": "{coding guidelines as markdown text}",
    "code_logic_draft": "{code logic draft as markdown text}",
    "files_for_context": [{"path": "/src/App.js"}, {"path": "/src/index.js"}]
}


code_plan_output_example_2 = {
    "requirements": "# Project Requirements\n\n## Main Features\n- User authentication\n- Task management\n- Real-time updates\n\n## Task Management Features\n- Task creation\n- Task assignment\n- Due dates\n- Priority levels\n- Status tracking\n\n## Authentication\n- Email/password login\n- OAuth 2.0 integration (Google and GitHub)\n\n## Real-time Updates\n- WebSocket implementation for instant task updates and notifications\n\n## Data Model\n- Tasks: title, description, assignee, due date, priority, status\n- Users: name, email, role, associated tasks\n\n## Offline Functionality\n- Offline caching for recent tasks and user data\n- Sync functionality when connection is restored\n\n## Technical Stack\n- Frontend: React\n- Backend: Node.js with AWS Lambda\n- Database: DynamoDB\n- Infrastructure: AWS, serverless architecture\n\n## Security\n- HTTPS\n- JWT authentication\n- Data encryption at rest\n\n## Performance\n- Handle up to 10,000 concurrent users\n\n## Testing\n- Unit tests\n- Integration tests\n- End-to-end tests\n\n## Documentation\n- JSDoc for functions\n- README.md for project overview\n\n## Accessibility\n- WCAG 2.1 compliance",
    "coding_guidelines": "# Coding Guidelines\n\n## Naming Conventions\n- Use camelCase for variables and function names\n- Use PascalCase for component names\n- Use UPPER_CASE for constants\n\n## Code Style\n- Follow Airbnb JavaScript Style Guide\n- Use ESLint for code linting\n- Use Prettier for code formatting\n\n## React Best Practices\n- Use functional components and hooks\n- Keep components small and focused\n- Use PropTypes for type checking\n\n## Testing\n- Write unit tests for all components and functions\n- Aim for at least 80% code coverage\n- Use Jest and React Testing Library\n\n## Documentation\n- Use JSDoc for inline documentation\n- Keep README.md up-to-date\n- Document all API endpoints",
    "code_logic_draft": "1. Set up project structure\n   - Create React app\n   - Set up AWS Lambda functions\n   - Configure DynamoDB tables\n\n2. Implement user authentication\n   - Create login/signup forms\n   - Implement JWT authentication\n   - Set up OAuth 2.0 for Google and GitHub\n\n3. Develop task management features\n   - Create TaskList and TaskItem components\n   - Implement CRUD operations for tasks\n   - Add filtering and sorting functionality\n\n4. Set up real-time updates\n   - Implement WebSocket connection\n   - Create notification system\n\n5. Implement offline functionality\n   - Set up local storage for caching\n   - Implement sync mechanism\n\n6. Add error handling and validation\n\n7. Implement accessibility features\n\n8. Write tests\n   - Unit tests for components and functions\n   - Integration tests for API calls\n   - End-to-end tests for critical user flows\n\n9. Optimize performance\n   - Implement code splitting\n   - Add caching mechanisms\n\n10. Finalize documentation",
    "files_for_context": [
        {
            "path": "/src/App.js",
            "content": "import React from 'react';\nimport { BrowserRouter as Router, Route, Switch } from 'react-router-dom';\nimport Header from './components/Header';\nimport TaskList from './components/TaskList';\nimport TaskDetails from './components/TaskDetails';\nimport Login from './components/Login';\n\nfunction App() {\n  return (\n    <Router>\n      <div className=\"App\">\n        <Header />\n        <Switch>\n          <Route exact path=\"/\" component={TaskList} />\n          <Route path=\"/task/:id\" component={TaskDetails} />\n          <Route path=\"/login\" component={Login} />\n        </Switch>\n      </div>\n    </Router>\n  );\n}\n\nexport default App;"
        }
    ],
    "file_tree_for_context": {
        "root": {
            "src": {
                "components": {
                    "Header.js": [
                        "function Header()",
                        "const styles = StyleSheet.create({...})"
                    ],
                    "TaskList.js": [
                        "function TaskList({ tasks })",
                        "function TaskItem({ task })"
                    ]
                },
                "pages": {
                    "Home.js": [
                        "function Home()",
                        "const styles = StyleSheet.create({...})"
                    ],
                    "TaskDetails.js": [
                        "function TaskDetails({ taskId })",
                        "const styles = StyleSheet.create({...})"
                    ]
                },
                "utils": {
                    "api.js": [
                        "async function fetchTasks()",
                        "async function createTask(task)",
                        "async function updateTask(taskId, updates)"
                    ],
                    "helpers.js": [
                        "function formatDate(date)",
                        "function sortTasks(tasks, sortBy)"
                    ]
                },
                "App.js": [
                    "function App()",
                    "const styles = StyleSheet.create({...})"
                ],
                "index.js": [
                    "ReactDOM.render(<App />, document.getElementById('root'))"
                ]
            },
            "public": {
                "index.html": None,
                "favicon.ico": None
            },
            "package.json": None,
            "README.md": None
        }
    },
    "costs_in_credits": 18
}