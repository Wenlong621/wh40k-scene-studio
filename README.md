# WH40K 场景摄影棚 · Grimdark Scene Studio

战锤40K AI 视频（《Life of an Astartes》第一人称 POV）的 **3D 场景一致性工具**：
用 Three.js 搭建可复用的实景棚，锁定环境 / 光照 / 机位，为 Higgsfield / 即梦等图生视频工具
提供一致的场景参考帧；并可一键导出到 Blender 走 Cycles 路径追踪出电影级英雄帧。

## 使用（云端为主）

**日常造景直接用云端版：<https://wenlong621.github.io/wh40k-scene-studio/>**
（布局、机位收藏等存在浏览器 localStorage，请固定用同一浏览器访问）

本地运行（可选，开发/调试用）：

```
python serve.py
```

浏览器打开 http://127.0.0.1:8943，或双击 `启动摄影棚.bat`。

## 功能速览

- **5 个场景**：哥特大教堂 / 蜂巢城废墟（主力）/ 轨道船坞 / 星舰内廊 / 混沌废土
- **视角**：自由视角 · 第一人称（双 FPS 武器，可调机位）· 第三人称（Spring Arm 吊臂 + 贴墙自动收杆，主角下三分构图）
- **造景模式**：建筑物（教堂/要塞/塔楼/村落/雕像/桥梁等 40+ 件）· 建筑物细节（立面/拱门/环形露台等贴装件）·
  角色 / 敌对角色（虫族全家桶 + 220m 母舰）/ 我方星界军 · 地面铁板 · 体积云
  - 全套操作：旋转 / 缩放（建筑最高 **100×**）/ 悬浮（最高 **10000m**）/ 复制 / 移动 / 撤销；数值可点击直接输入
  - 全部资产带 **BVH 贴面碰撞**（走桥面、穿拱洞、上台阶、站墙顶）
- **一键军团**：虫群压城 · 分股攻势 · 虫潮蛇阵（GPU 实例化蛇形纵队）· 骸骨龙群（天空乱流虫云）
- **打光双模式**（一键切换，记忆选择）：🎬 摄影棚（无影均匀，摆景/看细节）· ☀ 电影日光（硬影反差，出情绪片）
- **画面**：暖调高饱和电影调色（历版参数备档注释内）· 全高度空气雾（千米巨构同层入雾，浓度滑杆可调）·
  辉光 / 颗粒 / 暗角后期 · 16:9 / 9:16 / 21:9 画幅
- **出帧**：📷 2K 截图 · 🎬 录像模式 · 📋 场景 Scene-Lock 提示词一键复制 · 机位收藏（多帧构图一致）

## Blender 出片通道（Cycles 电影级渲染）

1. 摆好景、走到机位，点 **「🎥 导出 Blender 布景」**（云端版直接下载 `scene.json`）
2. 本机项目根目录执行：

```
blender --background --python-exit-code 1 --python tools/blender_import.py -- <scene.json路径> --render export/render.png --samples 128 --res 2560
```

同一机位以路径追踪重渲：真实软影 / 全局光 / 太阳半影，另含默认开启的
**星际星野天幕、全高度体积雾、大雨**（`--sky grey` / `--fog off` / `--rain off` 可关）。
加 `--blend export/scene.blend` 可存工程文件双击进 Blender 手动调整。

## 存档与备份（重要）

- 布局只存在浏览器 localStorage —— **定期点「💾 下载布局备份」**，文件入库 `layouts/` 即成云端备份；
  页面启动会自动从 `layouts/backup.json` 恢复缺失存档（清缓存 / 换浏览器 / 换电脑均可找回）
- 「📂 导入布局备份」可从任意备份文件手动恢复
- 高模原件（每件 ~55MB）归档在 GitHub Release **assets-archive**；仓库内 `assets/` 为 gltfpack 精简版（~360-390k 面/件）

## 目录

| 路径 | 说明 |
| --- | --- |
| `index.html` | 全部应用代码（单文件） |
| `serve.py` | 本地静态服务 + 截图 / 布局落盘 / Blender 导出接口 |
| `tools/blender_import.py` | Blender 布景重建 + Cycles 渲染脚本 |
| `assets/` | 运行用 GLB（gltfpack 减面）；`orig_hi/` 高模原件不入库（见 Release） |
| `layouts/` | 浏览器存档备份（布局 / 机位等，随 git 云备份） |
| `export/` | Blender 导出与渲染产物（不入库） |
