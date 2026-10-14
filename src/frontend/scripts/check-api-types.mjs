import { readFile, unlink } from "node:fs/promises";

const generated = new URL("../src/api/schema.check.d.ts", import.meta.url);
const committed = new URL("../src/api/schema.d.ts", import.meta.url);

try {
  const [current, expected] = await Promise.all([
    readFile(generated, "utf8"),
    readFile(committed, "utf8").catch(() => null),
  ]);
  if (expected === null || current !== expected) {
    process.stderr.write(
      "OpenAPI types are missing or stale. Run npm run api:generate and review the generated diff.\n",
    );
    process.exitCode = 1;
  } else {
    process.stdout.write(
      "OpenAPI-generated TypeScript types match contracts/openapi.yaml.\n",
    );
  }
} finally {
  await unlink(generated).catch(() => undefined);
}
