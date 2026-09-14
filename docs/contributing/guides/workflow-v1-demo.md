# Workflow v1 demos

The updated web builder saves each node explicitly. Save commits a new workflow version; Test uses unsaved skill inputs, and Send message Preview renders unsaved content without sending. Run now executes a complete saved graph even while its schedule is disabled.

Editable examples are in `examples/workflows/`:

- `morning-weather-news.yml`: daily 09:00, Weather → rain Check → News → one new chat.
- `weekly-ai-events.yml`: Sunday, events for the upcoming calendar Monday–Sunday → new chat.
- `hourly-apartments.yml`: hourly apartment search → new chat with only previously undelivered listings.

The examples use Berlin, Germany news and a €1,200/month apartment ceiling. Edit these inputs and the timezone as needed. Home provider selection and known skill costs are visible; bounded search results are not an exhaustive listing inventory. Provider warnings distinguish incomplete coverage from an empty successful search.

Create and test a disabled example using the existing signed-in CLI:

```sh
openmates workflows create --file examples/workflows/hourly-apartments.yml
openmates workflows run <workflow-id> --idempotency-key <unique-run-key> --wait
openmates workflows runs <workflow-id>
openmates workflows run-show <workflow-id> <run-id>
```

Reuse the same idempotency key only when retrying the same run. Enable the workflow after reviewing its schedule and costs. Normal chat encryption uses an authorized connected owner client; a pending delivery is not reported as an acknowledged chat write.

The SDKs expose the same controls:

```ts
await client.workflows.stepTest(id, stepId, { node, input, upstreamOutputs });
await client.workflows.previewStep(id, messageNodeId, { node, upstreamOutputs });
await client.workflows.deleteRun(id, runId);
```

```python
client.workflows.step_test(id, step_id, node=node, input_data=inputs, upstream_outputs=outputs)
client.workflows.preview_step(id, message_node_id, node=node, upstream_outputs=outputs)
client.workflows.delete_run(id, run_id)
```

For CLI draft inputs use `step-test` or `step-preview` with `--node '<json>'`, `--input '<json>'` and `--upstream '<json>'`. `run-delete <workflow-id> <run-id> --yes` removes the run and forgets its delivered-result membership; existing chat messages remain.

Only new results is per selected result list. New chats created by the same workflow and Send message node share delivery memory; explicitly different existing chats are distinct destinations. Pending accepted deliveries reserve their selected identities, successful acknowledgement remembers them, and failed/expired undelivered reservations release. Only visible retained runs own this memory. Payload-only expiry preserves membership, while deleting the sole remembering run makes its results eligible again. Old fetched example results do not seed this history.
