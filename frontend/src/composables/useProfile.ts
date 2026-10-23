// 组合式函数：全局档案（P3 目录重构，对齐伯乐 composables/）
// ---------------------------------------------------------------------------
// 底层持久化仍走 utils/profile.js（端侧存储），此处仅做响应式包装，方便页面 setup 里使用。
import { computed } from "vue";
import {
  getProfile,
  setProfile,
  hasProfile,
  applyProfile,
  saveFromForm,
} from "@/utils/profile.js";
import type { Profile } from "@/types";

export function useProfile() {
  const profile = computed<Profile>(() => getProfile() as Profile);
  return { profile, getProfile, setProfile, hasProfile, applyProfile, saveFromForm };
}
