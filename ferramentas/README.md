# Ferramentas do acervo

- `meshy_lote.py`: lote do Meshy pela API com teto de créditos e livro-caixa (`meshy/livro-caixa.md`). Fases `preview`,
  `status` (ou `olhar`, sem esperar), `refine`, `baixar`, `registrar`. Manifesto por lote em `meshy/lote-<ano-mes>.json`
  (prompt, categoria, jogo alvo, polycount, `aprovado` para o refine). As miniaturas das prévias ficam em
  `meshy/previas/<lote>/` para o Felipe olhar antes de pagar a textura.
- `limpar_ia.py`: limpeza de modelo gerado ou baixado dentro do Blender (`blender -b -P ferramentas/limpar_ia.py -- ...`):
  escala em metros, pivô na base, frente em +X, LODs por Decimate, GLB e FBX; `--sem-soltos` apaga ilhas com menos de 0,5 % dos vértices (só quando a miniatura mostra lixo: num poste, isoladores pequenos são ilhas legítimas). Não faz remesh nem bake. Testado na nuvem com o módulo `bpy` 5.2.3 (`pip install bpy` num venv).

Regras: nenhuma geração sem o Felipe aprovar o lote com o número de créditos; tudo gerado entra em `catalogo.csv` com
`gerado_por_ia` nas notas e na aba "Modelos 3D" do doc do estúdio no mesmo dia; licença CC0 ou CC BY só para o que
vem da comunidade; o que a conta do Felipe gera no plano Pro é dele.

## carro_quebravel.py

Transforma um carro que já vem em peças (a série modular de Daniel Zhabotinsky em `veiculos/sketchfab/`, CC BY 4.0, e outros GLB, glTF
ou FBX com um objeto por peça) num kit de peças padronizado para o pipeline de dano do Detonauto (`Tools/Blender/split_car_parts.py` e
`make_damage_morphs.py`).

```
blender -b --python-exit-code 1 -P ferramentas/carro_quebravel.py -- --entrada veiculos/sketchfab/sedan-kiri-10__<uid>.glb --out <pasta>
python -I ferramentas/carro_quebravel.py -- --entrada <carro.glb> --out <pasta> [--id nome] [--escala 0.01] [--amostras 24] [--sem-previa] [--sem-fbx]
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
