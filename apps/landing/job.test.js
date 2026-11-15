import assert from "node:assert/strict";
import test from "node:test";
import { advanceJob, initialJob, stages } from "./job.js";

const run = (...actions) => actions.reduce(advanceJob, initialJob);

test("a result requires a request and explicit approval", () => {
  assert.equal(run("finish", "approve", "finish"), initialJob);
  assert.equal(run("request", "finish").stage, "review");
  const job = run("request", "approve", "finish");
  assert.equal(job.stage, "done");
  assert.match(stages[job.stage].copy, /Unit tests passed in Build A and failed in Build B/);
  assert.deepEqual(job.events, ["Sandbox ready", "Request received. Scope ready for review.", "Approved. Read-only comparison started.", "Comparison complete. Receipt recorded."]);
});

test("stop and decline are final and reset clears the receipt", () => {
  const stopped = run("request", "approve", "stop", "finish");
  assert.equal(stopped.stage, "stopped");
  const declined = run("request", "decline", "approve", "finish");
  assert.equal(declined.stage, "declined");
  assert.equal(declined.events.length, 3);
  assert.equal(advanceJob(stopped, "reset"), initialJob);
});
