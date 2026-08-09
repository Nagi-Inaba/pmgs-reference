import { exports } from "cloudflare:workers";
import { expect, it } from "vitest";

import { seedLargeLookupFixture } from "./fixtures";

const ORIGIN = "https://pmgs.example.test";
const RECORD_COUNTS = [128, 185, 256, 512, 1_024, 2_048] as const;
const RUNS = 9;

function percentile(values: number[], fraction: number): number {
  const sorted = values.toSorted((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1);
  return sorted[index] ?? Number.NaN;
}

async function lookupLastRecord(recordCount: number): Promise<number> {
  const code = `A01B1/${String(recordCount - 1).padStart(4, "0")}`;
  const started = performance.now();
  const response = await exports.default.fetch(
    new Request(`${ORIGIN}/api/v1/lookup?scheme=fi&code=${encodeURIComponent(code)}`),
  );
  const payload: unknown = await response.json();
  expect(response.status).toBe(200);
  expect(response.headers.get("Server-Timing")).toBe('pmgs-r2;desc="2 reads"');
  expect(payload).toMatchObject({ normalized_code: code });
  return performance.now() - started;
}

it("records reproducible local workerd lookup timing by serialized chunk size", async () => {
  for (const recordCount of RECORD_COUNTS) {
    const bytes = await seedLargeLookupFixture(recordCount);
    await lookupLastRecord(recordCount);
    const durations: number[] = [];
    for (let index = 0; index < RUNS; index += 1) {
      durations.push(await lookupLastRecord(recordCount));
    }
    console.log(
      JSON.stringify({
        event: "pmgs_chunk_benchmark",
        records: recordCount,
        bytes,
        runs: RUNS,
        median_ms: Number(percentile(durations, 0.5).toFixed(3)),
        p95_ms: Number(percentile(durations, 0.95).toFixed(3)),
        r2_reads: 2,
        measurement: "local_workerd_end_to_end_wall_clock",
      }),
    );
  }
});
