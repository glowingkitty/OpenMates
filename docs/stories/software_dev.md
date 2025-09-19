# Software development user stories

> Work in progress

This is a collection of user stories, how OpenMates should be optimized to deal with them and the conclusions / features based on the stories.

## Update code base to Svelte 5

After updating the pnpm packages of a complex project to svelte 5, the compiler shows errors and warnings when starting the software.
Ideal solution: User asks "Fix the errors and warnings that appear when the svelte dev server starts up and the web app is loaded - and restart the server and fix the issues as long as needed until all errors and warnings have disappeared." - or even better, until all frontend unit tests succeed. That task will then run until its completed. Question: how to 