# Security architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## User signup

- user specific master encryption key generated on user device & encrypted via login method before being uploaded to server
- user specific server encryption key is generated on server and stored in hashicorp vault
- username, email address and other less sensitive user data which server needs access to independent of user login are encrypted using server encryption key


## Chats

- for each chat a separate encryption key is generated
- on user device chat encryption key is encrypted using user master encryption key, before being uploaded to server 
- User device encrypts & decrypts chats via AES, using decrypted chat encryption key


## App skills

- if user hasn't explicitly mentioned via @ specific app skill, user has to first confirm each app skill call
- details of which data app skill had as input and created as output are visible in UI (and therefore also saved, encrypted on user device)
- output of apis are first processed by safety LLM request before being further processed by app skill (protection against prompt injection attacks) 


## App settings & memories

- if user hasn't explicitly mentioned via @ specific app settings & memories, user has to first confirm each the submitting of the requested app settings & memories


## Terms explained

### encryption_key_user_local

On user device generated encryption key during signup, encrypted via AES using signup Methode (password or passkey). If "Stay logged in" is selected during login, decrypted key will be stored in local-storage, else it's saved in session-storage. If no encryption key is found in either on page reload, user is auto logged out and all local user data are auto deleted (will be downloaded again on next login).

### encryption_key_user_server

On server generated encryption key during signup, encrypted & stored in hashicorp Vault. Used for encrypting data which server needs access to (email address).

### encryption_key_chat

On user device generated encryption key for each chat.
Encrypted on user device via AES using encryption_key_user_local.

### encryption_key_user_app

On user device generated encryption key for each app for which the user saves settings & memories. Generated the first time user is saving settings & memories for an app. Encrypted on user device via AES using encryption_key_user_local.

### pre_processing

Requests via mistral small model json output with keys:

- harmful_or_illegal_request_chance
- category
- selected_llm


### post_processing

Requests via mistral small model json output with keys:

- follow_up_user_message_suggestions
	- list of strings (with max 6 words)
- new_chat_user_message_suggestions
	- list of strings (with max 6 words)
- harmful_or_illegal_response_chance
	- int 0-10
	- if above 6: hide assistant response immediately and replace it with "Sorry, I think my response was problematic. Could you rephrase and elaborate your request?"

### server_error_processing

If server error occurs while processing user request, return default response:
"Sorry, an error occurred while I was processing your request. Be assured: the OpenMates team will be informed. Please try again later."

### app_skill_output_security_scan

Requests via mistral small model json output with keys:

- prompt_injection_attack_chance
	- int 0-10
	- Used for app skills with reasonable chance output could include prompt injection attack
	- if above 6: replace output with "Content replaced with this security warning. Reason: Security scan revealed high chance of prompt injection attack."