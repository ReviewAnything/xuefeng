// 单一数据源：通过 @shared 别名引入 shared/content.json，与 Python 后端共用同一份内容
import data from "@shared/content.json";

export const APP_VERSION = data.APP_VERSION;
export const DATA_DATE = data.DATA_DATE;
export const QUESTIONS = data.QUESTIONS;
export const MAJORS = data.MAJORS;
export const RESOURCES = data.RESOURCES;
// 内容可溯：观点整理年份与证据口径（每个专业另带 source_year / source_note）
export const CONTENT_SOURCE = data.CONTENT_SOURCE || {};

export const VIEW_LABEL = { recommend: "推荐", caution: "慎选", avoid: "避坑" };
export const CATS = ["理工硬核", "医学类", "文科保底", "体制内", "避坑天坑"];
export const RES_CATS = [
  { key: "all", label: "全部" },
  { key: "mind", label: "思想/语料" },
  { key: "tool", label: "数据/工具" },
];
