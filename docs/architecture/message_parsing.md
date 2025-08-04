# Message parsing architecture

- one “parse_messag()” function for both parsing message_inputfield in active chat, as well as sent messages from user and assistant

## Input

- markdown text (of message draft, sent user request, sent assistant response)

## Output (message_inputfield)

- tiptap code / rendered code
- markdown tags which can’t be easily removed are not rendered but highlighted in different color: headings
- rendered previews which are auto parsed and can be edited via backspace: previews which can profit from added context or smaller footprint in message -> code block, document, sheet, web url, image url, YouTube url
- auto checks if any such preview is started via regex for code blocks, urls, tables. But while preview block is not closed, the text will only be color wise highlighted (to show the user the system recognizes the text as a preview, while keep enabling the user to edit the preview). Rendering will only happen once the preview is closed via closing ``` or space or empty line (depending on preview type)
- auto detect multiple previews of same type behind each other without space and if detected create a slider which can scroll previews from left to right

## Output (sent user request, sent assistant response)

- tiptap code / rendered code