const [major, minor] = process.versions.node.split(".").map(Number);
const supported =
  (major === 20 && minor >= 19) ||
  (major === 22 && minor >= 12) ||
  (major === 24 && minor >= 0);

if (!supported) {
  console.error(
    `Unsupported Node.js ${process.versions.node}; use Node 20.19+, 22.12+, or 24.x.`,
  );
  process.exitCode = 1;
} else {
  console.log(`Frontend runtime: Node.js ${process.versions.node}`);
}
