# Web app architecture

## Current state

Currently we have a separate website app.openmates.org and openmates.org site, where the openmates.org is forwarding to app.openmates.org (since the old informative website got too outdated).
The web app allows the user to interact with OpenMates after signup/login.

## Planned state

- one single openmates.org web app, which also replaces the informative website
- advantages: drastically reduced development effort, direct introduction to the web app and its capabilities
- if user is not logged in, web app loads default demo chats in chats list which show only the currently implemented features.
- on loading of the web app, the user sees a new assistant message showing up, which introduces the user to OpenMates, how its different to other services, how to access the chats list, the app store, docs and more - as well giving an outlook of what is planned for the future.
- this way we introduce the user to how to use the web app and what its capabilities are.
- Message input field shows 'Signup to send' button instead of 'Send' button, which then opens the signup flow and keeps the user message saved as a draft, to send later once signed up
- on signup completion, the demo chats are kept and the user receives another assistant message 'Thanks for signing up! If you don't want to see the example chats anymore, you can right click & delete them - or ask me to delete them.'
- demo chats:
    - "Welcome to OpenMates!" -> short introduction to OpenMates
    - "What makes OpenMates different?" -> explain the different areas/features of OpenMates (can also include youtube clips explaining the different areas/features)
    - "October 2025: New features & changes" -> summarize the new changes to OpenMates from last or current month, based on changelog on github?
    - "Example: Learn something new" -> (example chat for learning about a topic, without app use)
    - "Example: The power of apps" -> (example chat involving app skill use + focus mode: getting transcript from video, factchecking it with web research)
    - "Example: Personalized, but privacy preserving." -> (example chat involving app settings & memories: planning a trip based on personal preferences)
    - "OpenMates for developers" -> explain the features & planned features for developers and add link to Signal developer group for contributing
    - "Stay up to date & contribute" -> show all links to social media accounts & community links: Signal Dev group, Discord, Meetup, Luma, Instagram, YouTube, Mastodon, Pixelfed, etc.
- demo chats must have fixed chat id so we can link to individual chats from elsewhere (Example: "https://openmates.org/chat/stay-up-to-date-contribute")
- demo chats must be part of the precompiled static page, for SEO optimization and loading speed

See also: [Onboarding Architecture](onboarding.md) for planned user onboarding features.

### Welcome to OpenMates!

Hey there and welcome to OpenMates!
With OpenMates you have a full team of digital team mates (AI chatbots who are experts in various fields) to answer your questions, brainstorm ideas and fulfill various tasks using a wide range of Apps.

If you want to learn more about how OpenMates is different to ChatGPT, Claude, Manus, etc. - check out this chat:
“What makes OpenMates different?”

Or check one of the other example chats in the chat history (accessible via the menu button in the top left) - or signup (its fast, affordable & simple) and test out OpenMates yourself!

### What makes OpenMates different?

Assistant messages:

```
Hey there!
Think of OpenMates as a better alternative to ChatGPT, Claude, Manus, etc. - that actually focuses on user interests and building the best possible product that YOU love to use on a daily base. That means: functionality, privacy, accessibility - all by design.

Functionality

Mates
When you message OpenMates, your request will be automatically forwarded to the best optimized digital team mate for the request. With optimized instructions & the best AI model for the task. And if you prefer, you can also further customize the processing by opening the settings menu (in the top right). You can also check these example chats via the chats menu (in the top left), to get a better idea of how OpenMates can help you with questions & brainstorming ideas:
“chat 1”
“chat 2”

Apps
OpenMates can not just answer questions and help you brainstorm ideas - but it can also fulfill various tasks, using Apps. From discussing the content & learnings of a YouTube video with the Videos apps, to researching 5 different topics at the same time to then get a faster & more reliable summary using the Web app, getting career advice via the Jobs app and much more. Check out these example chats:
“Fact check & analyze this video”
“Career advice”
“More example usecases”

And more...
Those features only scratch the surface. Our goal with OpenMates is to build the best digital team mates for everyone - for everyday personal life and for work. Check this chat out for more details:”Current OpenMates features”
“What comes next for OpenMates”

Software developer?
If you happen to be a software developer, OpenMates has some exciting features for you in the pipeline, which you can check out here:”OpenMates for developers”

Privacy
We believe that every software needs to be built with privacy as a key priority - so we designed our architecture around that principle. All your chats and sensitive data are encrypted in a way that only your devices can read them. And only the minimum amount of data that is needed for processing is send to our server.

Accessibility
There is already too much income & opportunity inequality in this world. But by designing OpenMates so its easy to use by everyone (without the need for deep technical experience) we can make the best learning tool ever and digital team mates that can fullfill tasks for you, accessible to the masses and be part of a shift towards more 

Any more questions? Check the docs or (after signing up) just ask me questions about OpenMates!

```