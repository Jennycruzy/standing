import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  AcpAgent,
  AssetToken,
  PrivyAlchemyEvmProviderAdapter,
} from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";
import { encodeAbiParameters, keccak256, stringToBytes } from "viem";
import type { Address, Hex } from "viem";

import { createOfficialProvider, officialConfigFromEnv } from "./official.js";
import {
  extractSource,
  assertFetchedSourceOrigin,
  parseExtractionPolicy,
  type ExtractedValueType,
  type ExtractionPolicy,
} from "./extraction.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000" as Address;
const ZERO_UID = `0x${"0".repeat(64)}` as Hex;
const ATTEST_SELECTOR = keccak256(
  stringToBytes("attest((bytes32,(address,uint64,bool,bytes32,bytes,uint256)))"),
).slice(0, 10);
const ATTESTED_TOPIC = keccak256(stringToBytes("Attested(address,address,bytes32,bytes32)"));

type JsonObject = Record<string, unknown>;
type ObservedValue = string | number | boolean | string[];

type ConditionSpec = {
  mode: "source_extract";
  source_url: string;
  note: string;
  disclosure: string;
  value_type: ExtractedValueType;
  extraction: ExtractionPolicy;
  controlled_scenario: boolean;
};

type Requirement = {
  conditionKey: string;
  sourceUrl: string;
  valueType: ConditionSpec["value_type"];
  unit: string;
  refUid?: Hex;
};

type ObserverProvenance = {
  operator_id: string;
  source_id: string;
  extractor_id: string;
  operator_type?: string;
};

type Delivery = {
  condition_key: string;
  value: ObservedValue;
  source_type: string;
  source_url: string;
  source_domain: string;
  observation_uid: Hex;
  observation_transaction: Hex;
  observer_address: Address;
  effective_from: number;
  observed_at: number;
  recorded_at: number;
  value_type: ExtractedValueType;
  unit: string;
  extraction_method: ExtractionPolicy["method"];
  extraction_version: string;
  evidence_hash: string;
  source_snapshot_hash: string;
  source_publication_date?: number;
  controlled_scenario: boolean;
  note: string;
  disclosure: string;
  provenance: ObserverProvenance;
  ref_uid: Hex;
};

type RuntimeConfig = {
  chainId: number;
  easAddress: Address;
  observationSchemaUid: Hex;
  sourceType: string;
  sourceTypeCode: number;
  budgetUsdc: number;
  observerProvenance: ObserverProvenance;
  conditions: Record<string, ConditionSpec>;
};

async function main(): Promise<void> {
  const config = loadRuntimeConfig();
  const provider = await createOfficialProvider(
    officialConfigFromEnv(process.env, "STANDING_ACP_SELLER_"),
  );
  const seller = await AcpAgent.create({ evmProvider: provider });
  const activeJobs = new Map<string, { conditionKey: string; spec: ConditionSpec; refUid?: Hex }>();
  const completed = new Promise<void>((resolveCompletion, rejectCompletion) => {
    let settled = false;
    const resolveOnce = (): void => {
      if (!settled) {
        settled = true;
        resolveCompletion();
      }
    };
    const rejectOnce = (error: unknown): void => {
      if (!settled) {
        settled = true;
        rejectCompletion(toError(error, "verifier worker failed"));
      }
    };

    seller.on("entry", (session, entry) => {
      process.stderr.write(
        `[standing-verifier] ${entry.kind === "system" ? entry.event.type : entry.contentType ?? "message"} ${session.jobId} ${session.status}\n`,
      );
      void handleEntry(provider, session, entry, config, activeJobs, resolveOnce, rejectOnce);
    });
  });

  await seller.start(() => {
    process.stdout.write(JSON.stringify({ ready: true }) + "\n");
  });
  try {
    await completed;
  } finally {
    await seller.stop();
  }
}

