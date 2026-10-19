// 前端 SFC 模板静态编译校验（零依赖）
//
// 复用管理端 vendor 里的 Vue 编译器（backend/admin/vendor/vue.global.prod.js），
// 在 Node 里把每个 .vue 的 <template> 编译一遍，用来捕获模板语法错误
// （表达式写错、标签不闭合、指令用法错误等）——无需 npm install / 完整构建。
//
// 运行：cd frontend && node tests/template.test.mjs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const vuePath = path.join(root, "backend", "admin", "vendor", "vue.global.prod.js");

// ---- 最小 DOM shim：Vue 编译器只在解析 v-on / 指令时读少量 DOM API ----
function mkEl(tag) {
  const el = {
    tagName: tag, style: {}, innerHTML: "", dataset: {},
    classList: { add() {}, remove() {} },
    setAttribute() {}, removeAttribute() {}, getAttribute: () => "",
    appendChild() {}, removeChild() {}, addEventListener() {}, removeEventListener() {},
  };
  el.children = [{ getAttribute: () => "" }];
  Object.defineProperty(el, "textContent", {
    get() { return String(el.innerHTML).replace(/<[^>]*>/g, ""); },
    set(v) { el.innerHTML = v; },
  });
  return el;
}
globalThis.window = globalThis;
globalThis.document = {
  createElement: mkEl,
  createElementNS: () => mkEl("svg"),
  createTextNode: () => ({}),
  createComment: () => ({}),
  querySelector: () => null,
  addEventListener() {},
  documentElement: mkEl("html"),
  head: mkEl("head"),
  body: mkEl("body"),
};
// Node 21+ 内置 navigator 为只读 getter，需用 defineProperty 覆盖
Object.defineProperty(globalThis, "navigator", {
  value: { userAgent: "node" }, configurable: true, writable: true,
});

vm.runInThisContext(fs.readFileSync(vuePath, "utf8"));

function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (e.name.endsWith(".vue")) out.push(p);
  }
  return out;
}

const files = walk(path.join(root, "frontend", "src")).sort();
let failed = 0;

for (const file of files) {
  const src = fs.readFileSync(file, "utf8");
  const m = src.match(/<template>([\s\S]*?)<\/template>/);
  const rel = path.relative(root, file);
  if (!m) { console.log(`SKIP  ${rel} (无 template)`); continue; }
  const problems = [];
  try {
    Vue.compile(m[1], {
      onError: (e) => problems.push(`ERROR code=${e.code} @${JSON.stringify(e.loc && e.loc.source || "")}`),
    });
  } catch (e) {
    problems.push(`THROW ${e.message}`);
  }
  if (problems.length) {
    failed++;
    console.log(`FAIL  ${rel}`);
    problems.slice(0, 5).forEach((p) => console.log(`      ${p}`));
  } else {
    console.log(`OK    ${rel}`);
  }
}

console.log("=".repeat(50));
console.log(`结果：${files.length - failed} 通过 / ${failed} 失败`);
console.log("=".repeat(50));
process.exit(failed ? 1 : 0);
