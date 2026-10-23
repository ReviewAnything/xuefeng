// 全局类型声明（全量 TS 阶段）
// ---------------------------------------------------------------------------
// __APP_ENV__ 由 vite.config.ts 经 Vite `define` 在【编译期】注入为普通对象字面量，
// 应用代码只读它（绝不自行读取 import.meta / process）。详见 vite.config.ts 顶部注释。
declare const __APP_ENV__: Record<string, string>;

// 让 TypeScript 认识 .vue 单文件组件
declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}

// 内容数据 JSON 置于项目内 src/shared/，由 `npm run sync:shared` 从根 shared/ 同步。
// 小程序编译器只认项目内目录，故不在此声明外部 @shared 别名。
declare module "*.json" {
  const value: any;
  export default value;
}

// H5 部署后可在静态页注入运行时后端地址，无需重新构建（仅 H5 生效）
interface Window {
  __XUEFENG_API__?: string;
}
