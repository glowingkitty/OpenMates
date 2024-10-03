from typing import Literal, List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, ConfigDict
from server.api.models.apps.code.skills_code_plan import FileContext

# POST /{team_slug}/apps/code/write (generate or update code based on plan)

class CodeWriteInput(BaseModel):
    """This is the model for the incoming parameters for POST /{team_slug}/apps/code/write"""
    requirements: Optional[str] = Field(None, description="Final requirements in markdown format")
    coding_guidelines: Optional[str] = Field(None, description="Coding guidelines in markdown format")
    code_logic_draft: Optional[str] = Field(None, description="Code logic draft in markdown format")
    files_for_context: Optional[List[FileContext]] = Field(None, description="Files for context")
    file_tree_for_context: Optional[Dict[str, Any]] = Field(None, description="File tree for context")

    model_config = ConfigDict(extra="forbid")

class CodeChange(BaseModel):
    file_path: str = Field(..., description="Path of the file to be changed")
    type: Literal["new", "update", "delete"] = Field(..., description="Type of change")
    content: Optional[str] = Field(None, description="Content of the file (for 'new' or 'update' types)")
    insert_after: Optional[str] = Field(None, description="Line to insert after (for 'update' type)")
    insert_before: Optional[str] = Field(None, description="Line to insert before (for 'update' type)")

class CodeWriteOutput(BaseModel):
    """This is the model for the output of POST /{team_slug}/apps/code/write"""
    changes: List[CodeChange] = Field(..., description="List of code changes")
    changelog: str = Field(..., description="Changelog describing the changes made")
    costs_in_credits: int = Field(..., description="The total costs of the requests, in credits.")

    model_config = ConfigDict(extra="forbid")

code_write_input_example = {
    "requirements": "# Project Requirements\n\n## Main Features\n- User authentication\n- Task management\n- Real-time updates\n\n## Technical Stack\n- Frontend: React\n- Backend: Node.js, AWS Lambda\n- Database: DynamoDB\n\n...",
    "coding_guidelines": "# Coding Guidelines\n\n## Naming Conventions\n- Use camelCase for variables and function names\n- Use PascalCase for component names\n\n## Code Style\n- Use ESLint with Airbnb style guide\n- Use Prettier for code formatting\n\n...",
    "files_for_context": [
        {
            "path": "/src/App.js",
            "content": "import React from 'react';\n\nfunction App() {\n  return (\n    <div className=\"App\">\n      <h1>Task Management App</h1>\n    </div>\n  );\n}\n\nexport default App;"
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
    }
}

code_write_output_example = {
    "changes": [
        {
            "file_path": "/src/components/TaskList.js",
            "type": "new",
            "content": "import React from 'react';\n\nfunction TaskList() {\n  return (\n    <div className=\"TaskList\">\n      <h2>Task List</h2>\n      {/* Add task list implementation here */}\n    </div>\n  );\n}\n\nexport default TaskList;"
        },
        {
            "file_path": "/src/App.js",
            "type": "update",
            "content": "import React from 'react';\nimport TaskList from './components/TaskList';\n\nfunction App() {\n  return (\n    <div className=\"App\">\n      <h1>Task Management App</h1>\n      <TaskList />\n    </div>\n  );\n}\n\nexport default App;"
        }
    ],
    "changelog": "- Created new component: TaskList\n- Updated App.js to include TaskList component",
    "costs_in_credits": 500
}