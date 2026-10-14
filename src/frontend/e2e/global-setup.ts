import type { FullConfig } from "@playwright/test";

const required = [
  "E2E_BASE_URL",
  "E2E_REVIEWER_TENANT",
  "E2E_REVIEWER_USERNAME",
  "E2E_REVIEWER_PASSWORD",
  "E2E_AUDITOR_TENANT",
  "E2E_AUDITOR_USERNAME",
  "E2E_AUDITOR_PASSWORD",
  "E2E_OPERATOR_TENANT",
  "E2E_OPERATOR_USERNAME",
  "E2E_OPERATOR_PASSWORD",
];

export default async function globalSetup(_config: FullConfig) {
  const missing = required.filter((name) => !process.env[name]);
  if (missing.length > 0) {
    throw new Error(`TASK-0011 browser E2E requires a separately provisioned isolated backend and test identities. Missing: ${missing.join(", ")}`);
  }
  const base = new URL(process.env.E2E_BASE_URL!);
  if (base.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(base.hostname)) {
    throw new Error("TASK-0011 E2E accepts only an isolated loopback test server; remote services are not allowed.");
  }
}
