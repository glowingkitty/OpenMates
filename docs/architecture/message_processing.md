# Message processing architecture

## Pre-Processing

- LLM request to mistral small 3.2
- system prompt:
    - requests a json output via JSON mode
        - language_code: language code of the last user request (default: EN)
- extract request category and therefore mate (software, marketing, etc.)
- define best fitting LLM for request based on complexity/usecase
- detect harmful / illegal requests
- detect which app settings & memories need to be requested by user to hand over to main processing (and requests those data via websocket connection)

## Main-processing

- LLM request to model selected by pre-processing
- system prompt:
    - is built up based on multiple instruction parts:
        1. Focus instruction (if focus mode active for chat)
        2. Base ethics instruction
        3. Mate specific instruction
        4. Apps instruction (about how to decide for which app skills/focus modes?)
- assistant creates response & function calls when requested (for starting focus modes and app skills)

## Post-Processing

- LLM request to mistral small 3.2
- system prompt:
    - requests a json output via JSON mode
- generates list of 6 “followup_request_suggestions” for current chat, based on last assistant response and previous user message
- generates “new_chat_request_suggestions” which are shown for new chats
- question: how to consider user interests without accidentally creating tracking profile of user?