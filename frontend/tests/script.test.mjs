// 前端 SFC 脚本静态语法校验（零依赖）
//
// 背景（2026-10-21 实际踩坑）：about.vue 里 `const open = ref("1")` 与
// `function open(u)` 在 <script setup> 里撞名，编译期 SyntaxError，整页白屏；
// 但 template.test.mjs 只编译模板，脚本坏没坏完全测不到，uni-app 构建前无感。
//
// 做法：抽每个 .vue 的 <script setup>，去掉 import/export 后用
// node:vm 的 new Function（或 Script）做语法编译——捕获重复声明、
// 括号不配对等一切语法级错误。无需 npm install / 完整构建。
//
// 运行：cd frontend && node tests/script.test.mjs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const pagesDir = path.resolve(here, "..", "src", "pages");

function listVue(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...listVue(p));
    else if (e.name.endsWith(".vue")) out.push(p);
  }
  return out;
}

// <script setup> 里的 import 语句在 new Function 作用域里不合法，去掉；
// export 前缀同理。剩余部分做语法编译即可覆盖「重复声明/括号不配对」等错误。
function stripModuleSyntax(code) {
  return code
    .replace(/^\s*import[\s\S]*?from\s*["'][^"']+["'];?\s*$/gm, "")
    .replace(/^\s*import\s+["'][^"']+["'];?\s*$/gm, "")
    .replace(/^\s*export\s+/gm, "");
}

const files = listVue(pagesDir);
let pass = 0;
const fails = [];

for (const f of files) {
  const rel = path.relative(pagesDir, f);
  const src = fs.readFileSync(f, "utf8");
  const m = src.match(/<script setup>([\s\S]*?)<\/script>/);
  if (!m) { console.log(`跳过（无 script setup）：${rel}`); continue; }
  const body = stripModuleSyntax(m[1]);
  try {
    // script setup 里允许 await / 环境宏，用普通函数体编译即可捕获语法错误
    new vm.Script(`(function(){\n"use strict";\n${body}\n})()`, { filename: rel });
    pass += 1;
  } catch (err) {
    fails.push({ rel, err });
  }
}

console.log("=".repeat(50));
for (const { rel, err } of fails) {
  console.log(`FAIL  ${rel}\n      ${err.message}`);
}
console.log(`结果：${pass} 通过 / ${fails.length} 失败（共 ${files.length} 个页面组件）`);
console.log("=".repeat(50));
process.exit(fails.length ? 1 : 0);
