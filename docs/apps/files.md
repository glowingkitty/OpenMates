# Files app architecture

## Search skill

- can search in connected cloud storage accounts
- can search in connected servers (connected via OpenMates CLI), powered by ripgrep

???
Issue:
when we create a search embed and embed for all found files, this gets a lot very quickly...
Also, ripgrep doesnt output all files but only the lines of text it found in the files.

How to handle?
Possible solution:
Create FileSearchResult for every file, which can either contain the matches of text (plus metadata of file), or only file metadata (for search via dropbox or other cloud storages).
Fullscreen embed of FileSearchResult could offer a 'Load file' button to request the full file and turn the embed into a regular code/doc/sheet etc. embed. Or, we directly create those embeds, but with the text matches only instead of the full file by default.

In addition, ripgrep (rg) might result in hundreds or even thousand of lines of matches. But we usually only return the first 10 embeds. How do handle this here? No typical search result output with 10 embeds but a text based overview/summary of the search and matches count per file or even only folder? so when a match gives 621 files and 20k lines - we are still able to output useful infos from it?