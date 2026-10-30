"""Táxi de tráfego a partir do corte quebrável de um carro do acervo (Barão, 30/10/2026): uma malha estática só, branca (a pintura
fica com a textura de desgaste do corte, branco-tinta x oclusão), vidros escuros opacos (o material do acervo no jogo é opaco),
rodas do corte, a antena, e uma caixa de teto lisa de 62 x 22 x 13 cm sem texto no meio do teto (medido só na área do teto: o ponto
mais alto do carro é a ponta da antena). Reduz peça por peça até o alvo (no carro inteiro o colapso ligava peças soltas).

    python -I ferramentas/taxi_do_corte.py -- veiculos/sketchfab/quebravel/barao/barao.glb \
        veiculos/sketchfab/taxi-barao__0383ac51df544ef5ab97559f7a97a811.glb 90000

No Detonauto: Tools/Blender/export_acervo.py com esse arquivo (id taxi_barao) e Tools/Unreal/import_acervo.py --only taxi_barao.
"""
import bpy, bmesh, sys, numpy as np
from mathutils import Vector
a=sys.argv[sys.argv.index("--")+1:]; ent,out,alvo=a[0],a[1],int(a[2])
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=ent)
obs=[o for o in bpy.data.objects if o.type=="MESH"]
for o in obs:
    o.data.transform(o.matrix_world); o.matrix_world.identity()
for o in list(bpy.data.objects):
    if o.type!="MESH": bpy.data.objects.remove(o)
# materiais lisos do táxi; a pintura fica com a textura de desgaste (branco-tinta x oclusão)
cores={"vidro":(0.04,0.05,0.06,1),"chassi":(0.03,0.03,0.03,1),"MI_DNVao":(0.02,0.02,0.02,1),"pneu":(0.03,0.03,0.03,1),
       "cromado":(0.75,0.76,0.78,1),"cromo":(0.85,0.86,0.88,1),"refletor":(0.7,0.7,0.72,1),"lente_farol":(0.85,0.87,0.88,1),
       "luz":(0.75,0.05,0.04,1),"luz_vermelha":(0.7,0.03,0.03,1),"luz_ambar":(0.95,0.45,0.05,1),"luz_branca":(0.9,0.9,0.88,1),
       "placa":(0.92,0.92,0.9,1),"lampada":(0.9,0.9,0.85,1)}
for m in bpy.data.materials:
    base=m.name.split(".")[0]
    if base in cores and m.use_nodes:
        b=next((n for n in m.node_tree.nodes if n.type=="BSDF_PRINCIPLED"),None)
        if b:
            for l in list(b.inputs["Base Color"].links): m.node_tree.links.remove(l)
            b.inputs["Base Color"].default_value=cores[base]
            b.inputs["Metallic"].default_value=1.0 if base in ("cromado","cromo") else 0.0
            b.inputs["Roughness"].default_value=0.1 if base in ("vidro","cromo","cromado") else 0.5
# reduz peça por peça (no carro inteiro o colapso ligava peças soltas e deixava lâminas compridas no chão)
total=sum(len(o.data.polygons) for o in obs); razao=min(1.0,alvo/total)
for o in obs:
    if len(o.data.polygons)<200: continue
    bpy.context.view_layer.objects.active=o
    md=o.modifiers.new("d","DECIMATE"); md.ratio=razao; md.use_collapse_triangulate=True
    bpy.ops.object.modifier_apply(modifier="d")
bpy.ops.object.select_all(action="DESELECT")
for o in obs: o.select_set(True)
bpy.context.view_layer.objects.active=obs[0]; bpy.ops.object.join()
car=bpy.context.view_layer.objects.active; me=car.data
P=np.array([v.co for v in me.vertices]); teto=P[(np.abs(P[:,1])<0.4)&(P[:,0]>-1.1)&(P[:,0]<0.1)]; topo=teto[:,2].max()
# caixa de teto lisa, sem texto: 62 x 22 x 13 cm, no meio do teto
xs=teto[(teto[:,2]>topo-0.02),0]; xc=float((xs.min()+xs.max())/2)
bm=bmesh.new(); bmesh.ops.create_cube(bm,size=1.0)
for v in bm.verts: v.co=Vector((xc+v.co.x*0.22, v.co.y*0.62, topo-0.01+(v.co.z+0.5)*0.14))
mt=bpy.data.materials.new("caixa_teto"); mt.use_nodes=True
bb=mt.node_tree.nodes["Principled BSDF"]; bb.inputs["Base Color"].default_value=(0.9,0.9,0.88,1); bb.inputs["Roughness"].default_value=0.4
mc=bpy.data.meshes.new("caixa"); bm.to_mesh(mc); bm.free(); mc.materials.append(mt)
oc=bpy.data.objects.new("caixa",mc); bpy.context.scene.collection.objects.link(oc)
bpy.ops.object.select_all(action="DESELECT"); oc.select_set(True); car.select_set(True); bpy.context.view_layer.objects.active=car; bpy.ops.object.join()
car=bpy.context.view_layer.objects.active
n0=total
car.name=car.data.name="taxi_barao"
print("triangulos",n0,"->",len(car.data.polygons),"caixa em x",round(xc,3),"topo",round(topo,3))
bpy.ops.export_scene.gltf(filepath=out,export_format="GLB",export_image_format="JPEG")
