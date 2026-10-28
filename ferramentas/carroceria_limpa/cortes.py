"""
Cortes dos painéis na carroceria limpa (bmesh): portas, capô, para-lamas dianteiros e tampa traseira, por planos
(bisect) limitados a uma região; depois cada peça vira um objeto, a borda do corte recua meia fresta e ganha uma aba
escura para dentro (a fresta aparece como vão preto, como num carro de verdade).

As funções recebem o objeto "body" montado pela malha.py e os dados do corpo.npz.
"""
import numpy as np
import bpy
import bmesh
from mathutils import Vector

FRESTA = 0.004       # vão total entre painéis
ABA = 0.012          # aba para dentro na borda do corte


def _geom_na_caixa(bm, caixa, normal=None):
    """Faces cuja caixa envolvente cruza a caixa dada (o centro só não basta: um triângulo comprido da costura passa por fora)."""
    x0, x1, y0, y1, z0, z1 = caixa
    faces = []
    for f in bm.faces:
        xs = [v.co.x for v in f.verts]
        ys = [v.co.y for v in f.verts]
        zs = [v.co.z for v in f.verts]
        if max(xs) >= x0 and min(xs) <= x1 and max(ys) >= y0 and min(ys) <= y1 and max(zs) >= z0 and min(zs) <= z1 \
                and (normal is None or normal(f.normal)):
            faces.append(f)
    verts = set(v for f in faces for v in f.verts)
    edges = set(e for f in faces for e in f.edges)
    return list(verts) + list(edges) + faces


def cortar_plano(bm, co, no, caixa, marca, normal=None):
    """Bisseta as faces da caixa (e com a normal aceita) pelo plano (co, no); as arestas novas levam a marca."""
    geom = _geom_na_caixa(bm, caixa, normal)
    if not geom:
        return 0
    r = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=Vector(co), plane_no=Vector(no).normalized())
    n = 0
    for g in r["geom_cut"]:
        if isinstance(g, bmesh.types.BMEdge):
            g[marca] = 1
            n += 1
    print("    corte", np.round(co, 3), np.round(no, 2), "faces", len([g for g in geom if isinstance(g, bmesh.types.BMFace)]), "arestas", n)
    return n


