from typing import List, Dict

class NoQuestionsError(Exception):
    """Raised when there are no questions to ask the user."""
    pass

def ask_user_questions(questions: List[str]) -> Dict[str, str]:
    """
    Ask the user a series of questions and collect their answers.

    Args:
        questions (List[str]): A list of questions to ask the user.

    Returns:
        Dict[str, str]: A dictionary where keys are questions and values are user answers.

    Raises:
        NoQuestionsError: If there are no questions to ask.
    """
    if not questions:
        raise NoQuestionsError("No questions found.")

    answers = {}
    for i, question in enumerate(questions, 1):
        answer = input(f"Question {i}: {question}\nYour answer: ")
        answers[question] = answer
    return answers