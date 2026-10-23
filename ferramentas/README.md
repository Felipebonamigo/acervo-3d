# Ferramentas do acervo

- `meshy_lote.py`: lote do Meshy pela API com teto de créditos e livro-caixa (`meshy/livro-caixa.md`). Fases `preview`,
  `status` (ou `olhar`, sem esperar), `refine`, `baixar`, `registrar`. Manifesto por lote em `meshy/lote-<ano-mes>.json`
  (prompt, categoria, jogo alvo, polycount, `aprovado` para o refine). As miniaturas das prévias ficam em
  `meshy/previas/<lote>/` para o Felipe olhar antes de pagar a textura.
- `limpar_ia.py`: limpeza de modelo gerado ou baixado dentro do Blender (`blender -b -P ferramentas/limpar_ia.py -- ...`):
  escala em metros, pivô na base, frente em +X, LODs por Decimate, GLB e FBX; `--sem-soltos` apaga ilhas com menos de 0,5 % dos vértices (só quando a miniatura mostra lixo: num poste, isoladores pequenos são ilhas legítimas). Não faz remesh nem bake. Testado na nuvem com o módulo `bpy` 5.2.3 (`pip install bpy` num venv).
  `--frente` diz para onde a frente aponta no arquivo de entrada: os carros do Meshy (multi-image-to-3d) chegam com a frente
  em -X, então use `--frente=-x` neles (com `=`, senão o argparse lê o `-x` como opção). Até 23/10/2026 o giro não era
  aplicado (o glTF importa a rotação em quaternion); os carros de `veiculos/meshy-conta/` foram reexportados com a frente em +X.
- `apagar_letreiro.py`: apaga letreiro, logo ou texto que o gerador pintou na textura (`--caixa x0,x1,y0,y1,z0,z1` em metros e
  `--normal` do lado de onde se olha). Lança raios sobre a caixa, monta a vista de fora da pintura, acha o que destoa do entorno
  e repinta só os texels acertados; `--previa` salva antes e depois. Letreiro denso pode pedir uma segunda passada com
  `--limiar` menor. Usado no capô do Furgãozinho da Firma.

Regras: nenhuma geração sem o Felipe aprovar o lote com o número de créditos; tudo gerado entra em `catalogo.csv` com
`gerado_por_ia` nas notas e na aba "Modelos 3D" do doc do estúdio no mesmo dia; licença CC0 ou CC BY só para o que
vem da comunidade; o que a conta do Felipe gera no plano Pro é dele.

## carro_quebravel.py

Transforma um carro que já vem em peças (a série modular de Daniel Zhabotinsky em `veiculos/sketchfab/`, CC BY 4.0, e outros GLB, glTF
ou FBX com um objeto por peça) num kit de peças padronizado para o pipeline de dano do Detonauto (`Tools/Blender/split_car_parts.py` e
`make_damage_morphs.py`).

```
blender -b --python-exit-code 1 -P ferramentas/carro_quebravel.py -- --entrada veiculos/sketchfab/sedan-kiri-10__<uid>.glb --out <pasta>
python -I ferramentas/carro_quebravel.py -- --entrada <carro.glb> --out <pasta> [--id nome] [--escala 0.01] [--amostras 24] [--sem-previa] [--sem-fbx] [--em-pecas]
```

Leva ~45 s por carro na CPU (quase tudo é a prévia). Saída em `--out`:

| Arquivo | O que é |
| --- | --- |
| `<id>.glb` | todas as peças, um objeto por peça com o nome padronizado, materiais renomeados |
| `<id>_pecas/<peca>.fbx` | uma por peça, com as opções de FBX do Detonauto (as do `make_street_light.py`); o pivô da peça vai na origem do FBX |
| `<id>_texturas/` | as texturas do GLB, que os FBX referenciam por caminho absoluto (o Detonauto troca os materiais pelos dele no Unreal) |
| `<id>_pecas.json` | por peça: papel, lado, `caixa_m` no formato `box` dos mapas do Detonauto, pivô, triângulos, materiais, a peça do Detonauto, os objetos de origem e a conferência da malha; no topo, dimensões, escala, orientação, material original → padrão, papel → materiais, removidos, `outros` e avisos |
| `<id>_wheels.json` | eixos e raio da roda em cm, no formato que `make_damage_morphs.py` e `split_car_parts.py` leem em `--wheels` |
| `<id>_previa.png` | prévia explodida em Cycles: à esquerda os materiais, à direita a cor por papel com o nome de cada peça |

