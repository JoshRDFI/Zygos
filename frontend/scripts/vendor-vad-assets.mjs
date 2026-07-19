// Copies the VAD runtime assets out of node_modules into public/vad so they are
// served from our own origin (no CDN) — keeps voice fully offline/data-local.
import { mkdirSync, copyFileSync, readdirSync, existsSync, statSync, utimesSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dest = join(root, "public", "vad");
const vadDist = join(root, "node_modules", "@ricky0123", "vad-web", "dist");
const ortDist = join(root, "node_modules", "onnxruntime-web", "dist");

for (const d of [vadDist, ortDist]) {
  if (!existsSync(d)) throw new Error(`missing dependency dir: ${d} (run npm install first)`);
}

const vadFiles = readdirSync(vadDist).filter(
  (f) => f.endsWith(".onnx") || f.endsWith(".worklet.bundle.min.js"),
);
const ortFiles = readdirSync(ortDist).filter(
  (f) => f.startsWith("ort-") && (f.endsWith(".wasm") || f.endsWith(".mjs")),
);

if (vadFiles.length === 0) throw new Error(`no vad-web assets (.onnx/worklet) in ${vadDist}`);
if (!ortFiles.some((f) => f.endsWith(".wasm"))) throw new Error(`no onnxruntime wasm in ${ortDist}`);

// Only create the destination once we know there is something valid to vendor.
mkdirSync(dest, { recursive: true });

let copied = 0;
let skipped = 0;
function vendor(srcDir, f) {
  const src = join(srcDir, f);
  const dst = join(dest, f);
  const s = statSync(src);
  if (existsSync(dst)) {
    const d = statSync(dst);
    // These assets total ~81MB; skip the copy when size + mtime already match the
    // source (mtime is preserved below) so postinstall/predev/prebuild stay fast.
    // Sub-millisecond tolerance: utimesSync rounds/truncates the source's sub-ms
    // mtime inconsistently across filesystems, so compare within 1ms. A genuine
    // asset swap (new package build) shifts the mtime by seconds, far beyond this.
    if (d.size === s.size && Math.abs(d.mtimeMs - s.mtimeMs) < 1) {
      skipped++;
      return;
    }
  }
  copyFileSync(src, dst);
  utimesSync(dst, s.atime, s.mtime); // preserve mtime so the next run can skip
  copied++;
}

for (const f of vadFiles) vendor(vadDist, f);
for (const f of ortFiles) vendor(ortDist, f);

console.log(`vendored ${copied} + skipped ${skipped} (of ${vadFiles.length} vad + ${ortFiles.length} ort) -> public/vad`);
