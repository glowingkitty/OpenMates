# Pricing architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

- user buys usage credits
- credits never expire
- pay per skill use
- skills can charge:
	- per usage
	- per input tokens
	- per output tokens
	- per unit (per image, per video)
	- per time (per minute of audio, per second of video)
	- different prices depending on model (mistral medium vs claude 4 sonnet for example)
- minimum 1 credit charged per request
- user needs to confirm when predicted skill use cost (before executing skill) is above treshold
- user is charged for all input and output tokens from main processing flow (including function calls)
- in billing section user is shown usage / pricing details per chat
- user can export chat with full text content (full markdown, full output of function calls, etc.), both for understanding the chat context bettet and to confirm pricing calculation when user os skeptical. Chat export includes billing.yml overview of all requests and their billing details and token count
- if user didnt mention @appname or @skillname in request, always ask fist for app skill executing confirmation by default (but allow this to be changed in settings to auto run skills if price below X)
- "Run app skill XY?" confirmation question includes estimated price if that can be calculated (for example: generating an image, generate a video, etc.) or else price of skill and for which unit (per minute, per input tokens, etc.)
- if chat costs go above treshold, user is asked if they want to continue the chat or start a new chat
- prices are listed in appstore section for each app skill


## Pricing / billing flow

### Web App

- user sends new message in chat
- server checks if user has at least 1 credit remaining
- if yes, message is processed via pre-processing, main-processing and together with assistant response in post-processing
- if app skill is called during main-processing:
	- calculate estimate for costs of app skill usage
	- check if user has enough credits for app skill use
	- charge credits directly once the costs occur (first from credits amount on server cache, then update server database)
	- once frontend receives completed app skill call output, encrypt metadata on client via wrapped encryption key and send to server for long term storage in database
- while response stream from main-processing is received, check with every generayed paragraph if calculated costs start to exceed remaining usage credits of user (by comparison to up to date server cache value of remaining credits of user)
- once assistant response is completed, charge either based on number of tokens which api output calculated, or if that number isn't given, based on calculated number of tokens (first update server cache, then server database)

### Scenarios

1. While processing stream of response the calculated cost of the output is exceeding remaining credits of user
	-  request will be interrupted, user will receive a separate "Ups... your usage credits just ran out. Please click here to purchase new usage credits to continue with this request."
	- once credits are purchased, the message changes to "Your have enough credits again to continue this request. Click here to resume." -> once clicked this will make the message disappear and send the existing chat history plus a "Continue" in the chat or user language 

2. User does not have enough credits for app skill use
	- just return existing function call draft to frontend for sync and show in web ui "You need at least X more credits for this app skill use. Click here to purchase new credits before you can continue."
	- once credits are purchased, text in chat changes to "Your have enough credits again to continue this request. Click here to resume."

3. User has no credits when making a request.
	- user receives fixed response "Sorry, you don't have any credits left. Click here to purchase more credits, before we can continue."
