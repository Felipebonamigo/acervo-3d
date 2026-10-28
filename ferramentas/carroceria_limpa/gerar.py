"""
Carroceria limpa: refaz a lataria de um carro do Meshy como superfícies limpas, usando o Meshy só como molde
(decisão do Felipe de 28/10/2026: "faça tudo até ficar perfeito"; remendar a malha do Meshy não chegava lá).

Entrada: a pasta do corte do carro_quebravel.py (o <id>.glb do Meshy cortado e o <id>_mapa.json com as medidas e as caixas).
Saída: um <id>.glb no mesmo formato do corte (body, door_fl/fr, hood, trunk, fender_front_left/right, glass_*, headlight_*,
taillight_*, bumper_*, grille, mais retrovisores, placas e rodas do Meshy), pronto para o carro_completo.py e para a cadeia do
Detonauto (make_crush_channels, kit_to_detonauto, glb_texturas).

    python -I ferramentas/carroceria_limpa/gerar.py -- --corte <pasta do corte> --id <carro> --out <pasta de saída> [--molde <meshy>.glb] [--trabalho <pasta>]

Passos (cada um é um script da pasta, que também roda sozinho):
  1. medir.py    mede a casca do Meshy por raios em grade de 1 cm nas 4 vistas (lateral, topo, frente, traseira) -> campos.npz
  2. corpo.py    ajusta polinômios por região (lateral baixa, caixa de vidros, capô, para-brisa, teto, vidro traseiro, frente,
                 traseira), monta as seções com vincos, o loft e os contornos dos vidros -> corpo.npz
  3. malha.py    monta a malha no Blender: loft espelhado, tampas com bolsos, vidros rebaixados com borracha, cortes dos painéis com
                 fresta, pele de dentro, para-choques, maçanetas, limpadores, faróis e lanternas; junta o que fica do Meshy -> <id>.glb
"""
import argparse
import os
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--corte", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--trabalho", default=None, help="pasta dos arquivos intermediários (campos.npz, corpo.npz); padrão: <out>/trabalho")
    p.add_argument("--molde", default=None, help="o GLB do Meshy cortado (padrão: <corte>/<id>.glb; no acervo fica como <id>_meshy.glb)")
    a = p.parse_args(argv)
    glb = a.molde or os.path.join(a.corte, a.id + ".glb")
    mapa = os.path.join(a.corte, a.id + "_mapa.json")
    for f in (glb, mapa):
        if not os.path.isfile(f):
            raise SystemExit("falta " + f)
    trab = a.trabalho or os.path.join(a.out, "trabalho")
    os.makedirs(trab, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    campos = os.path.join(trab, "campos.npz")
    corpo = os.path.join(trab, "corpo.npz")
    saida = os.path.join(a.out, a.id + ".glb")
    py = sys.executable
    passos = [
        [py, "-I", os.path.join(AQUI, "medir.py"), "--", glb, campos],
        [py, "-I", os.path.join(AQUI, "corpo.py"), "--", campos, mapa, corpo],
        [py, "-I", os.path.join(AQUI, "malha.py"), "--", corpo, saida, glb],
    ]
    for cmd in passos:
        print("==", os.path.basename(cmd[2]))
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit("falhou: " + os.path.basename(cmd[2]))
    # os JSON do corte continuam valendo (mapa, peças, rodas): copia para a saída
    for suf in ("_mapa.json", "_pecas.json", "_wheels.json"):
        src = os.path.join(a.corte, a.id + suf)
        if os.path.isfile(src) and os.path.abspath(src) != os.path.abspath(os.path.join(a.out, a.id + suf)):
            shutil.copy(src, os.path.join(a.out, a.id + suf))
    print("pronto:", saida)


if __name__ == "__main__":
    main()
