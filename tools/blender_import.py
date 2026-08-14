"""摄影棚布景 → Blender 重建（Cycles 出片通道）

用法（在项目根目录运行；--python-exit-code 1 必带——Blender 默认脚本崩溃也退出 0，
批处理会把上一轮的旧渲染当成功）：
  无头渲染:  blender --background --python-exit-code 1 --python tools/blender_import.py -- export/scene.json --render export/render.png
  只存工程:  blender --background --python-exit-code 1 --python tools/blender_import.py -- export/scene.json --blend export/scene.blend
  GUI 查看:  blender --python tools/blender_import.py -- export/scene.json
可选参数:  --samples 128   Cycles 采样数（默认 128，试渲可用 32）
          --res 2560      渲染横向分辨率（纵向按导出时画幅比自动算）

坐标约定（与 index.html exportBlenderScene 配套）：
  导出的矩阵是 three.js Y-up 右手世界系、列主序。换轴 C = Rx(+90°)，(x,y,z)_t → (x,-z,y)_b。
  glTF 导入器本身会把资产内容转成 Blender Z-up（content_b = C·content_gltf），
  因此集合实例的变换取 E = C·T_t·C⁻¹；相机无导入内容且 three/Blender 相机局部约定相同
  （-Z 朝前 +Y 朝上），直接 C·T_cam 不共轭。
"""
import bpy
import json
import math
import os
import sys
from mathutils import Matrix, Vector

# ── 参数 ──
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
JSON_PATH = argv[0] if argv and not argv[0].startswith('--') else os.path.join('export', 'scene.json')


