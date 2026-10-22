// 全局用户档案：省份 / 科类 / 位次 / 目标专业。
// 一次输入，跨页复用（「我能上哪 / 院校池 / 查专业 / 志愿表」共享同一份条件），
// 不再在各页重复索要。仅存端侧存储，不上传。
const KEY = "zhiyuan_profile_v1";

export const PROFILE_OPTIONS = {
  provinces: [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
  ],
  subjects: ["物理类", "历史类", "综合/未改革"],
};

export function getProfile() {
  try {
    return uni.getStorageSync(KEY) || {};
  } catch (e) {
    return {};
  }
}

export function setProfile(p) {
  try {
    uni.setStorageSync(KEY, {
      province: (p && p.province) || "",
      subject: (p && p.subject) || "",
      rank: (p && p.rank) || "",
      major: (p && p.major) || "",
    });
  } catch (e) {
    /* 存储不可用（隐私模式）时静默降级 */
  }
}

// 把已存档案回填到表单（只填有值的字段），让任意页打开即带齐条件。
export function applyProfile(form, fields = ["province", "subject", "rank", "major"]) {
  const p = getProfile();
  const out = {};
  fields.forEach((f) => {
    if (p[f]) out[f] = p[f];
  });
  return out;
}

// 把当前表单写入档案（位次转字符串统一存储）。
export function saveFromForm(form) {
  setProfile({
    province: form.province,
    subject: form.subject,
    rank: form.rank,
    major: form.major,
  });
}

export function hasProfile() {
  const p = getProfile();
  return !!(p.province && p.subject && p.rank);
}
