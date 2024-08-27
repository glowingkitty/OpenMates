- /skills/code/plan
    - endpoint contains multiple questions to build up the requirements

      - phase 1 (first request to endpoint):
        - input:
          - fixed requirements questions
            - main features?
            - target platform?
            - target users & user needs?
            - infrastructure context? (server, cloud provider, services, etc.)
            - specific tech to be used? (programming languages, frameworks, APIs, dependencies, etc.)
            - security & data privacy?
            - error handling?
            - what kind of testing implemented?
            - scaling & performance requirements?
            - naming conventions?
            - existing templates?
            - comments & documentation requirements?
            - other requirements?
          - code_git_url (optional, string)
          - code_zip (optional, attached file to request)
          - code_file (optional, string)
          - other_context_files (example JPGs, PNGs, PDFs)
        - processing:
          - extract from the git repo/zip file/code file a folder/file tree that includes all functions
          - ask LLM in combination with fixed requirements answers and folder/file tree and other_context_files to create:
            - LLM generated questions to further clearify the requirements
        - output:
          - LLM generated questions to further clearify the requirements

      - phase 2 (second request to endpoint):
        - input:
          - answers to fixed requirements questions
          - code_git_url (optional, string)
          - code_zip (optional, attached file to request)
          - code_file (optional, string)
          - other_context_files (example JPGs, PNGs, PDFs)
          - answers to LLM generated questions based on input requirements
        - processing:
          - extract from the git repo/zip file/code file a folder/file tree that includes all functions
          - then ask LLM in combination with ALL requirements answers and folder/file tree to create:
            - requirements (auto save requirements for project to settings?)
            - coding guidelines (auto save guidelines for tech to settings?)
            - files for context
        - output:
          - requirements
          - coding guidelines
          - code logic draft
          - files for context
          - file tree for context

      - phase 3 (third request to endpoint, optional, correct suggestion):
        - input:
          - requested corrections
          - earlier input:
            - answers to fixed requirements questions
            - code_git_url (optional, string)
            - code_zip (optional, attached file to request)
            - code_file (optional, string)
            - other_context_files (example JPGs, PNGs, PDFs)
            - answers to LLM generated questions based on input requirements
          - generated output:
            - requirements
            - coding guidelines
            - code logic draft
            - files for context
            - file tree for context
        - processing:
          - ask LLM to improve the generated output based on the requested corrections
        - output:
          - requirements
          - coding guidelines
          - code logic draft
          - files for context
          - file tree for context
          - costs in credits

- /skills/code/write
    - input:
      - requirements (str, markdown format)
      - coding guidelines (str, markdown format)
      - files for context (dict)
      - file tree for context (dict)
    - processing:
      - asks the LLM to generate a dict with all new files and changes to existing files
        - example structure:
          - {"new":[{"path":"/newfile.py","content":"..."}],"updated":[{"path":"/existingfile.py","target}]}
    - - output:
      - changes: [
          {
            "file_path": "/path/to/file.py",
            "type": "new" | "update" | "delete",
            "content": "...", (if "new" or "update")
            "insert_after": "function_name() {" | null, (if "update")
            "insert_before": "}" | null (if "update")
          }
        ]
      - changelog (str)
      - costs in credits (int)