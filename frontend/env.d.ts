// 全局类型声明（渐进式 TS 第一阶段）
// ---------------------------------------------------------------------------
// __APP_ENV__ 由 vite.config.js 经 Vite `define` 在【编译期】注入为普通对象字面量，
// 应用代码只读它（绝不自行读取 import.meta / process）。详见 vite.config.js 顶部注释。
declare const __APP_ENV__: Record<string, string>;

// 让 TypeScript 认识 .vue 单文件组件
declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}

// @shared 别名指向仓库根 shared/ 下的单一数据源 JSON（与 Python 后端共用）
declare module "@shared/content.json" {
  const value: any;
  export default value;
}
declare module "@shared/school_graph.json" {
  const value: any;
  export default value;
}
declare module "@shared/domain_glossary.json" {
  const value: any;
  export default value;
}

// H5 部署后可在静态页注入运行时后端地址，无需重新构建（仅 H5 生效）
interface Window {
  __XUEFENG_API__?: string;
}
