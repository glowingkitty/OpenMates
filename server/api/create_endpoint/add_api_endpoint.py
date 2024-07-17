import sys
from helper.file_loader import load_markdown_file, extract_linked_filepaths, load_linked_files, extract_numbered_list_items
from helper.prompt_builder import build_llm_prompt
from helper.user_interaction import ask_user_questions, NoQuestionsError
from helper.llm_interface import send_request_to_llm
from helper.file_processor import FileProcessor
from helper.file_linker import generate_file_links

def main():
    try:
        # 1. Load new_api_endpoint.md file
        new_api_endpoint_content = load_markdown_file("new_api_endpoint.md")

        # 2. Extract and load linked files
        linked_filepaths = extract_linked_filepaths(new_api_endpoint_content)
        linked_files_content = load_linked_files(linked_filepaths)

        # 3. Load system prompt
        systemprompt_content = load_markdown_file("systemprompt_for_new_api_endpoint.md")

        # 4. Load and extract questions, then ask user
        requirements_content = load_markdown_file("requirements_questions.md")
        questions = extract_numbered_list_items(requirements_content)
        user_answers = ask_user_questions(questions)

        # 5. Create prompt for LLM
        llm_prompt = build_llm_prompt(
            new_api_endpoint_content,
            "\n".join([f"Q: {q}\nA: {user_answers[q]}" for q in questions]),
            systemprompt_content,
            linked_files_content
        )

        # 6. Send request to LLM
        llm_response = send_request_to_llm(llm_prompt)

        # 7. Process the LLM response
        file_processor = FileProcessor()
        file_processor.process_llm_response(llm_response)

        # 8. Generate file links for user
        modified_files = file_processor.get_modified_files()
        file_links = generate_file_links(modified_files)
        print("The following files were created or modified:")
        for link in file_links:
            print(link)

    except NoQuestionsError as e:
        print(f"Error: {e}")
        print("Exiting the program as there are no questions to ask.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()