O que ele faz:

- **Convenção do Detonauto:** metros, frente em +X, esquerda em +Y, cima em +Z; pivô do carro no chão (base dos pneus), no meio entre
  os eixos. As peças ficam no espaço do carro; as rodas têm o pivô no centro do cubo (`pivo_m` no JSON). A escala sai das rodas
  (diâmetro de 0,45 a 1,30 m) e do comprimento (2,4 a 12 m), testando m, cm, mm, polegada e pé; `--escala` força. A frente é achada
  pelos faróis e para-brisa contra lanternas e vidro traseiro; comprimento em Y gira 90°.
- **Papéis por regras:** regex sobre o nome do objeto (sem o prefixo do modelo, como `Kiri10_`), com a tabela `EXCECOES` no topo do
  script antes das `REGRAS` gerais e, sem regra, o material. Vocabulário: `body`, `hood`, `trunk`, `bumper_front`, `bumper_rear`,
  `glass_windshield`, `glass_rear`, `glass_door_fl/fr/rl/rr`, `headlight_left/right`, `taillight_left/right`, `wheel_fl/fr/rl/rr`,
  `interior`, `underbody` e `outros_<nome>` (não reconhecido, listado no relatório e no JSON).
- **Posição manda no lado:** rodas e vidros de porta levam o lado e a ponta pela posição, e um nome que contradiz a posição vira aviso (o
  Fairheaven tem as rodas RL e RR trocadas; o LCT3000 tem dois `Glass_Driver` e dois `WheelStock_FR`). Objetos com os dois lados juntos
  (os dois faróis num objeto, os vidros de trás) são divididos por ilha; ilha de luz no meio do carro (pisca lateral, lanterna lateral
  do baú) vai para a carroceria.
- **Tira emblemas e placas** (`Badges`, `Numberplate`, `logo`), mesmo de marca fictícia.
- **Materiais padronizados:** `pintura`, `vidro`, `luz`, `pneu`, `interior`, `chassi` (plástico escuro de baixo; o nome casa com o
  material escuro que o `split_car_parts.py` procura) e `cromado`; sem regra vira `outro` e entra nos avisos.
- **Malha validada:** faces degeneradas, vértices e arestas soltos, NaN; as normais do arquivo são preservadas (atributo de canto, como
  no `split_car_parts.py`), faces com a ordem contra a normal do arquivo são viradas, e vidro de uma face virado para dentro é virado.

### Resultados (23/10/2026)

| Carro | Comprimento | Entre-eixos | Peças | Outros |
| --- | --- | --- | --- | --- |
| `sedan-kiri-10` | 4,35 m | 2,70 m | 21 | nenhum |
| `sedan-fairheaven-lt80` | 5,00 m | 2,65 m | 21 | nenhum |
| `hatch-milano-95` | 3,85 m | 2,42 m | 20 (sem `trunk`: a tampa traseira vem fundida no `body`) | nenhum |
| `picape-lightbody-90` | 5,36 m | 3,16 m | 19 | `outros_bullbar_b` (quebra-mato) |
| `caminhao-bau-lct3000-07` | 5,86 m | 3,35 m | 18 (`trunk_left/right` = portas do baú) | nenhum |

Todos já vinham em metros e com a frente em +X. A picape e o caminhão não têm vidros de porta traseira; a caçamba da
picape é `body` e o caminhão não tem capô.

### Modo malha única (carros do Meshy, 23/10/2026)

Os carros nacionais gerados no Meshy (`veiculos/meshy-conta/`: `hatch-quadrado`, `besouro`, `pao-de-forma`, `tupiniquim`, `barao`) chegam
como **uma malha só** (~79 mil triângulos, textura PBR 2K, vidro e luzes só pintados). Com um objeto só no arquivo o script entra
sozinho no modo malha única (`--malha-unica` força; `--em-pecas` desliga):

