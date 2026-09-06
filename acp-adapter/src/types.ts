import type { Address } from "viem";

export const ACP_EVENT_TYPES = [
  "job.created",
  "budget.set",
  "job.funded",
  "job.submitted",
  "job.completed",
  "job.rejected",
  "job.expired",
] as const;

export type AcpEventType = (typeof ACP_EVENT_TYPES)[number];

export type AcpJobRequest = {
  chainId: number;
  /** Resume an already-created job instead of creating a new one. */
  jobId?: string;
  offeringName: string;
  providerAddress: Address;
  requirement: Record<string, unknown>;
  budgetUsdc: number;
  completionReason: string;
  timeoutMs?: number;
};

export type AcpSystemEntry = {
  kind: "system";
  eventType: AcpEventType;
  jobId: string;
  status: string;
};

export type AcpMessageEntry = {
  kind: "message";
  contentType: string;
  content: string;
};

export type AcpEntry = AcpSystemEntry | AcpMessageEntry;

export type AcpJobResult = {
  jobId: string;
  status: "completed";
  entries: readonly AcpEntry[];
};

export type AcpSession = {
  readonly jobId: string | number | bigint;
  readonly chainId: number;
  readonly status: string;
  fund(assetToken: unknown): Promise<unknown>;
  complete(reason: string): Promise<unknown>;
};

export type AcpEntryEvent =
  | {
      kind: "system";
      event: { type: AcpEventType };
    }
  | {
      kind: "message";
      contentType?: string;
      content?: string;
    };

export type AcpEntryListener = (session: AcpSession, entry: AcpEntryEvent) => void | Promise<void>;

export type AcpAgent = {
  on(event: "entry", listener: AcpEntryListener): unknown;
  start(): Promise<unknown>;
  stop(): Promise<unknown>;
  getSession(chainId: number, jobId: string): AcpSession | undefined;
  getAddress(): Promise<string>;
  createJobByOfferingName(
    chainId: number,
    offeringName: string,
    providerAddress: Address,
    requirement: Record<string, unknown>,
    options: { evaluatorAddress: string },
  ): Promise<string | number | bigint>;
};

export type AcpRuntime = {
  createAgent(): Promise<AcpAgent>;
  usdc(amount: number, chainId: number): unknown;
};
