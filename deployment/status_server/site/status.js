// status.openmates.org: renders /data/status.json (written by the status agent
// every minute) and refreshes it every 60 seconds. No external requests.
"use strict";

const LABELS = {
  operational: "Operational",
  degraded: "Partial outage",
  outage: "Major outage",
  unknown: "No data yet",
};
const OVERALL = {
  operational: "All systems operational",
  degraded: "Some systems are not working",
  outage: "Major outage",
  unknown: "Status unknown",
};

function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text) node.textContent = text;
  return node;
}

function formatTime(seconds) {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    dateStyle: "medium", timeStyle: "short",
  });
}

function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function barLevel(uptime) {
  if (uptime === null) return "none";
  if (uptime >= 99.5) return "ok";
  if (uptime >= 95) return "minor";
  return "major";
}

function renderComponents(components) {
  const list = document.getElementById("components");
  const template = document.getElementById("component-row");
  list.replaceChildren();
  for (const component of components) {
    const row = template.content.firstElementChild.cloneNode(true);
    row.dataset.testid = `status-component-${component.id}`;
    row.querySelector(".name").textContent = component.name;
    row.querySelector(".name").title = component.description;
    const state = row.querySelector(".state");
    state.textContent = LABELS[component.status] || LABELS.unknown;
    state.dataset.status = component.status;
    const bars = row.querySelector(".bars");
    bars.setAttribute("aria-label", `${component.name}: daily uptime for the past 90 days`);
    for (const day of component.days) {
      const text = day.uptime === null ? "no data" : `${day.uptime}% uptime`;
      bars.append(el("span", { class: "bar", "data-level": barLevel(day.uptime), title: `${day.day}: ${text}` }));
    }
    row.querySelector(".uptime").textContent =
      component.uptime_percent === null ? "" : `${component.uptime_percent}% uptime`;
    list.append(row);
  }
}

function renderProviders(providers) {
  const list = document.getElementById("providers");
  list.replaceChildren();
  for (const provider of providers) {
    const item = el("li", { class: "provider", "data-testid": `status-provider-${provider.id}` });
    item.append(el("span", { class: "dot", "data-status": provider.status, title: LABELS[provider.status] || "" }));
    const text = el("div");
    text.append(el("a", { href: provider.status_page, rel: "noopener", target: "_blank" }, provider.name));
    text.append(el("small", {}, `${provider.category} · ${LABELS[provider.status] || LABELS.unknown}`));
    item.append(text);
    list.append(item);
  }
}

function renderIncidents(incidents) {
  const list = document.getElementById("incidents");
  list.replaceChildren();
  if (!incidents.length) {
    list.append(el("li", { class: "empty muted" }, "No incidents in the past 90 days."));
    return;
  }
  for (const incident of incidents) {
    const item = el("li", { class: "incident" });
    item.append(el("h3", {}, incident.title));
    const line = el("p", { class: "muted" });
    if (incident.resolved_at === null) {
      line.append(el("span", { class: "open" }, "Ongoing"), ` · started ${formatTime(incident.started_at)}`);
    } else {
      line.textContent = `${formatTime(incident.started_at)} · resolved after ${formatDuration(incident.resolved_at - incident.started_at)}`;
    }
    item.append(line);
    list.append(item);
  }
}

async function refresh() {
  const overall = document.getElementById("overall");
  try {
    const response = await fetch("/data/status.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const stale = Date.now() / 1000 - data.generated_at > 10 * 60;
    const status = stale ? "unknown" : data.overall;
    overall.dataset.status = status;
    document.getElementById("overall-text").textContent = OVERALL[status] || OVERALL.unknown;
    document.getElementById("updated").textContent = stale
      ? `The checker has not reported since ${formatTime(data.generated_at)}.`
      : `Last checked ${formatTime(data.generated_at)}`;
    renderComponents(data.components);
    renderProviders(data.providers);
    renderIncidents(data.incidents);
  } catch (error) {
    overall.dataset.status = "unknown";
    document.getElementById("overall-text").textContent = OVERALL.unknown;
    document.getElementById("updated").textContent = "The status data could not be loaded. Retrying every minute.";
  }
}

refresh();
setInterval(refresh, 60_000);
