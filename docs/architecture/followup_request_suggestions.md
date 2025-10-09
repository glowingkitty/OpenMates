# Followup request suggestions architecture 

- also show app skills and focus modes in suggestions, always include in auto complete
- the post processing after every assistant response generates 6 new follow up request suggestions
- for every chat, the last 30 follow up request suggestions (as a list) are encrypted and stored under the field 'encrypted_follow_up_request_suggestions' in the chat record
- new chat request suggestions are stored under a separate database model 'new_chat_request_suggestions', see [new_chat_request_suggestions.md](new_chat_request_suggestions.md)