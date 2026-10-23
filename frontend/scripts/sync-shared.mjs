// 同步根 shared/ 的内容 JSON 到 frontend/src/shared/。
//
// 为什么需要这一步：小程序编译器不认项目外目录，前端依赖的内容 JSON 必须放在
// frontend 项目内（src/shared/）才能被 mp-weixin 编译打包。根 shared/ 仍是与 Python
// 后端共用的单一真源，本脚本负责在构建 / 更新内容时把最新数据同步进前端。
//
// 用法：cd frontend && npm run sync:shared
import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.cwd(), '..', 'shared');
const dst = path.resolve(process.cwd(), 'src', 'shared');
mkdirSync(dst, { recursive: true });

const files = ['content.json', 'school_graph.json', 'domain_glossary.json'];
let synced = 0;
for (const f of files) {
  const src = path.join(root, f);
  if (!existsSync(src)) {
    console.warn('[skip] 缺少源文件:', src);
    continue;
  }
  copyFileSync(src, path.join(dst, f));
  synced++;
  console.log('[ok] 同步', f);
}
console.log(`完成：已同步 ${synced}/${files.length} 个文件 → src/shared/`);
