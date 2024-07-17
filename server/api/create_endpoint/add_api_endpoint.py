import sys
from helper.file_loader import load_markdown_file, extract_linked_filepaths, load_linked_files, extract_numbered_list_items
from helper.prompt_builder import build_llm_prompt
from helper.user_interaction import ask_user_questions, NoQuestionsError
from helper.llm_interface import send_request_to_llm
from helper.file_processor import FileProcessor
import json


def main():
    try:
        # # 1. Load new_api_endpoint.md file
        # new_api_endpoint_content = load_markdown_file("new_api_endpoint.md")

        # # 2. Extract and load linked files
        # linked_filepaths = extract_linked_filepaths(new_api_endpoint_content)
        # linked_files_content = load_linked_files(linked_filepaths)

        # # 3. Load system prompt
        # systemprompt_content = load_markdown_file("systemprompt_for_new_api_endpoint.md")

        # # 4. Load and extract questions, then ask user
        # requirements_content = load_markdown_file("requirements_questions.md")
        # questions = extract_numbered_list_items(requirements_content)
        # user_answers = ask_user_questions(questions)

        # # 5. Create prompt for LLM
        # llm_prompt = build_llm_prompt(
        #     new_api_endpoint_content,
        #     "\n".join([f"Q: {q}\nA: {user_answers[q]}" for q in questions]),
        #     systemprompt_content,
        #     linked_files_content
        # )

        # # 6. Send request to LLM
        # llm_response = send_request_to_llm(llm_prompt)

        # # Save LLM response as JSON file
        # with open('llm_response.json', 'w') as json_file:
        #     json.dump(llm_response, json_file, indent=2)

        with open('llm_response.json', 'r') as json_file:
            llm_response = json.load(json_file)

        # 7. Process the LLM response
        file_processor = FileProcessor()
        file_processor.process_llm_response(llm_response)

        # 8. Print modified files for user
        updated_files = file_processor.get_updated_files()
        created_files = file_processor.get_created_files()

        print("\n📝 Updated files:")
        for file_path in updated_files:
            print(f"  ✏️ {file_path}")

        print("\n🆕 Newly created files:")
        for file_path in created_files:
            print(f"  ➕ {file_path}")

    except NoQuestionsError as e:
        print(f"Error: {e}")
        print("Exiting the program as there are no questions to ask.")
        sys.exit(1)

if __name__ == "__main__":
    main()