// 全局档案 Store（P2 Pinia 迁移）
// ---------------------------------------------------------------------------
// 底层持久化仍走 utils/profile（端侧存储），Store 仅做响应式状态 + 动作封装。
// 采用「新旧并存」渐进策略：页面可逐步从 `@/utils/profile` 切到此处，旧代码暂不删。
import { defineStore } from "pinia";
import { getProfile, setProfile } from "@/utils/profile";
import type { Profile, Province, Subject } from "@/types";

export const useProfileStore = defineStore("profile", {
  state: () => ({
    province: "" as Province,
    subject: "" as Subject,
    rank: "" as string | number,
    major: "",
  }),
  getters: {
    filled: (s): boolean => !!(s.province && s.subject && s.rank),
  },
  actions: {
    load() {
      const p = (getProfile() || {}) as Profile;
      this.province = (p.province as Province) || "";
      this.subject = (p.subject as Subject) || "";
      this.rank = p.rank ?? "";
      this.major = p.major || "";
    },
    save(p: Partial<Profile>) {
      setProfile({
        province: (p.province as Province) ?? this.province,
        subject: (p.subject as Subject) ?? this.subject,
        rank: p.rank ?? this.rank,
        major: p.major ?? this.major,
      });
      this.load();
    },
  },
});
