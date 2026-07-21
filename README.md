# WH40K 场景摄影棚 · Grimdark Scene Studio

战锤40K AI 视频（《Life of an Astartes》第一人称 POV）的 **3D 场景一致性工具**：
用 Three.js 搭建可复用的实景棚，锁定环境/光照/机位，为 Higgsfield / 即梦 图生视频提供一致的场景参考帧。

## 运行

```
python serve.py
```

浏览器打开 **http://127.0.0.1:8943**（务必用这个地址——localStorage 按源隔离，换 localhost 会看不到已存布局）。
或直接双击 `启动摄影棚.bat`。

## 功能速览

- 5 个场景：哥特大教堂 / 蜂巢城废墟 / 轨道船坞 / 星舰内廊 / 混沌废土
- 第一人称（双 FPS 武器）/ 第三人称极限战士（GLB 蒙皮，A-pose 自动雕塑）
- 造景模式：角色 / 敌对角色（含 220m 虫族母舰）/ 建筑物 / 地面铁板（嵌入式贴面，可走上走下）
- 一键按钮：蜂巢布景 · 一键铺城（20m 随机混拼铁板）· 大军压城 · 清空铁板
- BVH 贴面碰撞 + 桥洞穿行 + 站墙顶；Spring Arm 相机；机位收藏；2K 截图（POST /save）
- 布局云备份：浏览器 localStorage 每 10s 自动落盘 `layouts/backup.json`，清缓存/换浏览器自动恢复

## 目录

| 路径 | 说明 |
| --- | --- |
| `index.html` | 全部应用代码（单文件） |
| `serve.py` | 静态服务 + 截图/布局落盘接口 |
| `assets/` | 运行用 GLB（已 gltfpack 减面）；`orig_hi/` 高模原件不入库 |
| `layouts/` | 浏览器存档的磁盘备份（布局/机位收藏等，随 git 云备份） |
