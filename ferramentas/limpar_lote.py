#!/usr/bin/env python3
"""Passa limpar_ia.py em todos os modelos baixados de um lote do Meshy (altura real em metros do manifesto,
campo altura_m), trocando o arquivo no lugar. Uso:
  python3 ferramentas/limpar_lote.py meshy/lote-2026-10.json [--python caminho/do/python-com-bpy | --blender caminho/do/blender]
Sem --python nem --blender, usa `blender` do PATH.
"""
import json, os, subprocess, sys, shutil, tempfile, pathlib
RAIZ = pathlib.Path(__file__).resolve().parent.parent
def main():
    manifesto = sys.argv[1]; m = json.loads(pathlib.Path(manifesto).read_text(encoding="utf-8"))
    py = sys.argv[sys.argv.index("--python") + 1] if "--python" in sys.argv else None
    bl = sys.argv[sys.argv.index("--blender") + 1] if "--blender" in sys.argv else "blender"
    script = str(RAIZ / "ferramentas" / "limpar_ia.py")
    for it in m["itens"]:
        if not it.get("arquivo") or it.get("limpo"):
            continue
        entrada = RAIZ / it["arquivo"]
        if not it.get("altura_m"):
            print("sem altura_m:", it["id"]); continue
        tmp = pathlib.Path(tempfile.mkdtemp()) / entrada.name
        cmd = ([py, script] if py else [bl, "-b", "-P", script]) + ["--", "--entrada", str(entrada), "--saida", str(tmp),
               "--altura", str(it["altura_m"]), "--frente", "+x"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        linha = next((l for l in r.stdout.splitlines() if l.startswith("[limpar_ia]")), None)
        if r.returncode != 0 or not tmp.exists():
            print("FALHOU:", it["id"], (r.stderr or r.stdout)[-400:]); continue
        shutil.move(str(tmp), str(entrada))
        it["limpo"] = linha; print(linha)
        pathlib.Path(manifesto).write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
main()
