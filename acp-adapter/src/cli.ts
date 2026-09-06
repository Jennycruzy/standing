import { AcpJobError, StandingAcpAdapter } from "./adapter.js";
import { createOfficialRuntime, officialConfigFromEnv } from "./official.js";
import type { AcpJobRequest } from "./types.js";

type SuccessResponse = {
  ok: true;
  result: Awaited<ReturnType<StandingAcpAdapter["runJob"]>>;
};

type FailureResponse = {
  ok: false;
  error: {
    name: string;
    message: string;
    eventType?: string;
    entries?: unknown;
  };
};

async function main(): Promise<void> {
  try {
    const request = JSON.parse(await readStdin()) as AcpJobRequest;
    const runtime = await createOfficialRuntime(officialConfigFromEnv());
    const result = await new StandingAcpAdapter(runtime).runJob(request);
    writeResponse({ ok: true, result });
  } catch (error: unknown) {
    const response: FailureResponse = {
      ok: false,
      error: {
        name: error instanceof Error ? error.name : "Error",
        message: error instanceof Error ? error.message : "ACP adapter failed",
        ...(error instanceof AcpJobError ? { eventType: error.eventType, entries: error.entries } : {}),
      },
    };
    writeResponse(response);
    process.exitCode = 1;
  }
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk: string) => {
      input += chunk;
    });
    process.stdin.on("end", () => {
      if (input.trim() === "") {
        reject(new Error("ACP adapter requires one JSON request on stdin"));
        return;
      }
      resolve(input);
    });
    process.stdin.on("error", reject);
  });
}

function writeResponse(response: SuccessResponse | FailureResponse): void {
  process.stdout.write(`${JSON.stringify(response)}\n`);
}

void main();
