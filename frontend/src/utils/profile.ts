// 全局用户档案：省份 / 科类 / 位次 / 目标专业。
// 一次输入，跨页复用（「我能上哪 / 院校池 / 查专业 / 志愿表」共享同一份条件），
// 不再在各页重复索要。仅存端侧存储，不上传。
import type { Profile } from "@/types";

const KEY = "zhiyuan_profile_v1";

// PROFILE_OPTIONS 已迁移至 src/constants/index.ts（对齐伯乐目录结构），此处重导出以兼容旧引用。
export { PROFILE_OPTIONS } from "@/constants";

export function getProfile(): Partial<Profile> {
  try {
    return (uni.getStorageSync(KEY) || {}) as Partial<Profile>;
  } catch (e) {
    return {};
  }
}

export function setProfile(p: Partial<Profile>): void {
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
export function applyProfile(form: any, fields: Array<keyof Profile> = ["province", "subject", "rank", "major"]) {
  const p = getProfile();
  const out: any = {};
  fields.forEach((f) => {
    if (p[f]) out[f] = p[f];
  });
  return out;
}

// 把当前表单写入档案（位次转字符串统一存储）。
export function saveFromForm(form: any) {
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