```
python -I ferramentas/carro_quebravel.py -- --entrada veiculos/meshy-conta/barao__01a16960.glb --out <pasta> --portas 4 [--frente -x]
    [--mapa <pasta>/barao_mapa.json] [--detonauto ../Detonauto] [--debug-classes] [--sem-previa] [--sem-fbx] [--amostras 12]
```

~2,5 min por carro na CPU (metade é a prévia). Mesma saída do modo em peças, mais:

| Arquivo | O que é |
| --- | --- |
| `<id>_mapa.json` | o mapa de peças gerado pelas proporções (caixas, normais, espessura, vão); edite e rode de novo com `--mapa` |
| `<id>_amassada.png` | intacto, frente + esquerda em 1,0 e traseira + direita + teto em 1,0, com o campo do `make_damage_morphs.py` do Detonauto (lido como biblioteca, nada gravado lá); o `_pecas.json` traz o menor determinante por zona e a fresta medida na costura depois de amassar |
| `<id>_classes.png` | (`--debug-classes`) a classe de textura de cada face: vidro por janela, faróis, lanternas, placas, grade, retrovisores |

Como funciona:

1. **Solda** os vértices repetidos das costuras de UV (a malha do Meshy é uma ilha por ilha de UV; os UVs ficam nos cantos, nada
   estica) e guarda a normal de cada canto, que atravessa os cortes.
2. **Frente** pelos retrovisores (pico estreito de largura acima da cintura, na metade da frente); os cinco vinham com a frente em -X e
   foram girados 180°. `--frente` força. Origem no chão, entre os eixos.
3. **Rodas** pela geometria: contato com o chão nas quatro pontas, raio pela banda de rodagem (faces a um raio R do cubo com a normal
   para fora dele), aro onde a face externa deixa de ser borracha escura, calota onde o miolo avança para fora. Saem `wheel_<pos>_tire`,
   `wheel_<pos>_rim` e `hubcap_<pos>`, com pivô no cubo; atrás de cada roda a carroceria ganha uma **caixa de roda escura** (arco +
   parede de dentro), nunca um buraco.
4. **Vidros** pela textura (cor na UV de cada face): pouco saturado e diferente da pintura (mais escuro, menos saturado ou de outro
   matiz), mais as regiões cercadas pela borracha (rugosidade alta e metal zero); cada janela é o fecho convexo dos pedaços acima da
   cintura (o para-brisa e o vidro traseiro, espelhados em Y), separada em `glass_windshield`, `glass_rear`, `glass_door_fl/fr` e
   `glass_door_rl/rr` (janela de trás ou do vigia). Nos carros de 4 portas com a coluna B preta, corta na faixa mais escura do meio.
5. **Faróis, lanternas, placas e grade** pela textura nas pontas (claro / vermelho-âmbar / branco no meio / escuro entre os faróis);
   pedaço pequeno demais fica no corpo, com aviso.
6. **Painéis por planos** (como o `split_car_parts.py`): para-choques, capô (largura do para-brisa), tampa traseira (vertical no hatch e
   na van, deck no sedã e no besouro), saias laterais, portas (uma ou duas por lado; na van a da cabine), para-lamas dianteiros e
   traseiros, retrovisores. Cada seleção passa por um fechamento e fica só com as partes conexas grandes (sem fiapos).
7. Cada peça sai **fechada** (espessura, lado de dentro em `chassi`) e deixa um **vão** escuro (`MI_DNVao`) na carroceria; atrás dos
   vidros o vão é a casca escura de interior (35 cm). Materiais: `pintura` (o do Meshy), cópias com a mesma textura `vidro`, `luz`,
   `pneu`, `cromado`; sem textura `chassi` e `MI_DNVao`.

Peças que o vocabulário do Detonauto ainda não tem (listadas em `fora_do_vocabulario_do_detonauto` no `_pecas.json`): `door_rl/rr`
(porta traseira), `side_skirt_*`, `mirror_*`, `grille`, `plate_*`, `wheel_*_tire/rim` e `hubcap_*` (a roda hoje é inteira do Chaos).

