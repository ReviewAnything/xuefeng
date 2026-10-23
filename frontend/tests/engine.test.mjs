// 前端决策引擎单测（零依赖，Node ESM）。运行：npm run test:engine
import {
  VIEW_LABEL,
  buildStrategy,
  pickMajors,
  buildBiasWarn,
  buildCanvas,
} from "../src/subpackages/diagnose/engine.ts";

let pass = 0,
  fail = 0;
const ok = (m) => { pass++; console.log("  ✔ " + m); };
const bad = (m) => { fail++; console.error("  ✘ " + m); };

console.log("\n▎前端决策引擎 engine.js");

const MAJORS = [
  { name: "计算机科学与技术", cat: "理工硬核", view: "recommend", tags: ["技术壁垒"], reason: "r", bias: "b" },
  { name: "电气工程及其自动化", cat: "理工硬核", view: "recommend", tags: ["国网校招", "越老越香"], reason: "r", bias: "b" },
  { name: "临床医学", cat: "医学类", view: "recommend", tags: [], reason: "r", bias: "b" },
  { name: "法学", cat: "文科保底", view: "recommend", tags: [], reason: "r", bias: "b" },
  { name: "公费师范生", cat: "体制内", view: "recommend", tags: [], reason: "r", bias: "b" },
  { name: "生物工程", cat: "避坑天坑", view: "avoid", tags: [], reason: "r", bias: "b" },
];

// 1. 策略分层
buildStrategy("冲刺985").includes("985") ? ok("985 策略正确") : bad("985 策略错误");
buildStrategy("专科/高职").includes("一技之长") ? ok("专科策略正确") : bad("专科策略错误");

// 2. 历史类过滤：应排除理工硬核（非医学/体制内/文科）
const hist = pickMajors({ subject: "历史类" }, MAJORS);
hist.every((m) => ["文科保底", "体制内"].includes(m.cat) || m.name.includes("法学")) && !hist.some((m) => m.cat === "理工硬核")
  ? ok("历史类过滤掉理工硬核") : bad("历史类过滤异常");

// 2b. 历史类不得推荐「物理必选」的体制内方向（与后端 SUBJECT_REQ 对齐）
const histWithPhysicsOnly = pickMajors({ subject: "历史类" }, [
  ...MAJORS,
  { name: "军校", cat: "体制内", view: "recommend", tags: [], reason: "r", bias: "b" },
  { name: "定向士官", cat: "体制内", view: "recommend", tags: [], reason: "r", bias: "b" },
  { name: "警校/公安类", cat: "体制内", view: "recommend", tags: [], reason: "r", bias: "b" },
]);
!histWithPhysicsOnly.some((m) => ["军校", "定向士官"].includes(m.name))
  && histWithPhysicsOnly.some((m) => m.name === "警校/公安类")
  ? ok("历史类剔除物理必选的军校/士官，保留公安类")
  : bad("历史类选科过滤异常：" + histWithPhysicsOnly.map((m) => m.name).join(","));

// 3. 求稳优先过滤：普通家庭求稳应剔除无壁垒的纯理工（保留有国网/越老越香/医学/体制内/文科）
const stable = pickMajors({ subject: "物理类", familyBg: "普通家庭", riskPref: "求稳优先", goal: "稳定/有编有岗" }, MAJORS);
!stable.some((m) => m.name === "计算机科学与技术") && stable.some((m) => m.name === "电气工程及其自动化")
  ? ok("求稳优先保留电气(国网)、剔除纯计算机") : bad("求稳优先过滤异常：" + stable.map((m) => m.name).join(","));

// 4. 偏见校正提示区分人群
buildBiasWarn({ familyBg: "资源型(有人脉/可试错)" }).includes("约束较弱") ? ok("资源型提示正确") : bad("资源型提示错误");
buildBiasWarn({ familyBg: "寒门(容错率低)" }).includes("核心适用人群") ? ok("寒门提示正确") : bad("寒门提示错误");

// 5. 完整画布结构
const cv = buildCanvas({ tier: "普通一本/二本", subject: "物理类" }, MAJORS);
cv.strategy && Array.isArray(cv.picks) && cv.biasWarn && Array.isArray(cv.next) && Array.isArray(cv.avoidHint)
  ? ok("buildCanvas 结构完整") : bad("buildCanvas 结构缺失");
cv.picks.length > 0 && cv.picks.length <= 8 ? ok(`推荐方向数量合理(${cv.picks.length})`) : bad("推荐方向数量异常");

console.log(`\n=====================\n结果：${pass} 通过 / ${fail} 失败\n=====================`);
process.exit(fail ? 1 : 0);
