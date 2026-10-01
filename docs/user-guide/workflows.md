# Workflows

Workflows automate repeatable tasks in OpenMates. Each Workflow combines a trigger with one or more actions and is shown with an automatically assigned category and icon.

## Create A Workflow

1. Open **Workflows** from the workspace sidebar.
2. Enter a title in the composer at the bottom of the start screen.
3. Submit the title to create a disabled draft.

The new draft opens in the **Template** tab. OpenMates assigns its category and icon from the Workflow graph when possible. These identity fields are encrypted with the rest of the Workflow metadata.

Use **Show my workflows** to browse all your Workflows. The grid starts with the most recently created or updated Workflow. Change **Last updated** to **Running next first** to put enabled Workflows with upcoming runs first.

**Continue where you left off** prioritizes Workflows created or updated in the last 30 minutes, then Workflows running in the next 30 minutes, those created or updated in the last 24 hours, those running in the next 24 hours, and finally older Workflows by their latest creation or update time. Paused Workflows do not count as upcoming runs.

Open **Show templates** for built-in examples. Selecting a template creates a disabled copy and opens it for review; it does not run or activate the schedule. Templates stay separate from your continuation cards until you create your own copy.

## Edit The Template

The Template graph shows the trigger, actions, branches, and end step in execution order.

1. Select a node to expand it in place.
2. Change the available fields or add and remove nodes.
3. Select **Save** to create a new immutable definition version, or **Undo** to discard the current local edits.

Changes remain local until you save them. If you try to open Runs, another Workflow, a historical version, or the workspace while changes are unsaved, choose one of these options:

- **Save** saves the changes and continues.
- **Discard** removes the local changes and continues.
- **Stay** returns to the current Template without losing the edits.

## Inspect Versions

The version selector and horizontal timeline list the immutable definitions of a Workflow. The current definition is marked **Active**.

Select an older timestamp to inspect its complete graph in read-only mode. Restoring a historical definition creates a new current version after confirmation; it never changes or deletes the original history.

## Inspect Runs

Select the **Runs** tab to inspect upcoming and persisted executions. The timeline distinguishes the next scheduled occurrence and completed, failed, active, waiting, and cancelled runs.

Select a run to see the Workflow version used for that execution and the status of each node. Expanded nodes show retained inputs, outputs, sources, branches, and errors when available. If retained content has expired, OpenMates keeps the run and node statuses visible and marks the content unavailable instead of reconstructing it.

Runs can be cancelled only while their current state supports cancellation. OpenMates asks for confirmation before requesting cancellation.

A **Send message** step stays pending until the encrypted chat message is persisted and delivery is acknowledged. When the message is ready, an in-app chat notification lets you open it; the acknowledged step also offers **Open chat**. If you are already viewing that chat, OpenMates avoids an extra notification.

## Privacy

Workflow titles, descriptions, category and icon identity, definitions, and retained run content follow the Workflow encryption and owner or team access boundary. Existing authorized REST, CLI, and SDK clients receive the same decrypted category and icon; stored Directus records do not contain plaintext identity metadata.