Limites conhecidos: corte reto por caixa (não segue o vinco do Meshy); placa da van branca não sai (pintura branca); faróis redondos da
van e do besouro e as lanternas do besouro não se separam da pintura pela cor; escapamento, antena e limpadores são só pintura ou
fundidos no assoalho (ficam no corpo); em amassado forte de lado, a casca de interior de 30 cm atrás do vidro da porta pode aparecer
pela janela.

### Os 13 carros nacionais cortados (23/10/2026)

`veiculos/meshy-conta/quebravel/<carro>/` guarda o que repete o corte igual: o mapa de peças (`_mapa.json`), o relatório
(`_pecas.json`), as rodas (`_wheels.json`) e uma prévia explodida e amassada (`_previa.jpg`). O GLB e os FBX das peças
(~40 MB por carro) não entram no acervo: saem de novo em ~2,5 min com
`carro_quebravel.py -- --entrada veiculos/meshy-conta/<carro>__<id>.glb --out <pasta> --portas N --mapa veiculos/meshy-conta/quebravel/<carro>/<carro>_mapa.json`.
De 28 a 40 peças por carro; fresta zero ao amassar nos 13. No Pampeiro, no Furgãozinho e no Trilheiro o para-brisa não sai
pela cor, então o capô (e no jipe o para-choque dianteiro) foi posto à mão no mapa, pelo perfil do teto. Pendente: o
bagageiro do Furgãozinho fica no corpo (devia soltar com a escada).

### O que falta para o pipeline de dano do Detonauto

1. **Portas e para-lamas estão fundidos no `body`** (nesta série, só capô, porta-malas, para-choques, vidros, luzes e rodas são objetos
   próprios). **O corte por planos do `split_car_parts.py` resolve**, testado no Kiri: com `body.fbx` + `underbody.fbx` como `--inputs`
   (o `underbody` traz o material `chassi`, que o script exige para o lado de dentro e os vãos) e o `<id>_wheels.json` como `--wheels`,
   um mapa com `DoorLeft`, `FenderFrontLeft` e `FenderRearLeft` (espelhados) saiu limpo, com borda reta e vão escuro. Duas condições:
   cada caixa precisa de `"material": "pintura"` (sem isso a caixa leva junto a caixa de roda e a suspensão do `underbody`), e as caixas
   são medidas à mão por carro a partir de `caixa_m` dos vidros e rodas no `_pecas.json` (o mapa de teste do Kiri está no rascunho da
   sessão; o do Detonauto vai em `Tools/Blender/parts/<Carro>.json`). O corte é reto: não segue o vinco da porta do modelo.
2. **Tampa do hatch:** no Milano a tampa traseira também precisa de caixa (`Trunk`) no mapa.
3. **Sedã de 4 portas:** o contrato (`docs/regras-pecas.md`) tem uma porta por lado. A porta de trás fica na carroceria, ou o contrato
   ganha `DoorRearLeft/Right` (mudança no enum `EDNDamagePart`, `Data/CarParts.csv` e testes).
4. **Peças já separadas entram como peças do mapa** com `"take": "islands"` (capô, porta-malas, para-choques e lentes), ou o `split`
   ganha uma opção para receber peças prontas em vez de recortar. Hoje ele espera a carroceria inteira num FBX só.
5. **Retrovisores e frisos** estão dentro do `underbody` (objeto `Bottom` do modelo). Para soltar o retrovisor (regra do contrato), é preciso
   mais uma caixa no mapa.
6. **Unreal:** as rodas viram as rodas do Chaos Vehicle (pivô no cubo já pronto, raio no `_wheels.json`); os vidros e lentes ligam aos
   materiais de trinca; as linhas de `Data/CarParts.csv` e `Data/CarGlass.csv` do carro novo, o `CarId` e a captura de aprovação
   (`aprovar-visual`) ainda faltam. O crédito CC BY do autor entra na tela de créditos e o modelo em `docs/licencas.csv`.
