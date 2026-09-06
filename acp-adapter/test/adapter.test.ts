import assert from "node:assert/strict";
import test from "node:test";

import { AcpJobError, StandingAcpAdapter } from "../src/adapter.js";
import type { AcpAgent, AcpEntryListener, AcpRuntime, AcpSession } from "../src/types.js";

class FakeAgent implements AcpAgent {
  listener?: AcpEntryListener;
  started = false;
  stopped = false;
  addressLookups = 0;
  creations = 0;
  fundedWith: unknown[] = [];
  completedWith: string[] = [];
  resumedSession?: AcpSession;

  on(_event: "entry", listener: AcpEntryListener): void {
    this.listener = listener;
  }

  async start(): Promise<void> {
    this.started = true;
  }

  async stop(): Promise<void> {
    this.stopped = true;
  }

  async getAddress(): Promise<string> {
    this.addressLookups += 1;
    return "0x1111111111111111111111111111111111111111";
  }

  async createJobByOfferingName(): Promise<string> {
    this.creations += 1;
    return "76580";
  }

  getSession(_chainId: number, _jobId: string): AcpSession | undefined {
    return this.resumedSession;
  }

  async emit(session: AcpSession, entry: Parameters<AcpEntryListener>[1]): Promise<void> {
    await this.listener?.(session, entry);
  }
}

function fakeRuntime(agent: FakeAgent): AcpRuntime {
  return {
    createAgent: async () => agent,
    usdc: (amount, chainId) => ({ amount, chainId, symbol: "USDC" }),
  };
}

function fakeSession(agent: FakeAgent): AcpSession {
  return {
    jobId: "76580",
    chainId: 8453,
    status: "open",
    fund: async (token) => agent.fundedWith.push(token),
    complete: async (reason) => agent.completedWith.push(reason),
  };
}

const request = {
  chainId: 8453,
  offeringName: "published_condition_check",
  providerAddress: "0x2222222222222222222222222222222222222222" as `0x${string}`,
  requirement: { key: "standing-preflight" },
  budgetUsdc: 0.01,
  completionReason: "preflight lifecycle accepted",
  timeoutMs: 1000,
};

test("completes the typed ACP lifecycle and returns the event history", async () => {
  const agent = new FakeAgent();
  const session = fakeSession(agent);
  const adapter = new StandingAcpAdapter(fakeRuntime(agent));

  const resultPromise = adapter.runJob(request);
  await new Promise((resolve) => setImmediate(resolve));
  await agent.emit(session, { kind: "system", event: { type: "job.created" } });
  await agent.emit(session, { kind: "system", event: { type: "budget.set" } });
  await agent.emit(session, { kind: "system", event: { type: "job.funded" } });
  await agent.emit(session, { kind: "system", event: { type: "job.submitted" } });
  await agent.emit(session, { kind: "system", event: { type: "job.completed" } });

  const result = await resultPromise;
  assert.equal(result.jobId, "76580");
  assert.equal(result.status, "completed");
  assert.deepEqual(agent.fundedWith, [{ amount: 0.01, chainId: 8453, symbol: "USDC" }]);
  assert.deepEqual(agent.completedWith, ["preflight lifecycle accepted"]);
  assert.deepEqual(result.entries.map((entry) => entry.kind === "system" && entry.eventType), [
    "job.created",
    "budget.set",
    "job.funded",
    "job.submitted",
    "job.completed",
  ]);
  assert.equal(agent.started, true);
  assert.equal(agent.stopped, true);
});

test("surfaces ACP rejection instead of returning success", async () => {
  const agent = new FakeAgent();
  const adapter = new StandingAcpAdapter(fakeRuntime(agent));
  const resultPromise = adapter.runJob(request);
  await new Promise((resolve) => setImmediate(resolve));
  await agent.emit(fakeSession(agent), { kind: "system", event: { type: "job.rejected" } });

  await assert.rejects(resultPromise, (error: unknown) => {
    assert.ok(error instanceof AcpJobError);
    assert.equal(error.eventType, "job.rejected");
    return true;
  });
  assert.equal(agent.stopped, true);
});

test("resumes a hydrated job without creating another job", async () => {
  const agent = new FakeAgent();
  const session = fakeSession(agent);
  agent.resumedSession = session;
  const adapter = new StandingAcpAdapter(fakeRuntime(agent));
  const resultPromise = adapter.runJob({ ...request, jobId: "76580" });

  await new Promise((resolve) => setImmediate(resolve));
  await agent.emit(session, { kind: "system", event: { type: "job.completed" } });

  const result = await resultPromise;
  assert.equal(result.jobId, "76580");
  assert.equal(agent.addressLookups, 0);
  assert.equal(agent.creations, 0);
  assert.equal(agent.stopped, true);
});

test("rejects unsafe job configuration before creating an agent", async () => {
  let created = false;
  const runtime: AcpRuntime = {
    createAgent: async () => {
      created = true;
      return new FakeAgent();
    },
    usdc: () => undefined,
  };
  const adapter = new StandingAcpAdapter(runtime);

  await assert.rejects(
    adapter.runJob({ ...request, budgetUsdc: 0 }),
    /budgetUsdc must be greater than zero/,
  );
  assert.equal(created, false);
});
