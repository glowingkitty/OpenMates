/*
Purpose: API client helpers for status service endpoints.
Architecture: Reads status data from backend/status FastAPI JSON routes.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
*/

async function request(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export function fetchStatus(environment) {
  return request(`/api/status?env=${environment}`);
}

export function fetchHistory(environment) {
  return request(
    `/api/status/history?env=${environment}&since_days=30&limit=100`,
  );
}

export function fetchUptime(environment) {
  return request(`/api/status/uptime?env=${environment}`);
}

export function fetchResponseTimes(environment, serviceId, period) {
  return request(
    `/api/status/response-times?env=${environment}&service_id=${encodeURIComponent(serviceId)}&period=${period}`,
  );
}
