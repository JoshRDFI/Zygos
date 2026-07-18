// Copies the VAD runtime assets out of node_modules into public/vad so they are
// served from our own origin (no CDN) — keeps voice fully offline/data-local.
import { mkdirSync, copyFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dest = join(root, "public", "vad");
const vadDist = join(root, "node_modules", "@ricky0123", "vad-web", "dist");
const ortDist = join(root, "node_modules", "onnxruntime-web", "dist");

for (const d of [vadDist, ortDist]) {
  if (!existsSync(d)) throw new Error(`missing dependency dir: ${d} (run npm install first)`);
}
mkdirSync(dest, { recursive: true });

const vadFiles = readdirSync(vadDist).filter(
  (f) => f.endsWith(".onnx") || f.endsWith(".worklet.bundle.min.js"),
);
const ortFiles = readdirSync(ortDist).filter(
  (f) => f.startsWith("ort-") && (f.endsWith(".wasm") || f.endsWith(".mjs")),
);

if (vadFiles.length === 0) throw new Error(`no vad-web assets (.onnx/worklet) in ${vadDist}`);
if (!ortFiles.some((f) => f.endsWith(".wasm"))) throw new Error(`no onnxruntime wasm in ${ortDist}`);

for (const f of vadFiles) copyFileSync(join(vadDist, f), join(dest, f));
for (const f of ortFiles) copyFileSync(join(ortDist, f), join(dest, f));

console.log(`vendored ${vadFiles.length} vad + ${ortFiles.length} ort files -> public/vad`);
