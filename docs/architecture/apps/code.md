# Code App architecture

The Code app allows for viewing, writing and editing code / software projects.

## Embedded previews

### Code

> Note: Not yet implemented, but high priority.

Used every time a code block is contained in a message in the chat history or message input field.

Can include a filepath in the first line of the code block where we also define the language of the code: `{language}:{filepath}`.

Data processing is done via unified `parseMessage()` function described in [message_parsing.md](../message_parsing.md).

#### Code | Processing

[![Code | Processing | Preview & Fullscreen view in mobile & desktop](../../images/apps/code/previews/code/processing.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3508-41238&t=V4FPCQaihiRx7h7e-4)

When the code is still being generated, those layouts are used.

##### Code | Processing | Input example (Markdown code block)

````
```python:stripe_payment_processor.py
import stripe
from datetime import datetime

# Initialize Stripe with your secret key
stripe.api_key = "sk_test_..."

def process_payment(amount, currency, payment_method, customer_email):
   try:
       # Create a PaymentIntent to charge the customer
       payment_intent = 
            stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to smallest currency unit (e.g., cents)
            currency=currency,
            payment_method=payment_method,
            confirmation_method='automatic',
            confirm=True,  # Attempt to confirm and process immediately
            receipt_email=customer_email,
            return_url="https://example.com/return"  # Required for payment methods that redirect
        )
# ...
```
````

##### Code | Processing | Output

- tiptap node (lightweight) with:
  - language (string)
  - line count (number)
  - contentRef (string) pointing to full source in client ContentStore (memory + IndexedDB)
  - contentHash? (string, sha256 when finished; used for preview caching)
  - preview is derived at render-time (first 12 lines only)
  - "Write" text and 'modify' icon, indicating that the code is still being written
- Figma design:
  - [Preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=2264-21760&t=JIw9suqrshvmsdFU-4)
  - [Preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=1764-16509&t=JIw9suqrshvmsdFU-4)


##### Code | Processing | Fullscreen view

Show code in fullscreen mode, with preview element in bottom of the screen (with line count and "Write" text and icon, indicating that the code is still being written). The download and copy to clipboard buttons are also available in the top left corner. Top right corner has the fullscreen button, which closes the fullscreen view.

Figma design:

- [Mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3498-40814&t=JIw9suqrshvmsdFU-4)
- [Desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3498-40841&t=JIw9suqrshvmsdFU-4)


#### Code | Finished

[![Code | Finished | Preview & Fullscreen view in mobile & desktop](../../images/apps/code/previews/code/finished.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3508-41242&t=V4FPCQaihiRx7h7e-4)

When the code is finished being generated, those layouts are used.

##### Code | Finished | Input example (Markdown code block)

````
```python:stripe_payment_processor.py
import stripe
from datetime import datetime

# Initialize Stripe with your secret key
stripe.api_key = "sk_test_..."

def process_payment(amount, currency, payment_method, customer_email):
   try:
       # Create a PaymentIntent to charge the customer
       payment_intent = 
            stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to smallest currency unit (e.g., cents)
            currency=currency,
            payment_method=payment_method,
            confirmation_method='automatic',
            confirm=True,  # Attempt to confirm and process immediately
            receipt_email=customer_email,
            return_url="https://example.com/return"  # Required for payment methods that redirect
        )
# ...
```
````

##### Code | Finished | Output

- tiptap node (lightweight) with:
  - language (string)
  - line count (number)
  - filename (string)
  - contentRef (string) pointing to full source in client ContentStore (loaded on fullscreen)
  - contentHash (string, sha256 for immutable snapshot/caching)
  - preview is derived at render-time (first 12 lines only)

- Figma design:
  - [Preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3423-41511&t=JIw9suqrshvmsdFU-4)
  - [Preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3423-41498&t=JIw9suqrshvmsdFU-4)



##### Code | Finished | Fullscreen view

Show code in fullscreen mode, with preview element in bottom of the screen (with filename, line count and language of the code). The download, copy to clipboard and modify buttons are also available in the top left corner. Top right corner has the fullscreen button, which closes the fullscreen view. Full source is resolved via `contentRef` from the client ContentStore and can stream/live-update independently of the preview node.

> Note: Modify functionality is not yet planned out and should be added in the future.

Figma design:

- [Mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3406-38017&t=V4FPCQaihiRx7h7e-4)
- [Desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3406-38057&t=V4FPCQaihiRx7h7e-4)


#### Code | Chat example

[![Code | Chat example](../../images/apps/code/previews/code/chat_example.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3508-41244&t=V4FPCQaihiRx7h7e-4)

Shows how code previews are rendered in a chat message. Mobile / desktop layouts are used depending on the viewport width.

**Multiple previews:**

General rule for all previews/apps: If multiple previews of the same type are rendered in a chat message, they should be grouped together in a horizontally scrollable container. The previews must be sorted from status "Processing" (left) to "Finished" (right), so that the user can always see if there are any unfinished previews. Scroll bar is visible if there are scrollable elements.

**Single preview:**

If there is only one preview of the same type, no additional container with scrollbar is needed. If a text is following the preview, it will be regularly rendered below the preview. Same if a preview or group of previews of another type is following the preview.


### Notebook

> Note: To be implemented in the future.

Renders the Jupyter notebook json via notebookjs and adds execute buttons to it, triggering the execution in an e2b sandboxed instance and updating the Jupyter notebook json with the cell output. 

#### Input example (Markdown code block with Jupyter notebook json):

````
```json
{
  "cells": [
    {
      "cell_type": "code",
      ...
    }
  ]
}
```
````

#### Output:

- tiptap node with:
  - json code (string)
  - filename (string)
  - cell count (number)


## Skills

### Run Code

Uses e2b (https://github.com/e2b-dev/infra) to start a vm where the user code can run safely. From python to JavaScript and more. Including that the user can take control over the coding environment via a code-server instance installed on the vm. Great for testing, Jupyter notebook, and more.

### Get error logs

Use Sentry or similar providers to get the error logs after an issue occured, for better debugging and fixing of the issue.


### Get docs

Use context7.com API to get docs for the code. If no docs found, use web search + web read to get docs.

## Focuses

### Reverse engineer API

Starts focus mode that focuse on using stagehand / playwright / web app to analyze api which website is using in background. With the end goal to create a Jupyter notebook file with the api being successfully used.