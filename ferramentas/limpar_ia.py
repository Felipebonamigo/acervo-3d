"""Limpeza de modelo gerado por IA (Meshy, TripoSG) ou baixado, antes de entrar num jogo.

Roda dentro do Blender, sem janela:
  blender -b -P ferramentas/limpar_ia.py -- --entrada x.glb --saida y.glb --altura 2.4 [--frente +x|-x|+y|-y]
          [--lods 0.5,0.25] [--fbx] [--sem-soltos] [--juntar]
Ou com o módulo bpy instalado no Python:  python -m ferramentas.limpar_ia -- ... (mesmos argumentos)

O que faz, nesta ordem:
  1. importa o GLB/FBX/OBJ e junta tudo num objeto (--juntar, padrão) ou mantém as partes;
  2. aplica rotação e escala; escala pela altura real em metros (--altura) ou pela maior medida (--maior);
  3. remove vértices duplicados e, com --sem-soltos, as ilhas com menos de 0,5 % dos vértices (lixo do gerador);
  4. põe o pivô no centro da base (chão em z = 0) e vira a frente para +X, o do Unreal (--frente diz para onde ela
     aponta no arquivo de entrada; use -x num modelo que chegou de traseira para +X);
  5. gera LODs por Decimate (colapso, UVs preservadas aproximadamente) nas razões de --lods;
  6. exporta GLB (e FBX com --fbx) com o nome de saída; LODs como <saida>_LOD1.glb etc.
Não faz remesh nem bake: o Meshy já entrega malha remalhada com UV e PBR; malha crua do TripoSG (sem UV) precisa
de retopologia e bake antes, à mão ou num passo próprio.
Checagem: a saída imprime medidas, triângulos e número de materiais; confira num cubo de 1 m no motor.
"""
import sys, math, argparse, os

try:
    import bpy, bmesh
    from mathutils import Vector
except ImportError:  # fora do Blender
    print("este script roda dentro do Blender (blender -b -P ...) ou com o módulo bpy instalado"); sys.exit(2)

def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--entrada", required=True); p.add_argument("--saida", required=True)
    p.add_argument("--altura", type=float, help="altura real em metros (eixo Z depois de importar)")
    p.add_argument("--maior", type=float, help="maior medida real em metros, se a altura não for a referência")
    p.add_argument("--frente", default="+x", choices=["+x", "-x", "+y", "-y"])
    p.add_argument("--lods", default="", help="razões de faces, ex. 0.5,0.25")
    p.add_argument("--fbx", action="store_true"); p.add_argument("--sem-soltos", action="store_true")
    p.add_argument("--juntar", action="store_true", default=True); p.add_argument("--separado", action="store_true")
    return p.parse_args(argv)

def importar(caminho):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = os.path.splitext(caminho)[1].lower()
    if ext in (".glb", ".gltf"): bpy.ops.import_scene.gltf(filepath=caminho)
    elif ext == ".fbx": bpy.ops.import_scene.fbx(filepath=caminho)
    elif ext == ".obj": bpy.ops.wm.obj_import(filepath=caminho)
    else: raise SystemExit("formato não suportado: " + ext)
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]

def juntar(malhas):
    bpy.ops.object.select_all(action="DESELECT")
    for o in malhas: o.select_set(True)
    bpy.context.view_layer.objects.active = malhas[0]
    if len(malhas) > 1: bpy.ops.object.join()
    return bpy.context.view_layer.objects.active

def medidas(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx

def main():
    a = args()
    malhas = importar(a.entrada)
    if not malhas: raise SystemExit("nenhuma malha em " + a.entrada)
    # pais vazios do glTF: aplica a transformação do mundo em cada malha antes de juntar
    for o in malhas:
        o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    obj = juntar(malhas) if not a.separado else malhas[0]
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    mn, mx = medidas(obj); tam = mx - mn
    fator = 1.0
    if a.altura: fator = a.altura / tam.z
    elif a.maior: fator = a.maior / max(tam.x, tam.y, tam.z)
    if abs(fator - 1.0) > 1e-6:
        obj.scale = (fator, fator, fator); bpy.ops.object.transform_apply(scale=True)
    # limpeza da malha
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    if a.sem_soltos:
        bm.verts.ensure_lookup_table()
        total = len(bm.verts); visto = set(); ilhas = []
        for v in bm.verts:
            if v.index in visto: continue
            pilha = [v]; ilha = []
            while pilha:
                w = pilha.pop()
                if w.index in visto: continue
                visto.add(w.index); ilha.append(w)
                pilha.extend(e.other_vert(w) for e in w.link_edges)
            ilhas.append(ilha)
        lixo = [v for ilha in ilhas if len(ilha) < 0.005 * total for v in ilha]
        if lixo: bmesh.ops.delete(bm, geom=lixo, context="VERTS"); print(f"ilhas soltas removidas: {sum(1 for i in ilhas if len(i) < 0.005 * total)}")
    bm.to_mesh(obj.data); bm.free()
    # frente: --frente diz para onde a frente do modelo aponta como ele chegou; o script gira até +X (o do Unreal).
    # Antes de 23/10/2026 este giro não fazia nada (o importador do
    # glTF deixa a rotação em quaternion e o ângulo era ignorado), por isso o padrão +x não gira. Os carros do Meshy
    # (multi-image-to-3d) chegam com a frente em -X: use --frente=-x neles.
    giro = {"+x": 0, "-x": 180, "+y": -90, "-y": 90}[a.frente]
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0, 0, math.radians(giro)); bpy.ops.object.transform_apply(rotation=True)
    # pivô no centro da base
    mn, mx = medidas(obj)
    centro = Vector(((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, mn.z))
    obj.data.transform(__import__("mathutils").Matrix.Translation(-centro)); obj.location = (0, 0, 0)
    mn, mx = medidas(obj); tam = mx - mn
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    print(f"[limpar_ia] {os.path.basename(a.entrada)}: {tam.x:.2f} x {tam.y:.2f} x {tam.z:.2f} m, {tris} triângulos, {len(obj.data.materials)} materiais, frente {a.frente}")
    base, ext = os.path.splitext(a.saida)
    def exportar(o, caminho):
        bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.export_scene.gltf(filepath=caminho, use_selection=True, export_format="GLB", export_apply=True)
        if a.fbx: bpy.ops.export_scene.fbx(filepath=os.path.splitext(caminho)[0] + ".fbx", use_selection=True, apply_scale_options="FBX_SCALE_ALL")
        print("exportado:", caminho)
    obj.name = os.path.basename(base); exportar(obj, base + ".glb")
    for i, razao in enumerate([float(x) for x in a.lods.split(",") if x.strip()], start=1):
        lod = obj.copy(); lod.data = obj.data.copy(); bpy.context.scene.collection.objects.link(lod)
        lod.name = f"{obj.name}_LOD{i}"
        mod = lod.modifiers.new("decimate", "DECIMATE"); mod.ratio = razao
        bpy.context.view_layer.objects.active = lod; bpy.ops.object.modifier_apply(modifier="decimate")
        exportar(lod, f"{base}_LOD{i}.glb")

main()
