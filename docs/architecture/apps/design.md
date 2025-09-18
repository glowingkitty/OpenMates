# Design app architecture

> Idea stage

# Skills

## Export artboard

Use the Figma or Penpot api to export an artboard as images, code, SVG.

## Connect

Uses browserbase, Stagehand and e2b to login to a Figma or Penpot web app as the user, open the requested artboard, then load our custom plugin and login to the user OpenMates account. Once done, the session is ready to receive commands to modify or create new artboards via the plugin and new files via browserbase / stagehand, while allowing the user to take over at any time (optional, since realistically it would he better to just open the actual figma webapp on the user device then).

## Edit

Use a connected session and modify existing artboards or create new artboards.
