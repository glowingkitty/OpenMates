# Rules for files inside .context folder

Always make sure to follow these rules when writing / updating the files inside the .context folder.

## Markdown files

### Structure
1. heading: similar to filename (example: coding-guidelines.md -> Coding Guidelines)
2. table of content
3. chapters with text


## File specific rules

### todo.md

#### Structure
1. chapter 'Milestones' with table
   1. table has these fields:
      1. ID (M1, M2, etc.)
      2. Title (required)
      3. Target Date (YYYY-MM-DD)
      4. Tasks (T1, T2, etc.)
      5. Status (todo, in-progress, done)
2. chapter 'Milestone Descriptions' with sub chapters for each milestone
   1. content:
      1. headline: {ID} - {Title}
      2. text: {description}
3. chapter 'Tasks' with table
   1. table has these fields:
      1. ID (T1, T2, etc.)
      2. Title
      3. Priority (-, Low, Medium, High)
      4. Status (todo, in-progress, done)
      5. Depends on (- or T1, T2, etc.)
      6. Milestone (-, or M1, M2, etc.)
      7. Tags
4. chapter 'Task Descriptions' with sub chapters for each task
   1. content:
      1. headline: {ID} - {Title}
      2. text: {description}