import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          CURRENT_RELEASE: "JPPM2099001",
          RELEASE_CATALOG_JSON:
            '{"JPPM2099001":{"ipc_edition":"8U"},"JPPM2098001":{"ipc_edition":"8B"}}',
        },
      },
    }),
  ],
  test: {
    include: ["test/worker.spec.ts"],
  },
});