async function handleEntry(
  provider: PrivyAlchemyEvmProviderAdapter,
  session: Parameters<Parameters<AcpAgent["on"]>[1]>[0],
  entry: Parameters<Parameters<AcpAgent["on"]>[1]>[1],
  config: RuntimeConfig,
  activeJobs: Map<string, { conditionKey: string; spec: ConditionSpec; refUid?: Hex }>,
  resolveCompletion: () => void,
  rejectCompletion: (error: unknown) => void,
): Promise<void> {
  try {
    if (entry.kind === "message" && entry.contentType === "requirement" && session.status === "open") {
      const requirement = parseRequirement(entry.content);
      const spec = config.conditions[requirement.conditionKey];
      if (spec === undefined) return;
      if (!spec.note.includes(spec.disclosure)) {
        throw new Error("verifier disclosure is not present in the configured EAS note");
      }
      if (
        requirement.sourceUrl !== spec.source_url
        || requirement.valueType !== spec.value_type
        || requirement.unit !== spec.extraction.unit
      ) {
        throw new Error("ACP requirement does not match the configured verifier source");
      }
      activeJobs.set(session.jobId, {
        conditionKey: requirement.conditionKey,
        spec,
        refUid: requirement.refUid,
      });
      process.stderr.write(`[standing-verifier] setting budget ${session.jobId}\n`);
      await session.setBudget(AssetToken.usdc(config.budgetUsdc, session.chainId));
      process.stderr.write(`[standing-verifier] budget set ${session.jobId}\n`);
      return;
    }

    if (entry.kind === "system" && entry.event.type === "job.funded") {
      const job = activeJobs.get(session.jobId) ?? recoverActiveJob(session, config);
      if (job === undefined) return;
      activeJobs.set(session.jobId, job);
      process.stderr.write(`[standing-verifier] publishing observation ${session.jobId}\n`);
      const delivery = await publishObservation(provider, session.chainId, config, job);
      process.stderr.write(`[standing-verifier] observation published ${session.jobId}\n`);
      await session.sendMessage(JSON.stringify(delivery), "structured");
      await session.submit(JSON.stringify(delivery));
      return;
    }

    if (entry.kind === "system" && ["job.rejected", "job.expired"].includes(entry.event.type)) {
      if (activeJobs.has(session.jobId)) {
        rejectCompletion(new Error(`ACP verifier job ${entry.event.type}`));
      }
      return;
    }

    if (entry.kind === "system" && entry.event.type === "job.completed") {
      if (activeJobs.has(session.jobId)) {
        resolveCompletion();
      }
    }
  } catch (error: unknown) {
    console.error(`[standing-verifier] entry handler error: ${toError(error, "entry handler failed").message}`);
    rejectCompletion(error);
  }
}

function recoverActiveJob(
  session: Parameters<Parameters<AcpAgent["on"]>[1]>[0],
  config: RuntimeConfig,
): { conditionKey: string; spec: ConditionSpec; refUid?: Hex } | undefined {
  for (const entry of session.entries) {
    if (entry.kind !== "message" || entry.contentType !== "requirement") continue;
    const requirement = parseRequirement(entry.content);
    const spec = config.conditions[requirement.conditionKey];
    if (spec === undefined) continue;
    if (!spec.note.includes(spec.disclosure)) {
      throw new Error("verifier disclosure is not present in the configured EAS note");
    }
    if (
      requirement.sourceUrl !== spec.source_url
      || requirement.valueType !== spec.value_type
      || requirement.unit !== spec.extraction.unit
    ) {
      throw new Error("ACP requirement does not match the configured verifier source");
    }
    return {
      conditionKey: requirement.conditionKey,
      spec,
      refUid: requirement.refUid,
    };
  }
  return undefined;
}

