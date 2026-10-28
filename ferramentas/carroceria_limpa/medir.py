"""Mede a casca do Meshy por raios em grade de 1 cm, nas 4 vistas, e grava campos (altura + material + objeto) num .npz."""
import bpy, bmesh, sys, numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

a = sys.argv[sys.argv.index("--") + 1:]
ent, sai = a[0], a[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = [o for o in bpy.data.objects if o.type == "MESH"]
MATS = ["pintura", "vidro", "luz", "cromado", "pneu", "chassi", "MI_DNVao", "outro"]
bm = bmesh.new()
face_mat, face_obj = [], []
onames = [o.name for o in objs]
for o in objs:
    b = bmesh.new()
    b.from_mesh(o.data)
    b.transform(o.matrix_world)
    names = [s.material.name if s.material else "" for s in o.material_slots]
    mi = [MATS.index(n) if n in MATS else 7 for n in names]
    for f in b.faces:
        face_mat.append(mi[f.material_index] if f.material_index < len(mi) else 7)
        face_obj.append(onames.index(o.name))
    me = bpy.data.meshes.new("t")
    b.to_mesh(me)
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    b.free()
bvh = BVHTree.FromBMesh(bm)
face_mat = np.array(face_mat)
face_obj = np.array(face_obj)
C = 0.01
X = np.arange(-2.0, 2.0, C)
Y = np.arange(-0.9, 0.9, C)
Z = np.arange(0.0, 1.5, C)


def campo(U, V, origem, dirv):
    H = np.full((len(U), len(V)), np.nan)
    M = np.full((len(U), len(V)), -1, np.int8)
    O = np.full((len(U), len(V)), -1, np.int16)
    d = Vector(dirv)
    for i, u in enumerate(U):
        for j, v in enumerate(V):
            loc, n, idx, dist = bvh.ray_cast(Vector(origem(u, v)), d, 5.0)
            if loc is not None:
                H[i, j] = dist
                M[i, j] = face_mat[idx]
                O[i, j] = face_obj[idx]
    return H, M, O


out = {}
out["lado_h"], out["lado_m"], out["lado_o"] = campo(X, Z, lambda x, z: (x, 2.0, z), (0, -1, 0))      # y = 2 - h
out["topo_h"], out["topo_m"], out["topo_o"] = campo(X, Y, lambda x, y: (x, y, 2.5), (0, 0, -1))      # z = 2.5 - h
out["frente_h"], out["frente_m"], out["frente_o"] = campo(Y, Z, lambda y, z: (3.0, y, z), (-1, 0, 0))  # x = 3 - h
out["tras_h"], out["tras_m"], out["tras_o"] = campo(Y, Z, lambda y, z: (-3.0, y, z), (1, 0, 0))     # x = -3 + h
np.savez(sai, X=X, Y=Y, Z=Z, mats=np.array(MATS), objs=np.array(onames), **out)
print("ok", {k: int(np.isfinite(v).sum()) for k, v in out.items() if k.endswith("_h")})
