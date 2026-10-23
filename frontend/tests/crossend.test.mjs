// 跨端兼容性护栏（零依赖，Node ESM）。运行：npm run test:crossend
//
// 背景：uni-app 的【非 H5 平台】（微信小程序 / App）不支持 Node.js 模块系统：
//   - import.meta / import.meta.env 会被转译成 require('url')，小程序无该模块，
//     导致 app.js 启动即崩（module 'url.js' is not defined），并连锁报「页面未注册」；
//   - process / process.env 在小程序运行时未定义（加 typeof 保护只会让判断恒为 false）；
//   - URLSearchParams / new URL() 在部分小程序基础库上不可用。
// 本测试把这条铁律固化成【可执行的护栏】：任何人再把这些写法写进应用源码，
// 测试立刻变红，而不是等到小程序运行时崩溃才发现。
//
// 正确做法（对齐伯乐 Bole）：环境变量在 vite.config.js（Node 侧）用 loadEnv 读取，
// 经 define 以字面量注入 __APP_ENV__，应用代码只读这个普通对象。
import fs from 'node:fs';
import path from 'node:path';

let pass = 0,
  fail = 0;
const ok = (m) => { pass++; console.log('  ✔ ' + m); };
const no = (m) => { fail++; console.log('  ✘ ' + m); };
const eq = (a, b, m) => (a === b ? ok(m) : no(`${m}（期望 ${b}，实际 ${a}）`));

const ROOT = path.resolve(import.meta.dirname, '..');
const SRC = path.join(ROOT, 'src');

// 去掉注释后再扫描，避免把「警告大家别用 import.meta」的注释本身判为违规
function stripComments(code) {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (/\.(js|ts|vue)$/.test(e.name)) out.push(p);
  }
  return out;
}

// 应用源码里禁止出现的 Node / 浏览器专有语义
const BANNED = [
  { re: /import\s*\.\s*meta/, name: 'import.meta（小程序会转译成 require("url")）' },
  { re: /process\s*\.\s*env/, name: 'process.env（小程序运行时 process 未定义）' },
  { re: /\brequire\s*\(/, name: 'require()（小程序不支持 CommonJS）' },
  { re: /URLSearchParams/, name: 'URLSearchParams（小程序基础库不保证可用）' },
  { re: /from\s*['"]node:/, name: "node: 内置模块导入" },
];

console.log('\n▎应用源码跨端兼容性（src/**）');
const files = walk(SRC);
ok(`扫描 ${files.length} 个源码文件`);
const hits = [];
for (const f of files) {
  const code = stripComments(fs.readFileSync(f, 'utf8'));
  for (const b of BANNED) {
    if (b.re.test(code)) hits.push(`${path.relative(ROOT, f)} → ${b.name}`);
  }
}
eq(hits.length, 0, hits.length === 0 ? '无 Node / 浏览器专有语义' : `发现违规：\n    - ${hits.join('\n    - ')}`);

console.log('\n▎环境变量注入契约（vite.config.js）');
const viteCfg = fs.readFileSync(path.join(ROOT, 'vite.config.js'), 'utf8');
ok('存在配置文件');
// 必须走 define 注入，而不是让应用代码自己去读 import.meta.env
eq(/define\s*:/.test(viteCfg), true, 'vite.config.js 使用 define 注入构建期常量');
eq(/__APP_ENV__/.test(viteCfg), true, '注入键为 __APP_ENV__');
eq(/loadEnv/.test(viteCfg), true, '环境变量由 Node 侧 loadEnv 读取');
// 配置文件自身也不该出现 import.meta（避免配置文件被一起处理时踩同样的坑）
eq(/import\s*\.\s*meta/.test(stripComments(viteCfg)), false, 'vite.config.js 自身不使用 import.meta');

console.log('\n▎config.js 消费方式');
const cfg = fs.readFileSync(path.join(SRC, 'config.js'), 'utf8');
eq(/__APP_ENV__/.test(cfg), true, 'config.js 从 __APP_ENV__ 取值');
eq(/import\s*\.\s*meta/.test(stripComments(cfg)), false, 'config.js 不使用 import.meta');
eq(/process\s*\.\s*env/.test(stripComments(cfg)), false, 'config.js 不使用 process.env');
// config.js 在纯 Node 下必须可用（__APP_ENV__ 未定义时走兜底）
const mod = await import('../src/config.js');
eq(typeof mod.API_BASE, 'string', '纯 Node 下 API_BASE 可解析');
eq(mod.API_BASE.length > 0, true, 'API_BASE 非空');

console.log('\n▎纯 Node 测试契约（api.js / config.js / demoData.js）');
// 这三个文件被 tests/plan.test.mjs、tests/engine.test.mjs 通过【相对路径】直接 import，
// 因此必须保持 .js 扩展名 + 相对导入；一旦改成 .ts 或用 @/ 别名，纯 Node 测试将无法解析。
const NODE_CONTRACT = [
  { file: 'src/utils/api.js', importers: 'tests/plan.test.mjs' },
  { file: 'src/utils/demoData.js', importers: 'tests/plan.test.mjs' },
  { file: 'src/config.js', importers: 'tests/plan.test.mjs / tests/engine.test.mjs' },
];
for (const { file, importers } of NODE_CONTRACT) {
  const abs = path.join(ROOT, file);
  eq(fs.existsSync(abs), true, `${file} 存在`);
  eq(fs.existsSync(abs.replace(/\.js$/, '.ts')), false,
    `${file} 未被改成 .ts（纯 Node 测试靠相对路径解析，importers: ${importers}）`);
  const code = stripComments(fs.readFileSync(abs, 'utf8'));
  eq(/from\s*["']@\//.test(code) || /import\s*["']@\//.test(code), false,
    `${file} 内部仅用相对导入（禁止 @/ 别名，否则纯 Node 测试解析失败）`);
}

console.log('\n▎content.js 懒加载不变量（P1 分包瘦身）');
// 234KB 的 @shared JSON 必须【动态 import()】懒加载，绝不能静态 import 打进主包初始体积。
const contentCode = stripComments(fs.readFileSync(path.join(SRC, 'utils/content.js'), 'utf8'));
eq(/export\s+(async\s+)?function\s+ensureContent/.test(contentCode), true,
  'content.js 导出 ensureContent() 懒加载入口');
eq(/import\s*\(\s*["'](\.\.\/shared\/|@\/shared\/)/.test(contentCode), true,
  'content.js 动态 import() 拉取 src 内（../shared 或 @/shared）JSON');
eq(/from\s*["']@shared\//.test(contentCode) || /import\s*["']@shared\//.test(contentCode), false,
  'content.js 不引用项目外 @shared 别名（外部目录小程序编译失败）');

console.log('\n=====================');
console.log(`结果：${pass} 通过 / ${fail} 失败`);
console.log('=====================');
process.exit(fail === 0 ? 0 : 1);
