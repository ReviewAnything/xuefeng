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
  buildPlan,
  breachStatus,
  breachStats,
  appendSafeSchools,
  selectBackstops,
  diffSafePatch,
  fillOrder,
  buildFillOrderText,
} from "../src/utils/plan.ts";
import { resolveBase } from "../src/utils/api.ts";

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

console.log("\n▎结论页 → 志愿表 plan.js#buildPlan");
const built = buildPlan({
  province: "广东", subject: "物理类", user_rank: 40000, major: "",
  tiers: [{
    tier: "211", level: "稳", min_score: 529, min_rank: 100604,
    data_source: "official", source_year: 2024, carried: true,
    schools: [{ name: "暨南大学", province: "广东", min_score: 590, min_rank: 28000, line_year: 2024, data_source: "school_line" }],
  }],
});
eq(built.tiers.length, 1, "按档落盘");
eq(built.tiers[0].schools[0].min_score, 590, "校线分数带进志愿表");
eq(built.tiers[0].carried, true, "沿用标记带进志愿表");
eq(built.tiers[0].pool_shared_with, null, "缺省共享池为 null");
eq(buildPlan(null), null, "空输入不落盘");
eq(typeof built.at, "number", "时间戳为毫秒数");

console.log("\n▎S4 保底安全网 breach 红灯（回归：保底失守不可见）");
// 用户位次 58000；三所"保底"：甲(投档位次 29731,够不上→失守)、乙(投档位次 70000,安全)、
// 丙(无投档线,不可判定→不计入失守)。
const breachPlan = {
  province: "河南", subject: "物理类", user_rank: 58000, at: "2026-10-20T02:30:00.000Z",
  tiers: [{
    level: "保", tier: "普通本科",
    schools: [
      { name: "甲大学", min_rank: 29731, line_rank: 29731, line_year: 2024 },
      { name: "乙大学", min_rank: 70000, line_rank: 70000, line_year: 2024 },
      { name: "丙大学" },
    ],
  }],
};
const breachRows = flattenPlan(breachPlan);
eq(breachRows.length, 3, "保底三行拍平");
eq(breachStatus(58000, { level: "冲", line_rank: 1 }), "unknown", "非保底档永不判定");
eq(breachStatus(58000, { level: "保", line_rank: 29731 }), "breach", "位次更靠后 → 失守");
eq(breachStatus(58000, { level: "保", line_rank: 70000 }), "safe", "位次更靠前 → 安全");
eq(breachStatus(58000, { level: "保" }), "unknown", "缺投档线 → 不误判为安全");
eq(breachStatus(58000, { level: "保", line_rank: 0 }), "unknown", "投档位次为 0 → 不可判定");
const bs = breachStats(breachPlan, breachRows);
eq(bs, { breach: 1, covered: 2, total: 3 }, "失守 1 / 可判定 2 / 共 3");
// 用户位次足够好 → 全部安全，红灯为 0
const safePlan = { ...breachPlan, user_rank: 10000 };
eq(breachStats(safePlan, flattenPlan(safePlan)), { breach: 0, covered: 2, total: 3 }, "位次好时红灯为 0");
// 全无投档线 → muted（未核验），红灯 0 但 covered 0
const noLinePlan = { province: "西藏", subject: "理工", user_rank: 5000, at: "x",
  tiers: [{ level: "保", tier: "普通本科", schools: [{ name: "丁大学" }] }] };
eq(breachStats(noLinePlan, flattenPlan(noLinePlan)), { breach: 0, covered: 0, total: 1 }, "无投档线时不误判，covered=0");
eq(breachStats(null, null), { breach: 0, covered: 0, total: 0 }, "空输入安全返回");