async function publishObservation(
  provider: PrivyAlchemyEvmProviderAdapter,
  chainId: number,
  config: RuntimeConfig,
  job: { conditionKey: string; spec: ConditionSpec; refUid?: Hex },
): Promise<Delivery> {
  if (job.spec.mode !== "source_extract") {
    throw new Error("verifier condition mode is not supported");
  }
  const sourceResponse = await fetch(job.spec.source_url);
  if (!sourceResponse.ok) {
    throw new Error(`verifier source returned HTTP ${sourceResponse.status}`);
  }
  assertFetchedSourceOrigin(job.spec.source_url, sourceResponse.url);
  const sourceText = await sourceResponse.text();
  const extracted = extractSource(sourceText, job.spec.value_type, job.spec.extraction);
  if (extracted.unit === undefined || extracted.unit.trim() === "") {
    throw new Error("extraction.unit is required for a governed observation");
  }
  const observerAddress = await provider.getAddress();
  const observedAt = Math.floor(Date.now() / 1000);
  const effectiveFrom = extracted.effectiveFrom ?? observedAt;
  const note = `${job.spec.note} Extraction: ${extracted.method}/${extracted.version}; unit=${extracted.unit}; source_snapshot_sha256=${extracted.sourceSnapshotHash}.`;
  const encodedObservation = encodeAbiParameters(
    [
      { type: "string" },
      { type: "string" },
      { type: "uint64" },
      { type: "string" },
      { type: "uint8" },
      { type: "string" },
    ],
    [
      job.conditionKey,
      rawValue(extracted.value, job.spec.value_type),
      BigInt(effectiveFrom),
      job.spec.source_url,
      config.sourceTypeCode,
      note,
    ],
  );
  const requestData = encodeAbiParameters(
    [
      {
        type: "tuple",
        components: [
          { type: "bytes32" },
          {
            type: "tuple",
            components: [
              { type: "address" },
              { type: "uint64" },
              { type: "bool" },
              { type: "bytes32" },
              { type: "bytes" },
              { type: "uint256" },
            ],
          },
        ],
      },
    ],
    [
      [config.observationSchemaUid, [ZERO_ADDRESS, 0n, true, job.refUid ?? ZERO_UID, encodedObservation, 0n]],
    ],
  );
  const txHash = (await provider.sendTransaction(chainId, {
    to: config.easAddress,
    data: `${ATTEST_SELECTOR}${requestData.slice(2)}` as Hex,
    value: 0n,
  })) as Hex;
  const receipt = await provider.getTransactionReceipt(chainId, txHash);
  if (receipt.status !== "success") {
    throw new Error("EAS observation transaction did not succeed");
  }
  const observationUid = findAttestationUid(receipt.logs);
  return {
    condition_key: job.conditionKey,
    value: extracted.value,
    source_type: config.sourceType,
    source_url: job.spec.source_url,
    source_domain: new URL(job.spec.source_url).hostname.toLowerCase(),
    observation_uid: observationUid,
    observation_transaction: txHash,
    observer_address: observerAddress,
    effective_from: effectiveFrom,
    observed_at: observedAt,
    recorded_at: observedAt,
    value_type: job.spec.value_type,
    unit: extracted.unit,
    extraction_method: extracted.method,
    extraction_version: extracted.version,
    evidence_hash: extracted.sourceSnapshotHash,
    source_snapshot_hash: extracted.sourceSnapshotHash,
    source_publication_date: extracted.sourcePublicationDate,
    controlled_scenario: job.spec.controlled_scenario,
    ref_uid: job.refUid ?? ZERO_UID,
    note,
    disclosure: job.spec.disclosure,
    provenance: config.observerProvenance,
  };
}

function loadRuntimeConfig(): RuntimeConfig {
  const chain = readJson(resolve(ROOT, "config/chain.json"));
  const eas = readJson(resolve(ROOT, "config/eas.json"));
  const acp = readJson(resolve(ROOT, "config/acp.json"));
  const verifier = readJson(resolve(ROOT, "config/verifier.json"));
  const base = objectValue(chain.base, "chain.base");
  const acpSection = objectValue(acp.acp, "acp");
  const registrations = objectValue(eas.registrations, "eas.registrations");
  const observationRegistration = objectValue(
    registrations.observation,
    "eas.registrations.observation",
  );
  const sourceTypes = objectValue(eas.source_types, "eas.source_types");
  const conditionObjects = objectValue(verifier.conditions, "verifier.conditions");
  const conditions: Record<string, ConditionSpec> = {};
  for (const [conditionKey, value] of Object.entries(conditionObjects)) {
    const spec = objectValue(value, `verifier condition ${conditionKey}`);
    const mode = requiredString(spec.mode, `verifier condition ${conditionKey}.mode`);
    if (mode !== "source_extract") throw new Error("verifier conditions must use source_extract mode");
    const valueType = requiredString(spec.value_type, `verifier condition ${conditionKey}.value_type`);
    if (!["number", "boolean", "date", "set"].includes(valueType)) {
      throw new Error(`verifier condition ${conditionKey}.value_type is not supported`);
    }
    const controlledScenario = spec.controlled_scenario;
    if (typeof controlledScenario !== "boolean") {
      throw new Error(`verifier condition ${conditionKey}.controlled_scenario must be true or false`);
    }
    conditions[conditionKey] = {
      mode: "source_extract",
      source_url: requiredString(spec.source_url, `verifier condition ${conditionKey}.source_url`),
      note: requiredString(spec.note, `verifier condition ${conditionKey}.note`),
      disclosure: requiredString(spec.disclosure, `verifier condition ${conditionKey}.disclosure`),
      value_type: valueType as ExtractedValueType,
      extraction: parseExtractionPolicy(spec.extraction),
      controlled_scenario: controlledScenario,
    };
  }
  const sourceType = requiredString(acpSection.source_type, "acp.source_type");
  const provenanceRaw = objectValue(acpSection.observer_provenance, "acp.observer_provenance");
  const observerProvenance: ObserverProvenance = {
    operator_id: requiredString(provenanceRaw.operator_id, "acp.observer_provenance.operator_id"),
    source_id: requiredString(provenanceRaw.source_id, "acp.observer_provenance.source_id"),
    extractor_id: requiredString(provenanceRaw.extractor_id, "acp.observer_provenance.extractor_id"),
  };
  if (provenanceRaw.operator_type !== undefined) {
    observerProvenance.operator_type = requiredString(
      provenanceRaw.operator_type,
      "acp.observer_provenance.operator_type",
    );
  }
  const sourceTypeCode = Object.entries(sourceTypes).find(([, value]) => value === sourceType)?.[0];
  if (sourceTypeCode === undefined || !/^\d+$/.test(sourceTypeCode)) {
    throw new Error(`source type ${sourceType} is not configured`);
  }
  const chainId = positiveInt(base.chainId, "base.chainId");
  if (chainId !== base.id && base.id !== undefined) {
    throw new Error("configured Base chain ID is inconsistent");
  }
  return {
    chainId,
    easAddress: address(base.eas, "base.eas"),
    observationSchemaUid: uid(observationRegistration.uid, "observation schema UID"),
    sourceType,
    sourceTypeCode: Number(sourceTypeCode),
    budgetUsdc: positiveNumber(acpSection.budget_usdc, "acp.budget_usdc"),
    observerProvenance,
    conditions,
  };
}

