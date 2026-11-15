const fixtures = [
  new Map([["Format", true], ["Unit tests", true], ["Bundle budget", true]]),
  new Map([["Format", true], ["Unit tests", false], ["Bundle budget", true]]),
];

const newFailures = [...fixtures[1]]
  .filter(([check, passed]) => !passed && fixtures[0].get(check) === true)
  .map(([check]) => check);

export const stages = {
  ready: {
    step: "ready", label: "01 / Request", title: "“Compare the two build reports.”",
    copy: "Use the sample request to see what the assistant would need before it can act.",
    primary: ["request", "Send sample request"], event: "Sandbox ready",
  },
  review: {
    step: "review", label: "02 / Review scope", title: "Read two example reports?",
    copy: "Read only: Build A and Build B. The job can’t edit files or run commands.",
    primary: ["approve", "Approve sample job"], secondary: ["decline", "Decline"],
    event: "Request received. Scope ready for review.",
  },
  running: {
    step: "running", label: "03 / Run", title: "Comparing Build A and Build B.",
    copy: "Advance the simulation to see the result, or stop it now to see a cancellation receipt.",
    primary: ["finish", "Show result"], secondary: ["stop", "Stop sample job"],
    event: "Approved. Read-only comparison started.",
  },
  done: {
    step: "done", label: "04 / Completed", title: "One new failure found.",
    copy: `${newFailures.join(", ")} passed in Build A and failed in Build B. Two example reports read. No changes made.`,
    primary: ["reset", "Reset simulation"], event: "Comparison complete. Receipt recorded.",
  },
  stopped: {
    step: "done", label: "04 / Stopped", title: "Job stopped on request.",
    copy: "The simulated run ended before it produced a result. The receipt keeps the stop in the record.",
    primary: ["reset", "Reset simulation"], event: "Stop recorded. No result produced.",
  },
  declined: {
    step: "done", label: "04 / Declined", title: "The job never started.",
    copy: "You declined the proposed scope. No example reports were read.",
    primary: ["reset", "Reset simulation"], event: "Declined. No files opened.",
  },
};

const next = {
  request: "review", approve: "running", decline: "declined",
  finish: "done", stop: "stopped", reset: "ready",
};

export const initialJob = { stage: "ready", events: [stages.ready.event] };

export function advanceJob(job, action) {
  const stage = stages[job.stage];
  if (action !== stage.primary[0] && action !== stage.secondary?.[0]) return job;
  if (action === "reset") return initialJob;
  const destination = next[action];
  return { stage: destination, events: [...job.events, stages[destination].event] };
}
