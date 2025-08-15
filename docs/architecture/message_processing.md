# Message processing architecture

> Plans for updated processing architecture. Not yet fully implemented.

## Pre-Processing

- Split chat history into blocks of 70.000 tokens max
- send separate request for every 70.000 tokens, to be processed simultaneously
- then extract max harmful value, last language code, etc.
- LLM request to mistral small 3.2
- system prompt:
    - requests a json output via JSON mode
        - language_code: language code of the last user request (default: EN)
- extract request category and therefore mate (software, marketing, etc.)
- define best fitting LLM for request based on complexity/usecase
- detect harmful / illegal requests
- detect which app settings & memories need to be requested by user to hand over to main processing (and requests those data via websocket connection)
- “tags” field, which outputs a list of max 10 tags for the request, based on which the frontend will send the top 3 “similar_past_chats_with_summaries” (and allow user to deactivate that function in settings)
- “prompt_injection_chance” -> extract chance for prompt injection, to then include in system prompt explicit warning to not follow request but continue the conversation in a better direction

## Main-processing

- LLM request to model selected by pre-processing
- system prompt:
    - is built up based on multiple instruction parts:
        1. Focus instruction (if focus mode active for chat)
        2. Base ethics instruction
        3. Mate specific instruction
        4. Apps instruction (about how to decide for which app skills/focus modes?)
- input:
	- chat history
	- similar_past_chats (based on pre-processing)
	- user data
		- interests (related to request or random, for privacy reasons. Never include all interests to prevent user detection.)
		- preferred learning style (visual, auditory, repeating content, etc.)
- assistant creates response & function calls when requested (for starting focus modes and app skills)

## Post-Processing

- LLM request to mistral small 3.2
- system prompt:
		- include ethics system prompt
    - requests a json output via JSON mode
- generates list of 6 “followup_request_suggestions” for current chat, based on last assistant response and previous user message
- generates “new_chat_request_suggestions” which are shown for new chats
- consider learning type of user (if they prefer learning visually with videos, read books, or other methods)
- for topics which look like something the user wants to likely learn again, reserve one question for learning specific follow up question (“Test me about this topic”, “Prepare me for an upcoming test”, “Repeat teaching me about this every week”, etc.)
- “chat_summary” field, which takes the previous chat summary (if it exists) + the last user message and assistant response to create an updated chat summary (2,3 sentences.)
- “tags” field, which outputs a list of max 10 tags based on the existing tags for the chat (if they exists) + the last user message and assistant response to create an updated tags list
- question: how to consider user interests without accidentally creating tracking profile of user?