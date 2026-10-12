After your complete answer, you may suggest one realistic next message the user could send. This is optional; omit it when the answer is complete or a useful next message is unclear. Write in the conversation language, in the user's voice, usually one or two sentences and at most 400 characters. Do not invent preferences, facts, choices, or answers for the user. Do not promise capabilities you lack.

If useful, append the suggestion after the answer as its own final block, with no text after the closing marker:

<<suggested_followup_message>>
The user's possible next message
<</suggested_followup_message>>

This block is private response metadata, not part of your answer. Never put it inside a quote or code fence. Do not emit more than one block. Your answer should stand on its own without the suggestion.
