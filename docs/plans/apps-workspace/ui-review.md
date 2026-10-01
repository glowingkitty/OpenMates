# Apps workspace Figma comparison and deployed repair

The prior component review did not prove the deployed route, real cross-origin skill loading or signed-in navigation. The user's screenshots exposed failures missed by that review. Completion is reopened.

Design references: [home 6019:61646](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=6019-61646), [app 6021:60395](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=6021-60395), [skill 6022:77555](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=6022-77555). All three cached exports were inspected again on 2026-10-01 before the repair.

The repair uses the existing AppStoreCard on the home, makes the app/skill hero decorative, anchors account controls to the full route, and follows the user-confirmed header order Chats, Apps, Projects, Tasks, Workflows. Public skill schemas must load through the real endpoint and leaving Apps must survive chat restoration, reload and browser history.

The user's 2026-10-01 corrections override the earlier bottom quick-use pill: Apps has no bottom composer or quick-use control. The skill hero is a plain icon without a rectangle, border or shadow, and app-card text and content are left aligned.

A deployed guest walkthrough reproduced the schema CORS failure: a credentialed request was rejected by the public endpoint's wildcard origin response. DOM geometry also placed the profile at y=63 below a 55px header because its absolute wrapper was anchored to the Apps body. Guest return to Chats worked; authenticated verification remains required.

Verification is pending: focused components, full-route regression tests, and a direct walkthrough of the published version at laptop and phone sizes. This report will record source-bound evidence and the inspected deployed screenshots before completion.

Reviewed source `240c1a50d0123d8d092d9dfb1d15695f4cccec84` component artifacts from run 36879833495: home, app and skill at 1180px and 390px. The inspected home has left-aligned AppStoreCard contents and no bottom control. The skill hero is a plain search glyph without border, background or shadow; app details retain the Figma app tile. Component interaction and layout assertions passed (7 cases, no skips or retries). Full-route and deployed verification remain pending.
