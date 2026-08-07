/* Contract tests for the internal sub-chat orchestration boundary. */
import assert from 'node:assert/strict';
import test from 'node:test';

import { isAuthorized } from '../src/index.js';
import {
  executeOperation,
  SubChatOrchestrationError,
  testing,
} from '../src/operations.js';

const CHILD_ID = '11111111-1111-4111-8111-111111111111';

test('internal endpoint authentication fails closed', () => {
  assert.equal(isAuthorized({}, 'secret'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'secret' }, ''), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'wrong' }, 'secret'), false);
  assert.equal(isAuthorized({ 'x-internal-service-token': 'secret' }, 'secret'), true);
});

test('child preparation rejects content-bearing fields', () => {
  assert.throws(
    () => testing.validatedChildren([{
      child_chat_id: CHILD_ID,
      user_message_id: 'message-1',
      dispatch_token: 'dispatch-token',
      prompt: 'private prompt',
    }]),
    (error) => error instanceof SubChatOrchestrationError
      && error.code === 'private_child_field_forbidden',
  );
});

test('child preparation accepts identifiers and hashes dispatch tokens', () => {
  const [child] = testing.validatedChildren([{
    child_chat_id: CHILD_ID,
    user_message_id: 'message-1',
    dispatch_token: 'dispatch-token',
    budget_limit: 500,
  }]);

  assert.equal(child.child_chat_id, CHILD_ID);
  assert.equal(testing.tokenHash(child.dispatch_token).length, 64);
});

test('protocol version and operation allow-list fail closed', async () => {
  await assert.rejects(
    executeOperation({}, 'missing', { protocol_version: 1 }),
    (error) => error instanceof SubChatOrchestrationError
      && error.code === 'unsupported_operation',
  );
  await assert.rejects(
    executeOperation({ raw: async () => ({}) }, 'health_check', { protocol_version: 2 }),
    (error) => error instanceof SubChatOrchestrationError
      && error.code === 'client_update_required',
  );
});

test('operation reservations include spent and concurrent reserved credits', () => {
  const root = { spent_credits: 600, reserved_credits: 900, credit_limit: 2_000 };

  assert.equal(testing.operationReservationFits(root, 500), true);
  assert.equal(testing.operationReservationFits(root, 501), false);
});
