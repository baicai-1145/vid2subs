/* eslint-disable no-console */
/**
 * 从 node_modules 中拷贝 ffmpeg 相关静态资源到
 * src/vid2subs/web/static/ffmpeg 目录。
 *
 * 使用方式：
 *   npm install
 *   npm run prepare-ffmpeg
 */

const fs = require("fs");
const path = require("path");

function copyFile(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  console.log(`copied: ${src} -> ${dest}`);
}

function main() {
  const projectRoot = path.resolve(__dirname, "..");
  const staticDir = path.join(projectRoot, "src", "vid2subs", "web", "static", "ffmpeg");

  const ffmpegEsmDir = path.join(
    projectRoot,
    "node_modules",
    "@ffmpeg",
    "ffmpeg",
    "dist",
    "esm"
  );
  const coreEsmDir = path.join(
    projectRoot,
    "node_modules",
    "@ffmpeg",
    "core",
    "dist",
    "esm"
  );

  if (!fs.existsSync(ffmpegEsmDir)) {
    console.error(
      "未找到 @ffmpeg/ffmpeg ESM 目录，请先执行：npm install @ffmpeg/ffmpeg @ffmpeg/core"
    );
    process.exit(1);
  }

  if (!fs.existsSync(coreEsmDir)) {
    console.error("未找到 @ffmpeg/core ESM 目录，请先执行：npm install @ffmpeg/core");
    process.exit(1);
  }

  // 1) 拷贝 ffmpeg ESM 目录下的所有 JS/MJS 文件到 static/ffmpeg
  const entries = fs.readdirSync(ffmpegEsmDir, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const ext = path.extname(entry.name).toLowerCase();
    if (ext !== ".js" && ext !== ".mjs") continue;
    const src = path.join(ffmpegEsmDir, entry.name);
    const dest = path.join(staticDir, entry.name);
    copyFile(src, dest);
  }

  // 为了与前端 import("/static/ffmpeg/ffmpeg.js") 对齐，
  // 如果没有 ffmpeg.js，则直接复制 index.js 作为 ffmpeg.js。
  const ffmpegIndex = path.join(staticDir, "index.js");
  const ffmpegEntry = path.join(staticDir, "ffmpeg.js");
  if (!fs.existsSync(ffmpegEntry) && fs.existsSync(ffmpegIndex)) {
    copyFile(ffmpegIndex, ffmpegEntry);
  }

  // 2) 拷贝 core ESM 中的 core JS/wasm
  const coreJs = path.join(coreEsmDir, "ffmpeg-core.js");
  const coreWasm = path.join(coreEsmDir, "ffmpeg-core.wasm");
  if (!fs.existsSync(coreJs) || !fs.existsSync(coreWasm)) {
    console.error(
      "在 @ffmpeg/core/dist/esm 下未找到 ffmpeg-core.js / ffmpeg-core.wasm，请检查安装的版本结构。"
    );
    process.exit(1);
  }

  copyFile(coreJs, path.join(staticDir, "ffmpeg-core.js"));
  copyFile(coreWasm, path.join(staticDir, "ffmpeg-core.wasm"));
}

main();