def cortar(ob, d):
    """Todos os cortes do hatch de 2 portas; devolve o bmesh cortado (ainda um objeto só) com as arestas de corte marcadas."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    marca = bm.edges.layers.int.new("corte")
    zw_a, zw_b = d["zw"]
    z_belt = float(zw_a * 0.0 + zw_b)
    x_cowl, x_rg_top = float(d["x_cowl"]), float(d["x_rg_top"])
    x_bico, x_rabo = float(d["x_bico"]), float(d["x_rabo"])
    xd0, xd1 = [float(v) for v in d["door_x"]]
    y_capo = float(d["y_capo"])
    y_tampa, z_tampa, z_ombro = 0.60, 0.52, 0.86
    # contorno da janela da porta: a frente do quadro da porta sobe paralela à coluna A
    jan = d["janela_porta"] if "janela_porta" in d else None
    big = 9.0
    n = 0
    for s in (1, -1):
        # porta: traseira vertical na coluna B, do fundo até a borda do teto
        n += cortar_plano(bm, (xd0, 0, 0), (1, 0, 0), (xd0 - 0.1, xd0 + 0.1, 0.3 * s if s > 0 else -big, big if s > 0 else -0.3, 0.0, 1.45), marca)
        # porta: frente vertical até a cintura
        n += cortar_plano(bm, (xd1, 0, 0), (1, 0, 0), (xd1 - 0.1, xd1 + 0.1, 0.3 if s > 0 else -big, big if s > 0 else -0.3, 0.0, z_belt + 0.01), marca)
        # quadro da porta: frente inclinada, da cintura à borda do teto, paralela à coluna A
        if jan is not None:
            xa, za = float(jan[0]), float(jan[1])            # ponto alto da frente da janela (+3 cm de quadro)
            p0 = np.array([xd1, z_belt])
            p1 = np.array([xa, za])
            t = p1 - p0
            no = (t[1], 0.0, -t[0])                            # normal no plano xz
            n += cortar_plano(bm, (xd1, 0, z_belt), no, (min(xa, xd1) - 0.1, max(xa, xd1) + 0.1, 0.3 if s > 0 else -big,
                                                         big if s > 0 else -0.3, z_belt - 0.01, za + 0.02), marca)
        # para-lama: topo traseiro na cintura (a coluna A e o cowl ficam na carroceria), da frente da porta ao cowl
        zc_ = float(zw_a * 0.75 + zw_b) - 0.017
        n += cortar_plano(bm, (0, 0, zc_), (0, 0, 1), (xd1 - 0.02, x_cowl + 0.02, 0.55 if s > 0 else -big, big if s > 0 else -0.55,
                                                     zc_ - 0.1, zc_ + 0.1), marca, )
        # para-lama / capô: lateral do capô em y = ±y_capo, do cowl ao bico, só no topo
        n += cortar_plano(bm, (0, s * y_capo, 0), (0, 1, 0), (xd1 - 0.02, x_bico + 0.2, (y_capo - 0.1) if s > 0 else -(y_capo + 0.1),
                                                           (y_capo + 0.1) if s > 0 else -(y_capo - 0.1), 0.6, 1.45), marca)
        # tampa traseira: laterais em y = ±y_tampa, do vinco do teto para trás, no topo e na traseira
        n += cortar_plano(bm, (0, s * y_tampa, 0), (0, 1, 0), (-big, x_rg_top, (y_tampa - 0.1) if s > 0 else -(y_tampa + 0.1),
                                                            (y_tampa + 0.1) if s > 0 else -(y_tampa - 0.1), 0.3, 1.45), marca)
        # para-lama: traseira do topo no cowl (a base da coluna A é carroceria)
        n += cortar_plano(bm, (x_cowl, 0, 0), (1, 0, 0), (x_cowl - 0.1, x_cowl + 0.1, 0.55 if s > 0 else -big, big if s > 0 else -0.55,
                                                       0.85, 1.45), marca)
    # capô: traseira no cowl, só no topo entre as laterais
    n += cortar_plano(bm, (x_cowl, 0, 0), (1, 0, 0), (x_cowl - 0.1, x_cowl + 0.1, -y_capo - 0.02, y_capo + 0.02, 0.6, 1.45), marca,
                      normal=lambda nv: nv.z > 0.3)
    # tampa: frente no vinco do teto, entre as laterais
    n += cortar_plano(bm, (x_rg_top, 0, 0), (1, 0, 0), (x_rg_top - 0.1, x_rg_top + 0.1, -y_tampa - 0.02, y_tampa + 0.02, 1.0, 1.45), marca,
                      normal=lambda nv: nv.z > 0.3)
    # o topo da porta é a borda do teto: as arestas da fileira j_borda entre os cortes já existem; marca pelas posições
    j_borda = int(d["j_borda"])
    V = d["V"]
    zb_min = float(V[:, j_borda, 2].min()) - 0.02
    for e in bm.edges:
        a, b = e.verts
        c = 0.5 * (a.co + b.co)
        if xd0 - 0.005 < c.x < xd1 + 0.3 and abs(c.y) > 0.3 and c.z > zb_min:
            # aresta ao longo da borda do teto: os dois vértices perto da curva de borda (projetada em x)
            def perto(v):
                i = int(np.clip(np.searchsorted(V[:, j_borda, 0], v.co.x), 1, len(V) - 1))
                p = V[i, j_borda]
                return abs(abs(v.co.y) - p[1]) < 0.012 and abs(v.co.z - p[2]) < 0.012
            if perto(a) and perto(b) and abs(a.co.x - b.co.x) > 0.001:
                e[marca] = 1
                n += 1
    # vidro: a borda entre vidro e chapa separa o vidro (marca 2: sem fresta nem aba)
    for e in bm.edges:
        fs = e.link_faces
        if len(fs) == 2 and (fs[0].material_index == 1) != (fs[1].material_index == 1):
            e[marca] = 2
    # frente do capô e do para-lama: as arestas do fim das fileiras do loft (vértices com a marca "ponta" = 1)
    ponta = bm.verts.layers.int.get("ponta")
    for e in bm.edges:
        a, b = e.verts
        if ponta is not None and a[ponta] == 1 and b[ponta] == 1:
            e[marca] = 1
            n += 1
    return bm, marca, n


def separar(bm, marca):
    """Divide pelas arestas marcadas e devolve os conjuntos de faces conexos (lista de listas de faces)."""
    cortes = [e for e in bm.edges if e[marca]]
    bmesh.ops.split_edges(bm, edges=cortes)
    bm.faces.ensure_lookup_table()
    visto = set()
    grupos = []
    for f0 in bm.faces:
        if f0.index in visto:
            continue
        pilha = [f0]
        visto.add(f0.index)
        g = []
        while pilha:
            f = pilha.pop()
            g.append(f)
            for e in f.edges:
                for f2 in e.link_faces:
                    if f2.index not in visto:
                        visto.add(f2.index)
                        pilha.append(f2)
        grupos.append(g)
    return grupos


def nomear(grupos, z_belt):
    """Nome de cada grupo de faces pela posição do centro e pelo material (vidro)."""
    nomes = {}
    usados = set()
    out = []
    for g in grupos:
        c = np.mean([list(f.calc_center_median()) for f in g], axis=0)
        area = sum(f.calc_area() for f in g)
        vidro = all(f.material_index == 1 for f in g)
        if vidro:
            if c[0] > 0.2 and abs(c[1]) < 0.4:
                nome = "glass_windshield"
            elif c[0] < -1.0 and abs(c[1]) < 0.4:
                nome = "glass_rear"
            elif c[0] > -0.45:
                nome = "glass_door_fl" if c[1] > 0 else "glass_door_fr"
            else:
                nome = "glass_door_rl" if c[1] > 0 else "glass_door_rr"
        elif area < 0.002:
            nome = "lixo"
        else:
            nome = "body"
            if 1.0 < c[0] and abs(c[1]) < 0.5 and c[2] > 0.8 and area > 0.3:
                nome = "hood"
            elif c[0] < -1.3 and abs(c[1]) < 0.5 and area > 0.3:
                nome = "trunk"
            elif -0.5 < c[0] < 0.7 and abs(c[1]) > 0.5 and area > 0.3:
                nome = "door_fl" if c[1] > 0 else "door_fr"
            elif c[0] > 0.6 and abs(c[1]) > 0.45 and area > 0.15:
                nome = "fender_front_left" if c[1] > 0 else "fender_front_right"
        out.append((nome, g, area))
    return out


def fresta_e_aba(bm, faces, marca, mat_aba):
    """Nas arestas de borda vindas de corte: recua os vértices meia fresta para dentro da peça e cria a aba para dentro."""
    fs = set(faces)
    borda = [e for e in bm.edges if len(e.link_faces) == 1 and e.link_faces[0] in fs and e[marca] == 1]
    if not borda:
        return
    # direção para dentro por vértice: média das (normal x aresta) apontando para o centro da face vizinha
    mov = {}
    for e in borda:
        f = e.link_faces[0]
        a, b = e.verts
        t = (b.co - a.co).normalized()
        n = f.normal
        inward = n.cross(t)
        if inward.dot(f.calc_center_median() - 0.5 * (a.co + b.co)) < 0:
            inward = -inward
        for v in (a, b):
            mov.setdefault(v, []).append(inward)
    for v, ds in mov.items():
        dsum = sum(ds, Vector())
        if dsum.length > 1e-9:
            v.co += dsum.normalized() * (FRESTA / 2)
    # aba: extrusão da borda para dentro pela normal
    r = bmesh.ops.extrude_edge_only(bm, edges=borda)
    novos = [g for g in r["geom"] if isinstance(g, bmesh.types.BMVert)]
    for v in novos:
        n = Vector()
        for f in v.link_faces:
            if f in fs:
                n += f.normal
        if n.length < 1e-9:
            # pega a normal da face original pela aresta de origem
            for e in v.link_edges:
                for f in e.link_faces:
                    n += f.normal
        if n.length > 1e-9:
            v.co -= n.normalized() * ABA
    for g in r["geom"]:
        if isinstance(g, bmesh.types.BMFace):
            g.material_index = mat_aba
            g.smooth = False
            faces.append(g)