function parseRequirement(content: string): Requirement {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch (error) {
    throw new Error("ACP requirement was not JSON", { cause: error });
  }
  if (!isObject(parsed)) throw new Error("ACP requirement was not an object");
  const valueType = requiredString(parsed.valueType, "requirement.valueType");
  if (!["number", "boolean", "date", "set"].includes(valueType)) {
    throw new Error("requirement.valueType is not supported");
  }
  const rawRefUid = parsed.refUid;
  const refUid = rawRefUid === undefined ? undefined : uid(rawRefUid, "requirement.refUid");
  return {
    conditionKey: requiredString(parsed.conditionKey, "requirement.conditionKey"),
    sourceUrl: requiredString(parsed.sourceUrl, "requirement.sourceUrl"),
    valueType: valueType as ConditionSpec["value_type"],
    unit: requiredString(parsed.unit, "requirement.unit"),
    refUid,
  };
}

function findAttestationUid(logs: readonly { topics: readonly Hex[]; data: Hex }[]): Hex {
  for (const log of logs) {
    if (log.topics[0]?.toLowerCase() !== ATTESTED_TOPIC.toLowerCase()) continue;
    if (!log.data.startsWith("0x") || log.data.length < 66) continue;
    return `0x${log.data.slice(2, 66)}` as Hex;
  }
  throw new Error("EAS Attested event was not found");
}

function rawValue(value: ObservedValue, valueType: ConditionSpec["value_type"]): string {
  const parsed = parsedValue(value, valueType);
  return Array.isArray(parsed) ? JSON.stringify(parsed) : String(parsed);
}

function parsedValue(
  value: ObservedValue,
  valueType: ConditionSpec["value_type"],
): ObservedValue {
  if (valueType === "number") {
    const parsed = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(parsed)) throw new Error("extracted verifier value is not numeric");
    return parsed;
  }
  if (valueType === "boolean") {
    if (typeof value === "boolean") return value;
    if (value === "true") return true;
    if (value === "false") return false;
    throw new Error("extracted verifier value is not boolean");
  }
  if (valueType === "set") {
    if (Array.isArray(value)) return value;
    throw new Error("extracted verifier set value must be an array");
  }
  return String(value);
}

function readJson(path: string): JsonObject {
  const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!isObject(parsed)) throw new Error(`${path} must contain an object`);
  return parsed;
}

function objectValue(value: unknown, label: string): JsonObject {
  if (!isObject(value)) throw new Error(`${label} must be an object`);
  return value;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a non-empty string`);
  return value.trim();
}

function address(value: unknown, label: string): Address {
  const result = requiredString(value, label);
  if (!/^0x[a-fA-F0-9]{40}$/.test(result)) throw new Error(`${label} must be an address`);
  return result as Address;
}

function uid(value: unknown, label: string): Hex {
  const result = requiredString(value, label);
  if (!/^0x[a-fA-F0-9]{64}$/.test(result)) throw new Error(`${label} must be bytes32`);
  return result as Hex;
}

function positiveInt(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) throw new Error(`${label} must be a positive integer`);
  return value as number;
}

function positiveNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) throw new Error(`${label} must be positive`);
  return value;
}

function toError(error: unknown, fallback: string): Error {
  return error instanceof Error ? error : new Error(fallback, { cause: error });
}

void main().catch((error: unknown) => {
  console.error(`ERROR: ${toError(error, "verifier worker failed").message}`);
  process.exitCode = 1;
});