console.log("\n▎S5-C 保底失守一键补位 selectBackstops + appendSafeSchools");
// 一个已失守的志愿表（保底档有 2 所，其中丁大学失守）
const patchPlan = {
  province: "河南", subject: "物理类", user_rank: 58000, at: "x",
  tiers: [
    { level: "冲", tier: "985", schools: [{ name: "甲大学", min_rank: 1000 }] },
    { level: "保", tier: "普通本科", schools: [
      { name: "丙大学", province: "河南", nature: "公办", min_score: 500, min_rank: 29731, line_year: 2025, data_source: "school_line" },
      { name: "丁大学", province: "河南", nature: "公办", min_score: 480, min_rank: 70000, line_year: 2025, data_source: "school_line" },
    ] },
  ],
};
// 候选兜底（模拟 recommend 返回的院校行）。位次口径：min_rank = 该校最低投档位次，
// 数字越大门槛越低；用户位次 58000 更靠前才稳够，即只挑 min_rank > 58000 的院校。
// 己(65000)、庚(90000) 稳够；戊(55000)、丙(29731) 门槛比用户还高 → 必须排除。
const rec = {
  tiers: [{ level: "保", tier: "普通二本", schools: [
    { name: "戊大学", province: "河南", nature: "公办", min_score: 460, min_rank: 55000, line_year: 2025, data_source: "school_line" },
    { name: "己大学", province: "河南", nature: "公办", min_score: 470, min_rank: 65000, line_year: 2025, data_source: "school_line" },
    { name: "庚大学", province: "河南", nature: "公办", min_score: 600, min_rank: 90000, line_year: 2025, data_source: "school_line" },
    { name: "丙大学", province: "河南", nature: "公办", min_score: 500, min_rank: 29731, line_year: 2025, data_source: "school_line" },
  ] }],
};
const picks = selectBackstops(rec, 58000, 6);
eq(picks.length, 2, "只挑门槛比用户位次更靠后的院校（己、庚），排除够不上的戊、丙");
eq(picks[0].name, "庚大学", "门槛最宽（min_rank 最大）排第一");
eq(picks.some((s) => s.name === "戊大学"), false, "够不上的戊大学被排除（min_rank 55000 < 58000）");
eq(picks.some((s) => s.name === "丙大学"), false, "够不上的丙大学被排除");
// 补位方向红线：补进来的每一所都必须「用户稳够」，否则安全网是假的
eq(picks.every((s) => s.min_rank > 58000), true, "补位候选全部满足 min_rank > 用户位次");
// appendSafeSchools 只按名字去重 + 并入保底档（不做 min_rank 过滤，那是 selectBackstops 的职责）
const patched = appendSafeSchools(JSON.parse(JSON.stringify(patchPlan)), picks);
const safeTier = patched.tiers.find((t) => t.level === "保");
eq(safeTier.schools.length, 4, "补位后保底档 4 所（原 2 + 己、庚）");
eq(safeTier.schools.some((s) => s.name === "庚大学"), true, "庚大学并入保底档");
eq(safeTier.schools.some((s) => s.name === "己大学"), true, "己大学并入保底档");
eq(appendSafeSchools(null, picks), null, "空 plan 安全返回");
eq(appendSafeSchools(patchPlan, []), patchPlan, "无候选时不改动 plan");

console.log("\n▎S7-E 补位前后对比 diffSafePatch");
const diff = diffSafePatch(patchPlan, picks);
eq(diff.before, { breach: 1, covered: 2, total: 2 }, "补位前：保底档 2 所，丙大学（29731）已失守");
eq(diff.safe_before, 1, "补位前只有丁大学 1 所可稳够");
eq(diff.added.map((s) => s.name), ["庚大学", "己大学"], "新增两所真正稳够的兜底院校");
eq(diff.skipped, 0, "候选都不在表里，无重复跳过");
eq(diff.after.total, 4, "补位后保底档 4 所");
eq(diff.safe_after, 3, "补位后可稳够 3 所（安全网真的被撑住了）");
eq(diff.after.breach, 1, "失守数没被假装抹掉");
eq(diff.still_breach, ["丙大学"], "原失守行仍在表里 → 明确列出，提示用户自行下调或移除");
eq(/可稳够 1 → 3 所/.test(diff.text), true, "文案说清「可稳够」前后变化");
eq(patchPlan.tiers.find((t) => t.level === "保").schools.length, 2,
   "diffSafePatch 不改原 plan（在副本上补位，可先预览再落盘）");
eq(diff.next.tiers.find((t) => t.level === "保").schools.length, 4, "next 是补位后的 plan");
eq(diffSafePatch(patchPlan, []).added.length, 0, "无候选时无新增");
eq(diffSafePatch(null, picks).added.length, 0, "空 plan 安全返回");
eq(diffSafePatch({ tiers: [] }, picks).text.indexOf("补位") >= 0, true,
   "空表也能给出可读文案");

console.log("\n▎S8-D 填报顺序 fillOrder / buildFillOrderText");
// 位次 58000：西北农林(冲, 29731 需冲刺) / 郑州大学(稳, 66000 可稳够) / 河南大学(保, 90000 最稳) / 无数据行
const orderPlan = {
  province: "河南", subject: "物理类", user_rank: 58000, major: "计算机科学与技术",
  at: "2026-10-20T02:30:00.000Z",
  tiers: [
    { level: "保", tier: "普通本科", schools: [{ name: "河南大学", min_rank: 90000 }] },
    { level: "冲", tier: "985", schools: [{ name: "西北农林科技大学", min_rank: 29731 }] },
    { level: "稳", tier: "211", schools: [{ name: "郑州大学", min_rank: 66000 }] },
    { level: "保", tier: "专科", schools: [{ name: "某职业学院" }] },
  ],
};
const orderRows = flattenPlan(orderPlan);
const ord = fillOrder(orderPlan, orderRows);
eq(ord.total, 4, "4 所院校全部进入顺序（含 1 所无位次数据）");
eq(ord.items.map((i) => i.level), ["冲", "稳", "保", "保"], "先按档位 冲 → 稳 → 保");
eq(ord.items.map((i) => i.name),
   ["西北农林科技大学", "郑州大学", "河南大学", "某职业学院"],
   "同档内按位次余量从大到小；无数据行附在同档末尾");
