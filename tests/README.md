# Tests

This directory will contain primarly integration tests, which ensure that the entire system works together as expected.

Every file that is tested needs to link unitteets and integratikn tests into its file header (as comments or variable?) so LLM can auto test them after making changes, to see if they still work?

## Message processing

> Planned

This test will send a message via the web app ui an checks the following:
- pre-, main- and post-processing is working as expected and all generate all expected fields (no unexpected empty fields)
- user and assistant messages are stored in indexeddb encrypted with all fields, as well as in cache on server and directus for long term storage

## Chat right click options

> Planned

This test will ensure all the options that show up when right clicking on a chat are working as expected:

- copy -> the chat is copied to the clipboard in full with no empty fields
- download -> the chat is downloaded as a yaml file with all fields
- delete -> the chat is deleted from the indexeddb, cache on server and directus