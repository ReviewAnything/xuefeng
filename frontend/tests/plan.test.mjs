// 志愿表纯函数单测（零依赖，Node ESM）。运行：npm run test:plan
import {
  PLAN_KEY,
  LEVELS,
  flattenPlan,
  groupRows,
  formatTime,
  fillStats,
  buildPlanText,
  applyMajors,
  collectMajors,
} from "../src/utils/plan.js";
import { resolveBase } from "../src/utils/api.js";

let pass = 0,
  fail = 0;
const ok = (m) => { pass++; console.log("  ✔ " + m); };
const bad = (m) => { fail++; console.error("  ✘ " + m); };
const eq = (a, b, m) => (JSON.stringify(a) === JSON.stringify(b) ? ok(m) : bad(m + ` → ${JSON.stringify(a)} ≠ ${JSON.stringify(b)}`));

console.log("\n▎志愿表工具 plan.js");

eq(PLAN_KEY, "zhiyuan_plan_v1", "存储键固定，避免读写错位");
eq(LEVELS.map((l) => l.key), ["冲", "稳", "保"], "三档顺序固定");

const plan = {
  province: "河南",
  subject: "物理类",
  user_rank: 58000,
  major: "计算机科学与技术",
  at: "2026-10-20T02:30:00.000Z",
  tiers: [
    { level: "冲", tier: "985", schools: [{ name: "西北农林科技大学", province: "陕西", min_score: 589, min_rank: 29731, data_source: "school_line" }] },
    { level: "稳", tier: "211", schools: [{ name: "郑州大学", province: "河南" }] },
    { level: "保", tier: "普通本科", schools: [{ name: "河南大学", province: "河南" }] },
    { level: "不可及", tier: "专科", schools: [{ name: "某职业学院" }] },
  ],
};

const rows = flattenPlan(plan);
eq(rows.length, 3, "「不可及」档被丢弃");
eq(rows[0].key, "985-西北农林科技大学", "行 key 由层次+校名构成");
eq(rows[0].major, "计算机科学与技术", "行继承目标专业作为默认拟报");
eq(rows[1].major, "计算机科学与技术", "多行共用同一默认专业");
eq(rows[0].line, 589, "院校级投档分透传到行");
eq(rows[1].line, null, "缺失投档分时为 null（页面回退层次提示）");
eq(flattenPlan(null), [], "空 plan 安全返回空数组");
eq(flattenPlan({ tiers: [{ level: "冲" }] }), [], "tiers.schools 缺失不报错");

const groups = groupRows(rows);
eq(groups.map((g) => g.rows.length), [1, 1, 1], "分档行数正确");
eq(groups.map((g) => g.level), ["冲", "稳", "保"], "分组顺序固定");
eq(groupRows([]).map((g) => g.rows.length), [0, 0, 0], "空输入仍返回三个空组（页面需提示）");

eq(formatTime("2026-10-20T02:30:00.000Z").length, 16, "时间格式为 YYYY-MM-DD HH:mm");
eq(formatTime(""), "-", "空时间显示 -");
eq(formatTime("not-a-date"), "-", "非法时间显示 -");

eq(fillStats([{ major: "计算机" }, { major: "  " }, { major: "" }]), { filled: 1, total: 3 }, "填写进度只算非空专业");
eq(fillStats(null), { filled: 0, total: 0 }, "空输入进度为 0");

const text = buildPlanText(plan, groups, "2026-10-20 10:30");
[
  ["含标题", "志愿表草稿"],
  ["含省份与位次", "河南 | 科类：物理类 | 位次：58000"],
  ["含三档标题", "【冲（够一够）】"],
  ["含院校行", "1. 西北农林科技大学（985）"],
  ["含真实投档线", "去年最低 589 分 / 位次 29731"],
  ["缺失投档线不渲染该字段", "1. 郑州大学（211）  拟报专业"],
  ["含免责声明", "以考试院/院校招生网为准"],
].forEach(([label, needle]) => (text.includes(needle) ? ok(label) : bad(label + " → 未找到 " + needle)));

console.log("\n▎拟报专业持久化（回归：离开页面即丢）");
const draft = flattenPlan({
  province: "河南",
  subject: "物理类",
  user_rank: 58000,
  tiers: [{ level: "冲", tier: "985", schools: [{ name: "甲大学" }, { name: "乙大学" }] }],
});
draft[0].major = "软件工程";
draft[1].major = "   ";
const savedMajors = collectMajors(draft);
eq(savedMajors, { "985-甲大学": "软件工程" }, "只落盘非空拟报专业");
const restored = applyMajors(
  flattenPlan({ tiers: [{ level: "冲", tier: "985", schools: [{ name: "甲大学" }, { name: "乙大学" }] }] }),
  savedMajors,
);
eq(restored[0].major, "软件工程", "重新进入页面后回填拟报专业");
eq(restored[1].major, "", "空值不覆盖默认专业");
eq(applyMajors(draft, null) === draft, true, "无历史草稿时安全返回");

console.log("\n▎院校投档线年份（回归：savePlan 丢字段导致「去年最低」永远为空）");
const lineRows = flattenPlan({
  tiers: [{
    level: "稳",
    tier: "211",
    schools: [{ name: "郑州大学", min_score: 589, min_rank: 29731, line_year: 2024, data_source: "school_line" }],
  }],
});
eq(lineRows[0].line, 589, "投档分透传");
eq(lineRows[0].line_rank, 29731, "投档位次透传");
eq(lineRows[0].line_year, 2024, "投档年份透传");
const lineText = buildPlanText({ province: "河南", subject: "物理类", user_rank: 1 }, groupRows(lineRows), "-");
eq(lineText.includes("去年最低 589 分（2024） / 位次 29731"), true, "导出文本带年份");

console.log("\n▎API 地址解析 api.js");
const savedWindow = globalThis.window;
globalThis.window = { __XUEFENG_API__: "https://api.example.com" };
eq(resolveBase(), "https://api.example.com", "运行时注入优先于构建期");
globalThis.window = {};
eq(resolveBase(), "http://localhost:8000", "无注入时回退本机后端");
globalThis.window = savedWindow;

console.log("\n=====================");
console.log(`结果：${pass} 通过 / ${fail} 失败`);
console.log("=====================");
process.exit(fail === 0 ? 0 : 1);
