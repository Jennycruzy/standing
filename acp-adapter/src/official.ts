import {
  AcpAgent,
  AssetToken,
  PrivyAlchemyEvmProviderAdapter,
} from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";

import type { AcpRuntime } from "./types.js";

export type OfficialAcpConfig = {
  walletAddress: `0x${string}`;
  walletId: string;
  signerPrivateKey: string;
  builderCode?: string;
};

export async function createOfficialRuntime(config: OfficialAcpConfig): Promise<AcpRuntime> {
  const provider = await PrivyAlchemyEvmProviderAdapter.create({
    walletAddress: config.walletAddress,
    walletId: config.walletId,
    signerPrivateKey: config.signerPrivateKey,
    chains: [base],
    ...(config.builderCode === undefined ? {} : { builderCode: config.builderCode }),
  });

  return {
    createAgent: () => AcpAgent.create({ evmProvider: provider }),
    usdc: (amount, chainId) => AssetToken.usdc(amount, chainId),
  };
}

export function officialConfigFromEnv(env: NodeJS.ProcessEnv = process.env): OfficialAcpConfig {
  const walletAddress = requiredEnv(env, "STANDING_ACP_WALLET_ADDRESS");
  if (!/^0x[a-fA-F0-9]{40}$/.test(walletAddress)) {
    throw new TypeError("STANDING_ACP_WALLET_ADDRESS must be a 20-byte EVM address");
  }

  return {
    walletAddress: walletAddress as `0x${string}`,
    walletId: requiredEnv(env, "STANDING_ACP_WALLET_ID"),
    signerPrivateKey: requiredEnv(env, "STANDING_ACP_SIGNER_PRIVATE_KEY"),
    builderCode: optionalEnv(env, "STANDING_ACP_BUILDER_CODE"),
  };
}

function requiredEnv(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name];
  if (value === undefined || value.trim() === "") throw new Error(`missing ${name}`);
  return value;
}

function optionalEnv(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const value = env[name];
  return value === undefined || value.trim() === "" ? undefined : value;
}
