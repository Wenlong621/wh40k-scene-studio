"""摄影棚布景 → Blender 重建（Cycles 出片通道）

用法（在项目根目录运行；--python-exit-code 1 必带——Blender 默认脚本崩溃也退出 0，
批处理会把上一轮的旧渲染当成功）：
  无头渲染:  blender --background --python-exit-code 1 --python tools/blender_import.py -- export/scene.json --render export/render.png
  只存工程:  blender --background --python-exit-code 1 --python tools/blender_import.py -- export/scene.json --blend export/scene.blend
  GUI 查看:  blender --python tools/blender_import.py -- export/scene.json
可选参数:  --samples 128   Cycles 采样数（默认 128，试渲可用 32）
          --res 2560      渲染横向分辨率（纵向按导出时画幅比自动算）
          --sky stars     天幕：stars=星际星野+暗星云（默认）/ grey=纯色天光
          --fog 0.0008    体积雾密度（默认 0.0008，off 关闭）
          --rain 12000    雨丝数量（默认 12000，off 关闭；只铺在相机视锥内）

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
SKY = arg('--sky', 'stars')
FOG = arg('--fog', '0.0008')
RAIN = arg('--rain', '12000')

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
    if SKY == 'stars':                   # 星际夜幕下改冷调苍白主光（雨夜钢灰质感），暖阳会穿帮
        li.energy = 3.6
        li.color = (0.80, 0.85, 0.95)
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
nt = w.node_tree
bg = next(nd for nd in nt.nodes if nd.type == 'BACKGROUND')
if SKY == 'stars':
    # ── 星际天幕：程序化星野 + 暗星云 + 地平线雾霭（纯节点，无外部贴图）──
    # 颜色运算全部用 VectorMath/Math 组合（避开 ShaderNodeMix 多类型插槽的按名取坑）
    tex = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(tex.outputs['Generated'], sep.inputs['Vector'])
    # 星点：高频 Voronoi 距离场取尖峰；每颗星亮度=细胞随机色 BW^8（少数亮星、多数暗星）
    vor = nt.nodes.new('ShaderNodeTexVoronoi')
    vor.inputs['Scale'].default_value = 30.0    # 星距≈1/S rad≈2°；首版 320 星径仅 0.002° 亚像素不可见
    nt.links.new(tex.outputs['Generated'], vor.inputs['Vector'])
    less = nt.nodes.new('ShaderNodeMath'); less.operation = 'LESS_THAN'
    less.inputs[1].default_value = 0.045        # 星径≈t/S≈0.086°≈1-2px@2560
    nt.links.new(vor.outputs['Distance'], less.inputs[0])
    bwn = nt.nodes.new('ShaderNodeRGBToBW')
    nt.links.new(vor.outputs['Color'], bwn.inputs['Color'])
    powr = nt.nodes.new('ShaderNodeMath'); powr.operation = 'POWER'
    powr.inputs[1].default_value = 8.0
    nt.links.new(bwn.outputs['Val'], powr.inputs[0])
    star = nt.nodes.new('ShaderNodeMath'); star.operation = 'MULTIPLY'
    nt.links.new(less.outputs['Value'], star.inputs[0])
    nt.links.new(powr.outputs['Value'], star.inputs[1])
    starv = nt.nodes.new('ShaderNodeVectorMath'); starv.operation = 'SCALE'
    starv.inputs[0].default_value = (11.0, 12.2, 14.0)   # 星点冷白偏蓝，标量增益乘进去（雾会吃掉一档亮度）
    nt.links.new(star.outputs['Value'], starv.inputs['Scale'])
    # 暗星云底色
    noi = nt.nodes.new('ShaderNodeTexNoise')
    noi.inputs['Scale'].default_value = 2.2
    noi.inputs['Detail'].default_value = 6.0
    nt.links.new(tex.outputs['Generated'], noi.inputs['Vector'])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.004, 0.006, 0.012, 1)
    ramp.color_ramp.elements[1].position = 0.78
    ramp.color_ramp.elements[1].color = (0.030, 0.046, 0.078, 1)
    nt.links.new(noi.outputs['Fac'], ramp.inputs['Fac'])
    skyc = nt.nodes.new('ShaderNodeVectorMath'); skyc.operation = 'ADD'
    nt.links.new(ramp.outputs['Color'], skyc.inputs[0])
    nt.links.new(starv.outputs['Vector'], skyc.inputs[1])
    # 地平线雾霭：|Z| 越小越混入冷灰霭（呼应场景体积雾），星野只在高仰角清晰
    absz = nt.nodes.new('ShaderNodeMath'); absz.operation = 'ABSOLUTE'
    nt.links.new(sep.outputs['Z'], absz.inputs[0])
    hfac = nt.nodes.new('ShaderNodeMapRange')
    hfac.inputs['From Min'].default_value = 0.02
    hfac.inputs['From Max'].default_value = 0.14   # 霭带压窄：平视机位的天空带也要见到星
    hfac.inputs['To Min'].default_value = 1.0
    hfac.inputs['To Max'].default_value = 0.0
    nt.links.new(absz.outputs['Value'], hfac.inputs['Value'])
    inv = nt.nodes.new('ShaderNodeMath'); inv.operation = 'SUBTRACT'
    inv.inputs[0].default_value = 1.0
    nt.links.new(hfac.outputs['Result'], inv.inputs[1])
    sky_s = nt.nodes.new('ShaderNodeVectorMath'); sky_s.operation = 'SCALE'
    nt.links.new(skyc.outputs['Vector'], sky_s.inputs[0])
    nt.links.new(inv.outputs['Value'], sky_s.inputs['Scale'])
    haze = nt.nodes.new('ShaderNodeVectorMath'); haze.operation = 'SCALE'
    haze.inputs[0].default_value = (0.055, 0.068, 0.085)   # 地平线冷灰霭
    nt.links.new(hfac.outputs['Result'], haze.inputs['Scale'])
    fin = nt.nodes.new('ShaderNodeVectorMath'); fin.operation = 'ADD'
    nt.links.new(sky_s.outputs['Vector'], fin.inputs[0])
    nt.links.new(haze.outputs['Vector'], fin.inputs[1])
    nt.links.new(fin.outputs['Vector'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0
else:
    bg.inputs['Color'].default_value = hexc(env.get('hemiSky', '9fb0b5'))
    bg.inputs['Strength'].default_value = 0.4   # 冷调天光托底（对应实时端 hemi），过亮会洗掉日照反差

# ── 体积雾：限高雾箱（不用世界体积——那会把星空也糊掉）──
if FOG != 'off':
    import bmesh
    fdens = float(FOG)
    fme = bpy.data.meshes.new('fogbox')
    fbm = bmesh.new()
    bmesh.ops.create_cube(fbm, size=1.0)
    fbm.to_mesh(fme)
    fbm.free()
    fog_ob = bpy.data.objects.new('fog', fme)
    fog_ob.scale = (16000, 16000, 450)
    fog_ob.location = (0, 0, 225)
    fmat = bpy.data.materials.new('fog')
    fmat.use_nodes = True
    fnt = fmat.node_tree
    for nd in [n for n in fnt.nodes if n.type == 'BSDF_PRINCIPLED']:
        fnt.nodes.remove(nd)
    vol = fnt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Density'].default_value = fdens
    vol.inputs['Anisotropy'].default_value = 0.35
    vol.inputs['Color'].default_value = (0.65, 0.72, 0.80, 1)
    fout = next(nd for nd in fnt.nodes if nd.type == 'OUTPUT_MATERIAL')
    fnt.links.new(vol.outputs['Volume'], fout.inputs['Volume'])
    fme.materials.append(fmat)
    scn.collection.objects.link(fog_ob)
    print('FOG_OK density=%s' % fdens)

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

# ── 大雨：相机视锥内撒雨丝面片（细长四边形=雨滴运动模糊后的拉丝；统一风向微抖动）──
if RAIN != 'off':
    import random
    rnd = random.Random(40000)   # 定种子：同一布景重渲雨形不变
    n_rain = int(RAIN)
    cam_q = cam.matrix_world.to_quaternion()
    r_fwd = cam_q @ Vector((0, 0, -1))
    r_rgt = cam_q @ Vector((1, 0, 0))
    r_up = cam_q @ Vector((0, 1, 0))
    r_org = cam.matrix_world.translation
    wind = Vector((0.22, 0.10, -1.0)).normalized()
    verts, faces = [], []
    for i in range(n_rain):
        dd = 4.0 + rnd.random() * 130.0                   # 均匀分布：近处不能挤成白栅栏（首版教训）
        spread = dd * 0.75 + 2.0
        p = (r_org + r_fwd * dd
             + r_rgt * ((rnd.random() * 2 - 1) * spread)
             + r_up * ((rnd.random() * 2 - 1) * spread * 0.6))
        L = 0.30 + rnd.random() * 0.50
        wj = Vector((wind.x + (rnd.random() - 0.5) * 0.06,
                     wind.y + (rnd.random() - 0.5) * 0.06, wind.z)).normalized()
        wd = 0.0035 + rnd.random() * 0.0045               # 半宽 3.5-8mm：真实雨丝是 1-3px 的淡痕
        side = wj.cross((p - r_org).normalized())
        if side.length < 1e-6:
            side = r_rgt.copy()
        side = side.normalized() * wd
        base = len(verts)
        verts += [tuple(p - side), tuple(p + side), tuple(p + side + wj * L), tuple(p - side + wj * L)]
        faces.append((base, base + 1, base + 2, base + 3))
    rme = bpy.data.meshes.new('rain')
    rme.from_pydata(verts, [], faces)
    rme.validate()
    rmat = bpy.data.materials.new('rain')
    rmat.use_nodes = True
    rnt = rmat.node_tree
    for nd in [x for x in rnt.nodes if x.type == 'BSDF_PRINCIPLED']:
        rnt.nodes.remove(nd)
    rtrans = rnt.nodes.new('ShaderNodeBsdfTransparent')
    remit = rnt.nodes.new('ShaderNodeEmission')
    remit.inputs['Color'].default_value = (0.75, 0.82, 0.95, 1)
    remit.inputs['Strength'].default_value = 1.6
    rmix = rnt.nodes.new('ShaderNodeMixShader')
    rmix.inputs['Fac'].default_value = 0.09   # 大部分透明+一点自发光=暗背景上可读的雨丝
    rout = next(nd for nd in rnt.nodes if nd.type == 'OUTPUT_MATERIAL')
    rnt.links.new(rtrans.outputs['BSDF'], rmix.inputs[1])
    rnt.links.new(remit.outputs['Emission'], rmix.inputs[2])
    rnt.links.new(rmix.outputs['Shader'], rout.inputs['Surface'])
    rme.materials.append(rmat)
    rain_ob = bpy.data.objects.new('rain', rme)
    scn.collection.objects.link(rain_ob)
    print('RAIN_OK count=%d' % n_rain)

# ── ⑤ Cycles 渲染配置 ──
scn.render.engine = 'CYCLES'
scn.cycles.samples = SAMPLES
scn.cycles.use_denoising = True
scn.cycles.transparent_max_bounces = 24   # 雨丝多层透明面片叠深，默认 8 会出黑块
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