def arg(name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


RENDER = arg('--render')
BLEND = arg('--blend')
SAMPLES = int(arg('--samples', '128'))
RES_X = int(arg('--res', '2560'))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isabs(JSON_PATH):
    JSON_PATH = os.path.join(ROOT, JSON_PATH)
with open(JSON_PATH, encoding='utf-8') as f:
    data = json.load(f)

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene

# ── 坐标换轴 ──
C = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
C_INV = C.inverted()


def three_mat(cols16):
    """three Matrix4.toArray()（列主序）→ mathutils.Matrix（行构造）"""
    return Matrix((
        (cols16[0], cols16[4], cols16[8], cols16[12]),
        (cols16[1], cols16[5], cols16[9], cols16[13]),
        (cols16[2], cols16[6], cols16[10], cols16[14]),
        (cols16[3], cols16[7], cols16[11], cols16[15]),
    ))


def _srgb_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hexc(s):
    """十六进制 sRGB → Blender 线性色（色槽都吃线性，直喂 sRGB 会亮一档——地面变雪地的教训）"""
    return tuple(_srgb_lin(int(s[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (1.0,)


# ── ① 地形（规则高度场网格，three 系行内 x 快变）──
terr = data.get('terrain')
if terr:
    n = terr['n']
    x0, z0, dx, dz = terr['x0'], terr['z0'], terr['dx'], terr['dz']
    hs = terr['heights']
    verts = [None] * (n * n)
    for i in range(n * n):
        xt = x0 + (i % n) * dx
        zt = z0 + (i // n) * dz
        verts[i] = (xt, -zt, hs[i])          # (x,y,z)_t → (x,-z,y)_b
    faces = []
    for r in range(n - 1):
        base = r * n
        for c in range(n - 1):
            a = base + c
            # 出三角而非四边形：Blender 对四边形的对角线剖分与 three PlaneGeometry 相反，
            # 28.6m 格距的起伏地形格内曲面会差 ±0.5m（虫脚浮/陷）。这两枚三角与 three 的
            # (0,1)-(1,0) 反对角线剖分逐面一致；绕向已按 z_t→-y_b 翻转补偿（法线 +Z 朝天）
            faces.append((a, a + n, a + 1))
            faces.append((a + n, a + n + 1, a + 1))
    me = bpy.data.meshes.new('terrain')
    me.from_pydata(verts, [], faces)
    me.validate()
    mt = bpy.data.materials.new('terrain')
    mt.use_nodes = True
    # 按类型找节点：按名找在非英文界面开了"翻译新数据名"的机器上会拿到 None
    bsdf = next(nd for nd in mt.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = hexc(terr.get('color', '4d4a43'))
    bsdf.inputs['Roughness'].default_value = float(terr.get('roughness', 1))
    me.materials.append(mt)
    ob = bpy.data.objects.new('terrain', me)
    scn.collection.objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    print('TERRAIN_OK verts=%d' % (n * n))

# ── ② GLB 资产：每种导入一次进独立集合，摆放全用集合实例（Cycles 自动实例化省显存）──
_asset_cols = {}


def get_asset(src):
    if src in _asset_cols:
        return _asset_cols[src]
    path = os.path.join(ROOT, src.split('?')[0].replace('/', os.sep))
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception:
        # 半途失败（GLB 损坏/外链缺失）会留下已链接的残件挂在资产原点，清掉再抛
        for o in [o for o in bpy.data.objects if o not in before]:
            for c in list(o.users_collection):
                c.objects.unlink(o)
        raise
    new = [o for o in bpy.data.objects if o not in before]
    # 按实时端渲染名单剪掉 GLB 内嵌杂物（如 Tripo 模型自带的 Icosphere 背景球——
    # 摄影棚的角色克隆管线只取骨架+蒙皮体，原始 GLB 里的球会在 Cycles 里凭空出现挡镜头）。
    # 仅当名单与导入对象命名体系对得上（至少一个名字匹配）才敢剪，防止两边命名不一致时误删正身
    wl = (data.get('meshes') or {}).get(src)
    if wl:
        wl_set = set(n.split('.')[0] for n in wl if n)
        meshes_new = [o for o in new if o.type == 'MESH']
        # 对象名或网格数据名任一命中都算匹配（Tripo 的 node/mesh 前缀两边可能不一致）
        def names_of(o):
            ns = {o.name.split('.')[0]}
            if o.data:
                ns.add(o.data.name.split('.')[0])
            return ns
        matched = [o for o in meshes_new if names_of(o) & wl_set]
        if matched:   # 命名体系对得上才敢剪，防止不一致时误删正身
            for o in [o for o in meshes_new if not (names_of(o) & wl_set)]:
                print('PRUNE %s: %s（实时端不渲染的内嵌网格）' % (src, o.name))
                new.remove(o)
                bpy.data.objects.remove(o, do_unlink=True)
    # 源集合刻意不挂进场景树：未链接集合不参与渲染但可被实例引用（实例 empty 即用户，不会被清理）。
    # 不能用 hide_render 藏原件——集合的隐藏标志会连同它的全部实例一起藏掉
    col = bpy.data.collections.new('A_' + os.path.basename(src))
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        col.objects.link(o)
    _asset_cols[src] = col
    print('ASSET_OK %s objs=%d' % (src, len(new)))
    return col


_failed = set()


def place(src, m16, name='inst'):
    if src in _failed:
        return
    try:
        col = get_asset(src)
    except Exception as ex:
        _failed.add(src)
        print('ASSET_FAIL %s: %s' % (src, ex))   # 单件资产缺失/损坏只丢该类，不整锅端
        return
    e = bpy.data.objects.new(name, None)
    e.instance_type = 'COLLECTION'
    e.instance_collection = col
    e.matrix_world = C @ three_mat(m16) @ C_INV
    scn.collection.objects.link(e)


for it in data.get('items', []):
    place(it['src'], it['m'])
print('ITEMS_OK count=%d' % len(data.get('items', [])))

for pop in data.get('pops', []):
    for i, m16 in enumerate(pop['ms']):
        place(pop['src'], m16, 'pop%d' % i)
    print('POP_OK %s count=%d' % (pop['src'], pop['count']))

# ── ③ 日光 + 环境 ──
sun_d = data.get('sun')
if sun_d:
    li = bpy.data.lights.new('Sun', 'SUN')
    li.energy = 4.0                      # Cycles 太阳辐照度基线（W/m²），亮度不匹配就调这里
    li.angle = math.radians(0.53)        # 真实太阳视直径 → 距离越远半影越宽（实时端做不到的正确软影）
    li.color = hexc(sun_d.get('color', 'ffffff'))[:3]
    sun = bpy.data.objects.new('Sun', li)
    dir_t = (Vector(sun_d['tgt']) - Vector(sun_d['pos'])).normalized()
    dir_b = (C.to_3x3() @ dir_t).normalized()
    sun.rotation_mode = 'QUATERNION'
    sun.rotation_quaternion = Vector((0, 0, -1)).rotation_difference(dir_b)
    scn.collection.objects.link(sun)

env = data.get('env', {})
w = bpy.data.worlds.new('World')
scn.world = w
w.use_nodes = True
bg = next(nd for nd in w.node_tree.nodes if nd.type == 'BACKGROUND')
bg.inputs['Color'].default_value = hexc(env.get('hemiSky', '9fb0b5'))
bg.inputs['Strength'].default_value = 0.4    # 冷调天光托底（对应实时端 hemi），过亮会洗掉日照反差

# ── ④ 相机 ──
cam_d = data['camera']
cd = bpy.data.cameras.new('Cam')
cd.sensor_fit = 'VERTICAL'
cd.angle_y = math.radians(cam_d['fov'])      # three fov = 垂直视场角
cd.clip_start = 0.1
cd.clip_end = 40000
cam = bpy.data.objects.new('Cam', cd)
cam.matrix_world = C @ three_mat(cam_d['m'])
scn.collection.objects.link(cam)
scn.camera = cam

# ── ⑤ Cycles 渲染配置 ──
scn.render.engine = 'CYCLES'
scn.cycles.samples = SAMPLES
scn.cycles.use_denoising = True
scn.render.resolution_x = RES_X
scn.render.resolution_y = round(RES_X / cam_d.get('aspect', 16 / 9))
try:
    scn.view_settings.view_transform = 'AgX'     # 电影级色调映射，高光滚降接近实时端调色气质
except Exception:
    pass
prefs = bpy.context.preferences.addons.get('cycles')
if prefs:
    cp = prefs.preferences
    for dt in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            cp.compute_device_type = dt
            cp.get_devices()
            gpus = [d for d in cp.devices if d.type == dt]
            if gpus:
                for d in cp.devices:
                    d.use = True
                scn.cycles.device = 'GPU'
                print('GPU_OK ' + dt)
                break
        except Exception:
            continue

if BLEND:
    bp = BLEND if os.path.isabs(BLEND) else os.path.join(ROOT, BLEND)
    os.makedirs(os.path.dirname(bp), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=bp)
    print('BLEND_OK ' + bp)

if RENDER:
    rp = RENDER if os.path.isabs(RENDER) else os.path.join(ROOT, RENDER)
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    scn.render.filepath = rp
    scn.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)
    print('RENDER_OK ' + rp)

print('IMPORT_DONE items=%d pops=%d' % (
    len(data.get('items', [])), sum(p['count'] for p in data.get('pops', []))))
