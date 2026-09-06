import type {
  AcpAgent,
  AcpEntry,
  AcpEntryEvent,
  AcpEventType,
  AcpJobRequest,
  AcpJobResult,
  AcpRuntime,
  AcpSession,
} from "./types.js";

const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000;

export class AcpJobError extends Error {
  readonly entries: readonly AcpEntry[];
  readonly eventType?: AcpEventType;

  constructor(message: string, entries: readonly AcpEntry[], eventType?: AcpEventType) {
    super(message);
    this.name = "AcpJobError";
    this.entries = entries;
    this.eventType = eventType;
  }
}

export class StandingAcpAdapter {
  constructor(private readonly runtime: AcpRuntime) {}

  async runJob(request: AcpJobRequest): Promise<AcpJobResult> {
    validateRequest(request);

    const agent = await this.runtime.createAgent();
    const entries: AcpEntry[] = [];
    let createdJobId: string | undefined;
    let settled = false;
    let resolveCompletion: ((result: AcpJobResult) => void) | undefined;
    let rejectCompletion: ((error: Error) => void) | undefined;
    const completion = new Promise<AcpJobResult>((resolve, reject) => {
      resolveCompletion = resolve;
      rejectCompletion = reject;
    });

    let serial = Promise.resolve();
    const onEntry = (session: AcpSession, entry: AcpEntryEvent): void => {
      serial = serial.then(async () => {
        if (settled) return;
        const normalized = normalizeEntry(session, entry);
        entries.push(normalized);

        if (entry.kind !== "system") return;

        switch (entry.event.type) {
          case "budget.set":
            await session.fund(this.runtime.usdc(request.budgetUsdc, session.chainId));
            return;
          case "job.submitted":
            await session.complete(request.completionReason);
            return;
          case "job.completed":
            settled = true;
            resolveCompletion?.({
              jobId: String(session.jobId),
              status: "completed",
              entries: [...entries],
            });
            return;
          case "job.rejected":
          case "job.expired":
            settled = true;
            rejectCompletion?.(
              new AcpJobError(`ACP job ${entry.event.type}`, [...entries], entry.event.type),
            );
            return;
          case "job.created":
          case "job.funded":
            return;
        }
      }).catch((error: unknown) => {
        if (settled) return;
        settled = true;
        rejectCompletion?.(toError(error, "ACP event handling failed"));
      });
    };

    agent.on("entry", onEntry);

    try {
      await agent.start();
      const evaluatorAddress = await agent.getAddress();
      const jobId = await agent.createJobByOfferingName(
        request.chainId,
        request.offeringName,
        request.providerAddress,
        request.requirement,
        { evaluatorAddress },
      );
      createdJobId = String(jobId);

      const result = await withTimeout(completion, request.timeoutMs ?? DEFAULT_TIMEOUT_MS, () => {
        settled = true;
        return new AcpJobError(`ACP job ${createdJobId ?? "unknown"} timed out`, [...entries]);
      });
      await serial;
      return result;
    } catch (error: unknown) {
      throw toError(error, "ACP job failed");
    } finally {
      await agent.stop();
    }
  }
}

function validateRequest(request: AcpJobRequest): void {
  if (!Number.isSafeInteger(request.chainId) || request.chainId <= 0) {
    throw new TypeError("chainId must be a positive integer");
  }
  if (request.offeringName.trim() === "") {
    throw new TypeError("offeringName must not be empty");
  }
  if (!/^0x[a-fA-F0-9]{40}$/.test(request.providerAddress)) {
    throw new TypeError("providerAddress must be a 20-byte EVM address");
  }
  if (!Number.isFinite(request.budgetUsdc) || request.budgetUsdc <= 0) {
    throw new TypeError("budgetUsdc must be greater than zero");
  }
  if (request.completionReason.trim() === "") {
    throw new TypeError("completionReason must not be empty");
  }
  if (request.timeoutMs !== undefined && (!Number.isFinite(request.timeoutMs) || request.timeoutMs <= 0)) {
    throw new TypeError("timeoutMs must be greater than zero when provided");
  }
}

function normalizeEntry(session: AcpSession, entry: AcpEntryEvent): AcpEntry {
  if (entry.kind === "system") {
    return {
      kind: "system",
      eventType: entry.event.type,
      jobId: String(session.jobId),
      status: session.status,
    };
  }

  return {
    kind: "message",
    contentType: entry.contentType ?? "",
    content: entry.content ?? "",
  };
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, onTimeout: () => Error): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timeout = setTimeout(() => reject(onTimeout()), timeoutMs);
      }),
    ]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}

function toError(error: unknown, fallback: string): Error {
  return error instanceof Error ? error : new Error(fallback, { cause: error });
}
