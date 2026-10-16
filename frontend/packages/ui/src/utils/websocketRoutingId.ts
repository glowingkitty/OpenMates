import { v4 as uuidv4 } from 'uuid';

// A document owns one routing identity across reconnects. sessionStorage is
// intentionally unsuitable here: an opener-created tab can inherit its value.
const websocketRoutingId = uuidv4();

export function getWebSocketRoutingId(): string {
  return websocketRoutingId;
}
