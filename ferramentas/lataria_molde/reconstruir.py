"""
Um comando só: da ficha de texto ao carro aprovado, sempre igual.

    python -I ferramentas/lataria_molde/reconstruir.py <carro> [--sem-kit] [--previa] [--out <pasta>]
    (na nuvem do Detonauto: Tools/Blender/blender-nuvem.sh ../acervo-3d/ferramentas/lataria_molde/reconstruir.py -- <carro>)

  1. construir.py       ficha -> veiculos/proprios/quebravel/<id>/<id>.glb, _lod1.glb, _lod2.glb, _mapa.json, _wheels.json, _pecas.json, _molde.json
  2. carro_completo.py  o kit completo (interior, cofre, embaixo) nas medidas da carroceria nova -> veiculos/proprios/completo/<id>/
  3. portao.py          mede o arquivo final com o kit de anteparo; sai com código 1 se reprova (e grava <id>_portao.json)
  4. com --previa: as 4 vistas da folha em Cycles, de um lado só (previas/<id>-*.jpg na pasta do corte)
"""
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, '..', '..'))


def rodar(script, *args):
    cmd = [sys.executable, '-I', script, '--', *args]
    print('==', os.path.basename(script), ' '.join(args))
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for linha in r.stdout.splitlines():
        if ' | INFO' not in linha and 'Draco' not in linha and 'MeshOptimizer' not in linha and 'use_nodes' not in linha and linha.strip():
            print('  ', linha)
    return r.returncode


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    carro = argv[0]
    ficha = os.path.join(AQUI, 'fichas', carro + '.json')
    F = json.load(open(ficha, encoding='utf-8'))
    cid = F['carro']
    out = argv[argv.index('--out') + 1] if '--out' in argv else os.path.join(RAIZ, 'veiculos', 'proprios', 'quebravel', cid)
    kit = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(out))), 'completo', cid)
    if rodar(os.path.join(AQUI, 'construir.py'), '--ficha', ficha, '--out', out):
        sys.exit('falhou: construir.py')
    glb = os.path.join(out, cid + '.glb')
    args = [glb, '--json', os.path.join(out, cid + '_portao.json'),
            '--arcos', '%s,%s,%s,%s' % (F['cotas']['eixo_dianteiro'], F['cotas']['eixo_traseiro'], F['cotas']['z_centro_arco'], F['cotas']['raio_arco'])]
    if '--sem-kit' not in argv:
        if rodar(os.path.join(AQUI, '..', 'carro_completo.py'), '--corte', out, '--id', cid, '--out', kit, '--sem-previa', *F.get('kit_opcoes', [])):
            sys.exit('falhou: carro_completo.py')
        args += ['--kit', os.path.join(kit, cid + '_completo.glb')]
    codigo = rodar(os.path.join(AQUI, 'portao.py'), *args)
    if '--previa' in argv:
        extra = ['--kit', os.path.join(kit, cid + '_completo.glb')] if '--sem-kit' not in argv else []
        rodar(os.path.join(AQUI, 'previa.py'), glb, os.path.join(out, 'previas'), cid, *extra)
    sys.exit(codigo)


if __name__ == '__main__':
    main()