eq(ord.items[0].margin, 29731 - 58000, "冲档余量为负（门槛比自己靠前）");
eq(ord.items[1].margin, 8000, "稳档余量 +8000");
eq(ord.items[2].margin, 32000, "保档余量最大 → 排在同档最前");
eq(ord.items[0].margin_label.indexOf("冲刺") >= 0, true, "冲档文案说明是冲刺");
eq(ord.items[2].margin_label.indexOf("可稳够") >= 0, true, "正余量文案说明可稳够");
eq(ord.items[3].has_line_data, false, "无位次数据的行被明确标记");
eq(ord.items[3].margin_label.indexOf("无投档线数据") >= 0, true, "无数据文案说明不参与余量排序");
eq(ord.unknown_count, 1, "统计无数据行数");
eq(ord.items.map((i) => i.seq), [1, 2, 3, 4], "序号连续，可直接照抄");
// 同档内余量相同时保持原表顺序，避免每次渲染跳动
const tiePlan = { user_rank: 10000, tiers: [{ level: "保", tier: "t", schools: [
  { name: "甲大学", min_rank: 50000 }, { name: "乙大学", min_rank: 50000 }] }] };
eq(fillOrder(tiePlan, flattenPlan(tiePlan)).items.map((i) => i.name),
   ["甲大学", "乙大学"], "余量相同时保持原表顺序（避免随机跳动）");
// 边界
eq(fillOrder(null, []).total, 0, "空表安全返回");
eq(fillOrder({ user_rank: 0 }, [{ name: "甲" }]).items[0].has_line_data, false,
   "用户位次缺失时不臆造余量");
const orderText = buildFillOrderText(orderPlan, ord, "2026-10-20 10:30");
eq(/排序依据/.test(orderText), true, "导出文本说明排序依据");
eq(/不承诺录取/.test(orderText), true, "导出文本含「不承诺录取」红线");
eq(/1\. \[冲\]/.test(orderText), true, "导出文本含序号与档位");
eq(/其中 1 所缺往年投档位次/.test(orderText), true, "导出文本说明无数据行的处理");
eq(/不构成录取承诺/.test(orderText), true, "结尾再次声明不构成承诺");

console.log("\n▎S9-B 位次余量跨年/跨批次可比性");
// 参考年取最新年份；与参考年/批次不同的行标记 comparable=false，余量仅供参考
const cmpPlan = {
  province: "河南", subject: "物理类", user_rank: 58000, major: "计算机科学与技术",
  at: "2026-10-20T02:30:00.000Z",
  tiers: [
    { level: "稳", tier: "211", schools: [
      { name: "郑州大学", min_rank: 66000, line_year: 2025, batch: "本科批" },
      { name: "武汉理工", min_rank: 70000, line_year: 2024, batch: "本科批" },        // 跨年
      { name: "合肥工大", min_rank: 72000, line_year: 2025, batch: "国家专项计划批" }, // 跨批次
    ] },
  ],
};
const cmp = fillOrder(cmpPlan, flattenPlan(cmpPlan));
eq(cmp.reference_year, 2025, "参考年取最新年份 2025");
eq(cmp.reference_batch, "本科批", "参考批次取众数 本科批");
const cz = cmp.items.find((i) => i.name === "郑州大学");
const wh = cmp.items.find((i) => i.name === "武汉理工");
const hf = cmp.items.find((i) => i.name === "合肥工大");
eq(cz.comparable, true, "同口径行(2025/本科批) comparable=true");
eq(wh.comparable, false, "跨年行(2024) comparable=false");
eq(hf.comparable, false, "跨批次行 comparable=false");
eq(wh.cross_year, true, "跨年标记");
eq(hf.cross_batch, true, "跨批次标记");
eq(wh.margin_label.indexOf("余量仅供参考") >= 0, true, "跨年余量标注「仅供参考」");
eq(hf.margin_label.indexOf("余量仅供参考") >= 0, true, "跨批次余量标注「仅供参考」");
eq(cmp.incomparable_count, 2, "统计不可比行数");
// 同档内可比优先：郑州(可比) 排在前，跨年/跨批次行附后（按余量降序）
eq(cmp.items.map((i) => i.name), ["郑州大学", "合肥工大", "武汉理工"], "可比行优先排前");
const cmpText = buildFillOrderText(cmpPlan, cmp, "2026-10-20 10:30");
eq(/参考口径：年份 2025/.test(cmpText), true, "导出含参考年");
eq(/批次「本科批」/.test(cmpText), true, "导出含参考批次");
eq(/另：其中 2 所投档线/.test(cmpText), true, "导出含不可比说明");

// 全部同口径时不报不可比
const samePlan = { user_rank: 1000, tiers: [{ level: "保", tier: "t", schools: [
  { name: "甲", min_rank: 5000, line_year: 2025, batch: "本科批" },
  { name: "乙", min_rank: 6000, line_year: 2025, batch: "本科批" }] }] };
const same = fillOrder(samePlan, flattenPlan(samePlan));
eq(same.incomparable_count, 0, "同口径全可比 → 无不可比");
eq(same.items.every((i) => i.comparable), true, "同口径每行 comparable=true");

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
