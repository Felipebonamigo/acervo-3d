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
De 28 a 40 peças por carro; fresta zero ao amassar nos 13. Em 27/10/2026 o mapa do Besouro foi acertado à mão (porta de -0,33 a 0,62 m, capô e tampa do motor mais largos, para-brisa por
planos e oito caixas com `"papel": "remover"`, que tiram da carroceria a casca de dentro que o Meshy fez atrás dos vidros, da porta e
das tampas, sem virar peça nem vão) e o do Trilheiro (porta de -0,66 a 0,29 m, para-lamas da frente, vidros e capô por planos com
`"ignorar_rotulos": true`, porque a cor oliva confundia a classe de vidro). No Pampeiro, no Furgãozinho e no Trilheiro o para-brisa não sai
pela cor, então o capô (e no jipe o para-choque dianteiro) foi posto à mão no mapa, pelo perfil do teto. O bagageiro do
Furgãozinho sai como peça (`roof_rack`, de 1,53 m para cima) para soltar junto com a escada; no Besouro as tampas (capô e
motor) foram limitadas a ~85 cm de largura e o para-choque traseiro à lâmina da ponta, para não levar os para-lamas.

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

## Scripts pequenos do lote de 24/10/2026

Todos rodam com o módulo `bpy` no Python (`python ferramentas/<script>.py ...`, num venv com `pip install bpy pillow numpy`).

| Script | Para quê | Uso |
| --- | --- | --- |
| `decimar.py` | reduzir um GLB que o Meshy entregou sem remesh (multi-image e image-to-3d chegaram com 0,1 a 2,5 milhões de triângulos) antes do `limpar_ia.py`; Decimate por colapso, UV mantida | `decimar.py <ent.glb> <sai.glb> <triângulos>` |
| `closes.py` | tira de closes (frente, traseira, 3/4, lado) para olhar antes de afirmar algo visual; `--perto` faz só frente e traseira de perto, para achar letreiro e placa | `closes.py <glb> <png> [largura] [--perto]` |
| `cortar_base.py` | cortar o monte de areia ou chão que o gerador pôs debaixo de um objeto (usado no posto de salva-vidas) e pôr o chão em z = 0 | `cortar_base.py <ent> <sai> <altura_do_corte_m>` |
| `tirar_pneu.py` | apagar a borracha dos pneus de um carro queimado e assentá-lo no aro, pelas rodas do mapa de corte (`quebravel/<carro>/<carro>_mapa.json`) | `tirar_pneu.py <ent.glb> <mapa.json> <sai.glb>` |

O `tirar_pneu.py` limita o aro a 55 a 65 % do raio do pneu: no Lambari o corte achou um aro pequeno demais (0,12 m) e no
Trilheiro um do tamanho do pneu; sem esse limite o primeiro perdeu o aro e o segundo ficou com pneu.

Retexture e malha: o retexture do Meshy (10 créditos, `enable_original_uv`) mantém malha e UV, então o mapa de corte do carro
original vale; mas não cria geometria (a caixa de teto do táxi foi posta no Blender) e, por texto, tende a pintar número em
placa. O que funcionou para o fogo foi passar a foto aprovada como `image_style_url`.

## carro_completo.py

Gera, para um carro já cortado pelo `carro_quebravel.py`, as partes que faltam para ele ficar completo por dentro e por baixo
(pedido do Felipe de 26/10/2026, `Detonauto/docs/pedido-carro-completo.md`), encaixadas nas medidas daquele carro. Tudo é
geometria e textura feitas pelo script: licença CC0 do estúdio, sem marca, sem logo, sem texto de marca, sem IA.

```
python -I ferramentas/carro_completo.py -- --corte <pasta do corte> --id <carro> --out veiculos/meshy-conta/completo/<carro> \
    [--epoca 70|80|90|2000] [--motor ...] [--amostras 24] [--sem-previa] [--sem-sujeira]
python -I ferramentas/carro_completo.py -- --corte veiculos/meshy-conta/quebravel/<carro> --id <carro> --so-medidas
python3 -m unittest ferramentas/test_carro_completo.py     # medidas e dados dos 13, sem Blender
```

A pasta do corte precisa do `<carro>.glb` do `carro_quebravel.py` (não fica no acervo, ~20 MB): sai em ~1 min com
`carro_quebravel.py -- --entrada veiculos/meshy-conta/<carro>__<id>.glb --out <pasta> --portas N --mapa
quebravel/<carro>/<carro>_mapa.json --sem-previa --sem-fbx`. Sem ele o kit sai só pelas medidas dos JSON (sem assentar na
casca, sem sujeira com a casca e sem prévias). ~1 min para o kit (com a sujeira assada) e ~2 min de prévias por carro, na CPU.

### v2 (27/10/2026)

- **Vão do motor denso:** bloco com nervuras e selos, cabeçote, junta, tampa de válvulas com parafusos e bocal de óleo, capa da
  correia dentada, polias e correia (fecho das polias), alternador com aletas e suporte, motor de partida com solenoide, filtro
  de óleo, coletor de admissão (carburador e filtro redondo nos 70/80, monoponto nos 90, plenum, corpo de borboleta, caixa de
  filtro com presilhas e duto nos 2000), coletor de escape com protetor de calor (90/2000), distribuidor com tampa, torres e
  cabos de vela com cachimbo (até os 90) ou bobinas individuais (2000), bobina no para-lama, câmbio com cabos de engate e da
  embreagem; radiador com colmeia, caixas laterais, bocais, tampa (70/80), carenagem e ventoinha elétrica com o fio; mangueiras
  superior, inferior e do aquecedor com abraçadeiras; reservatório de expansão com marcas de nível e tampa, do freio e do
  lavador com a bomba e a mangueira; bateria na bandeja com grampo, tampas das células, bornes, terminais, capa do positivo e os
  cabos até a partida e a massa; chicote em conduíte corrugado com presilhas, caixa de fusíveis (90/2000); servo-freio,
  cilindro-mestre e as linhas de freio; corta-fogo com manta, passa-fios, caixa de ar com frestas e motor do limpador; torres
  com os prisioneiros, abas com pontos de solda, furos de passagem; longarinas com furos e soldas; painel dianteiro com a
  fechadura do capô, o cabo, a buzina e o fundo dos faróis; manta antirruído e reforços por baixo do capô (`hood_manta`, segue
  `hood`). Variantes: `l4_transversal` (bloco tombado 12° para trás, câmbio ao lado), `l4_longitudinal` (câmbio no túnel),
  `v8_longitudinal` (bancadas, coletores de ferro, carburador quádruplo, distribuidor com 8 cabos, ventoinha mecânica, bomba da
  direção) e `boxer_traseiro` (carenagem da ventoinha, gerador no pedestal com cinta, correia, carburador e filtro em banho de
  óleo, coletor em Y, chapas defletoras, trocadores de calor, bobina na carenagem). Estepe no vão do motor (`vao_motor`) nos
  micros da época.
- **Materiais:** cor em 1024 px (os grandes; detalhe pequeno em 512 ou menos), aspereza e relevo (normal) assados em meia
  resolução, tudo ladrilhável e na escala física (o fio do tecido tem ~1,6 mm, o granulado do plástico ~0,7 mm). Tecido com
  fio a fio e bolinhas, estampa em losango (90) e listras (80); vinil com grão e vincos; plástico com granulado e riscos;
  borracha fosca com pó; carpete com laços, manchas escuras e áreas pisadas; feltro do teto amarelado; metal escovado com
  micro-riscos; fundido com poros; ferro com placas de ferrugem; mostradores com números genéricos (km/h, x1000 rpm, 0 1/2 1,
  50 90 130), hodômetro e luzes-espia. Variantes de uso por grupo: o vão do motor `_po` (pó claro e áspero), embaixo e freios
  `_graxa` (graxa, óleo e escorridos), banco do motorista e aro do volante `_gasto` (desbotado e liso onde se apoia). E a
  **sujeira por oclusão** assada nos vértices (Cycles, com a casca do carro na cena) no atributo `sujeira`, que vai no `COLOR_0`
  e multiplica a cor base (no Blender e no glTF; no Unreal, o material do Detonauto multiplica pela Vertex Color). Imagens em
  JPEG (qualidade 82) dentro do GLB.
- **Habitáculo e portas com proporções de carro de verdade** (medidas em `carro_completo_dados.json`, `medidas_reais`, com as
  fontes): assento a 0,27 m do piso, encosto de 0,60 m, encosto de cabeça de 0,26 × 0,19 m com hastes e guias, vivos e
  costuras, apoio de braço da porta a 0,22 m acima do assento, forro com capa de cima e escova do vidro, miolo de tecido (ou
  vinil plissado nos 70) com moldura chanfrada e vivo, carpete embaixo (80/90), maçaneta em concha com alavanca, manivela,
  pino, bolso (com porta-garrafa nos 2000), alto-falante de 6,5", refletor; painel com mostradores numerados, capuz,
  interruptores, pisca-alerta, rádio com dial e toca-fitas, acendedor e cinzeiro, porta-luvas com fresta e fechadura, grade
  do desembaçador; volante com alavancas de seta e limpador (haste e ponta), comutador com a chave e o chaveiro, aro gasto
  nas 10 e 2 horas; pedais com borrachas nervuradas, mola e interruptor; cinto com presilha, lingueta, botão, retrator,
  fivela com o botão vermelho e o trilho na soleira (2 portas); tapetes de borracha (o do motorista com o calcanhar);
  quebra-sol com espelho de cortesia; alavanca dia/noite no retrovisor.
- **Carrocerias:** `hatch`, `sedan`, `furgao` (cabine de 2 lugares, divisória de grade, área de carga com manta nervurada,
  laterais de chapa com nervuras, caixas de roda e ganchos), `cabine_avancada` (motorista sobre o eixo da frente, banco
  inteiriço do passageiro, volante deitado, sem capô; piso de compensado, deque do motor traseiro, divisória de chapa e
  grade, eixo dianteiro de tubos) e `jipe` (santo-antônio com pernas até as caixas de roda e espuma, chassi de longarinas,
  eixo rígido na frente com diferencial, caixa de transferência, cardã dianteiro e a alavanca da reduzida).
- **Correções medidas à mão** (`corrigir` por carro): altura sem antena nem bagageiro, para-brisa e vidro de trás onde o
  mapa não tinha ou a cor errou, cintura e coluna B do jipe, piso da cabine avançada.

**Peças** (um objeto por peça, no espaço do carro do corte, nomes do kit de quebra; `segue` no JSON diz a peça do corte que
leva junto): habitáculo `interior_*` (carpete, tapetes, bancos, painel, volante, pedais, câmbio, freio de mão, console, cintos,
forro do teto, quebra-sóis, retrovisor, acabamentos, e `interior_carga`, `interior_divisoria`, `interior_santantonio`);
porta `door_card_<pos>` e `door_card_<pos>_chapa` (segue `door_<pos>`); vão da porta `jamb_<pos>_*`; porta-malas
`interior_portamalas_*`; motor `engine_*` e `hood_manta`; embaixo `under_*` (assoalho, linhas, chassi do jipe, escapamento,
tanque, berço, suspensões, eixos, caixas de roda); freios `brake_<pos>_*` (disco, tambor e cubo giram com a roda; pinça e
chapa vão na manga). LOD1 de cada peça (Decimate a 30 %, sufixo `_LOD1`) no mesmo GLB.

**O que o Detonauto faz ao usar o kit** (no `<carro>_completo.json`): tirar do corte a casca escura `MI_DNVao` nas caixas
`vaos_a_tirar_do_corte` e o fundo liso da casca do Meshy (`fundo_a_tirar_do_corte`), senão o interior fica escondido; prender
cada peça na que ela `segue`; multiplicar a cor base pela Vertex Color (sujeira); mostrar o interior só perto da câmera
(≤ 15 m, pedido) e medir com 40 carros de tráfego.

Prévias (Cycles na CPU): porta dianteira esquerda arrancada vista de lado a 1,5 m, a porta caída vista por dentro, cabine pelo
para-brisa, painel visto de dentro, capô aberto (no motor traseiro também a tampa de trás; na cabine avançada só a de trás) e
por baixo. Só a prévia da cabine tira do corpo as faces no plano do para-brisa que o corte deixou (o número vai no JSON,
`previa_faces_do_para_brisa_tiradas`); no Besouro a casca de dentro saiu de verdade pelo mapa (papel `remover`).

**Limites (v2):** o visual é de jogo de PC de uns 10 anos atrás, não de foto: a geometria é primitiva arredondada e chanfrada
(sem escultura), o tecido e o plástico ficam corretos de perto mas planos na luz difusa, os mostradores não têm vidro, e a
sujeira por vértice depende da densidade da malha (painéis grandes ficam limpos). Ainda falta a aprovação por captura ao
lado de foto real (`aprovar-visual` do Detonauto) e a medição no Unreal com 40 carros.

## rodas_kit.py (27/10/2026)

Rodas CC0 feitas do zero por geometria para o carro completo do Detonauto (lote 5 de `docs/carro-completo.md` lá): 4 aros (`aro_aco13`,
`aro_aco14`, `aro_liga13`, `aro_liga14`), 3 pneus (`pneu_p165_70`, `pneu_p175_70`, `pneu_p185_60`), cada um em 3 malhas (`_Ok`, `_Flat` com o
raio 6 cm menor no chão e `_Torn` estourado), e 2 calotas. Redondas de verdade (64 segmentos, desvio < 0,4 mm), pivô no cubo, face de fora em
+Y (roda esquerda; a direita gira 180° em Z), LOD1 no mesmo GLB, roda completa ≤ 9 mil triângulos. Saída em `veiculos/proprios/rodas/` com o
`rodas_kit.json` e a prévia. Aro e pneu são independentes: é o que deixa trocar um sem o outro.

    python -I ferramentas/rodas_kit.py -- [--out <pasta>] [--amostras 32] [--sem-previa]
    python -I ferramentas/test_rodas_kit.py -v

Falta melhorar: as tiras do pneu estourado parecem alças de lado; os sulcos da banda somem a 4 m.

## alisar_lataria.py (27/10/2026)

Deixa a lataria do Meshy com reflexo de carro novo. O Felipe comparou o Cuiabano com a foto de um carro de estúdio: "o outro parece massa
de modelar". O defeito é mais de sombreamento do que de forma. O Meshy faz triângulos grandes e tortos na chapa lisa, e a normal
interpolada entre eles quebra o reflexo.

- **Como funciona:** a chapa é vista de 9 direções: as duas laterais, o topo, a frente, a traseira e 4 diagonais. Em cada vista ela vira
  um relevo numa grade de 1 cm, alisado por um filtro longo no comprimento e curto na altura. A normal de cada ponto sai desse relevo
  alisado, e a forma anda no máximo 6 mm.
- **Vincos e bordas:** onde a chapa vira, ou onde o relevo alisado discorda da chapa em mais de 35°, fica a normal média.
- **Ordem:** rode na malha CHEIA e depois reduza com o `decimar.py`, que leva a normal nova para a malha reduzida. Corte com
  `carro_quebravel.py --manter-normais`; sem a opção, a solda recalcula as normais e desfaz o alisamento.

    python -I ferramentas/alisar_lataria.py -- <cheio.glb> <alisado.glb>
    python -I ferramentas/decimar.py <alisado.glb> <reduzido.glb> 120000
    python -I ferramentas/carro_quebravel.py -- --entrada <reduzido.glb> --out <pasta> --mapa <id>_mapa.json --manter-normais

Medida no teste do verniz (listras refletidas, `meshy/previas/cuiabano-v2/`): as listras da lateral passam de picotadas a retas e contínuas.
Tentativas que pioraram, para não repetir: alisamento ponto a ponto (Taubin) só na tinta ou em tudo, e filtro igual nos dois eixos.

## Acabamento da chapa depois do corte (27 e 28/10/2026)

Pedido do Felipe ("faça tudo até ficar perfeito", com a foto de um carro de estúdio como referência). São três passos no GLB do
`carro_quebravel.py`, nesta ordem, cada um gravando por cima:

    python -I ferramentas/fechar_rachas.py  -- <pasta>/<id>.glb <pasta>/<id>.glb
    python -I ferramentas/alisar_pecas.py   -- <pasta>/<id>.glb <pasta>/<id>_mapa.json <pasta>/<id>.glb
    python -I ferramentas/vedacao_vidros.py -- <pasta>/<id>.glb <pasta>/<id>.glb

Depois disso, refaça o kit (`carro_completo.py`) sobre o corte novo. Desde 28/10 (noite) a cadeia completa, com a cirurgia nas
bordas, está na seção `cirurgia_bordas.py` abaixo.

- **`fechar_rachas.py`:** a malha do Meshy tem costuras internas não soldadas, com duas fileiras de vértices a menos de 2 mm e a
  parede da espessura entre elas. De perto, viravam riscos pretos no meio do capô e do teto. O script solda os vértices de borda de
  material que têm par a menos de 2 mm. O contorno das peças não muda, porque lá os vizinhos ficam a ~1 cm. No Cuiabano v2, o capô
  tinha ~12 m de rachas para 4,5 m de contorno.
- **`alisar_pecas.py`:** todas as peças pintadas entram num conjunto só de pontos. Como a fresta é 0, a lateral inteira (para-lama,
  porta e lateral traseira) vira uma chapa só, e o reflexo atravessa as emendas reto; antes, a emenda da porta com a lateral traseira
  saía num vinco. A chapa é separada por 13 direções (incluindo as diagonais para baixo da saia), abaixo e acima da cintura, e por
  pedaço ligado. Cada pedaço recebe uma B-spline lisa, com um ponto de controle a cada 30 cm e penalidade de curvatura, e a normal sai
  dela. Pedaço com mais de 1,2 m e desvio mediano acima de 6 mm (a diagonal do ombro juntava capô, para-lama e coluna) é refeito em
  faixas no comprimento. Pontos a mais de 10 mm da superfície (maçaneta, friso, borda da caixa de roda) ficam com a normal de antes.
  Os vértices não andam (`--max-mm 0`), porque deslocar a forma abria rachas entre as peças.
- **`vedacao_vidros.py`:** o corte separa o vidro pelos triângulos, e a borda saía em escada (dentes brancos de 2 a 4 cm). O script
  rasteriza a face de fora de cada vidro numa grade de 3 mm, alisa a máscara (disco de ~2 cm, corte em 0,3) e tira o contorno por
  raios. Alisa a curva, a normal da chapa e a altura ao longo dela, e faz por cima uma borracha preta de perfil arredondado (material
  `chassi`). A largura, de 1,6 a 3,6 cm, vem do tamanho da escada. A borracha entra na peça que leva o vidro no jogo (porta, tampa
  traseira ou carroceria) e fica quando o vidro estoura.
- **`carro_completo.py`:** a função `recolher_na_casca` puxa para 6 mm por dentro da chapa os vértices do interior, das portas e do
  porta-malas que encostavam nela ou passavam dela. O teto do Meshy tem calombos, e o forro, o quebra-sol e o painel apareciam por fora
  em manchas. Desde 28/10 (noite) a casca de fora inclui o plástico escuro acima da cintura (as borrachas dos vidros e a aba do
  teto), a 6 cm de alcance: o forro atravessava as borrachas nos cantos dos vidros e as colunas.

Prévias em `meshy/previas/cuiabano-v2/`:
- `cuiabano-v2-acabamento-antes-depois.jpg`: de perto, antes à esquerda e depois à direita;
- `cuiabano-v2-chapa-por-painel-antes-depois.jpg`: no ângulo da foto de referência;
- `cuiabano-v2-verniz-chapa-por-painel.jpg`: teste das listras.

O que ainda falta é forma da malha, não reflexo: a saia das portas, o canto do para-lama perto do farol, a base do para-brisa
(palhetas e grade de ventilação) e as frestas, que não são retas.

## cirurgia_bordas.py, pele_de_dentro.py e a cadeia "Meshy sem borrões" (28/10/2026, noite)

O Felipe viu a carroceria limpa e preferiu o Meshy ("parece mais fiel ao modelo, só precisava tirar os borrões"). O que sobrava de
borrão no Meshy acabado era forma e lasca, não normal: bordas enroladas no fundo das portas e da saia, cantos amassados nos para-lamas
e nas caixas de roda, frestas tortas, a pele de dentro saindo por fora em toda borda, retalhos de chapa serrilhada em volta dos vidros,
vinco no vidro da porta. A cadeia completa fica (cada passo grava por cima do anterior):

    python -I ferramentas/fechar_rachas.py   -- <c>.glb <c>.glb
    python -I ferramentas/alisar_pecas.py    -- <c>.glb <mapa>.json <c>.glb --max-mm 25     # a forma anda até 25 mm
    python -I ferramentas/cirurgia_bordas.py -- <c>.glb <mapa>.json <c>.glb                 # bordas refeitas, sem pele
    python -I ferramentas/vedacao_vidros.py  -- <c>.glb <c>.glb --max-cm 1.5 --sigma 10     # vidro liso, ferro, borrachas
    python -I ferramentas/alisar_pecas.py    -- <c>.glb <mapa>.json <c>.glb                 # só a normal, por último
    python -I ferramentas/pele_de_dentro.py  -- <c>.glb <mapa>.json <c>.glb                 # pele de dentro, por último

- **`cirurgia_bordas.py`:** carroceria, portas, capô, tampa, para-lamas e saias viram uma casca pintada só (`remove_doubles` de 0,8 mm
  nas costuras dos cortes antigos). Saem as paredes de espessura do `carro_quebravel.py` (faces `chassi` coladas à borda da pintura)
  e o forro escuro do Meshy a menos de 1 cm por baixo da chapa e não paralelo a ela (dava riscos pretos no capô). Cortes por plano
  (`bisect_plane` nas faces da caixa, arestas marcadas): porta traseira e dianteira verticais até a cintura (o quadro da janela e as
  colunas ficam na carroceria, como no corte do Meshy); cintura do para-lama e cowl; lateral do capô; frente do para-lama na borda do
  farol, do chão ao capô; frente do capô 12 mm acima dos faróis; laterais da tampa, fundo no topo do para-choque e frente no vinco do
  teto. Cada face vai para a peça pela **região do centro** (separar por componente ligado vazava pelo poço da roda); `split_edges`
  entre peças; a borda marcada recua meia fresta (4 mm no total) e ganha a aba escura. Saia reta: some o que fica abaixo de z = 0,30
  entre as caixas de roda e entra uma tira pintada que segue a chapa, de 0,30 a 0,24, enrolando para dentro. Lábio das caixas de roda:
  meio tubo a raio da roda + 8,5 cm, 6 mm para fora e 12 mm para dentro. O UV e a orientação do Meshy ficam (um `recalc_face_normals`
  na casca aberta virou 82% da porta para dentro, manchas pretas); só as faces novas são orientadas pelo lado de fora.
- **`vedacao_vidros.py` (ganhou três coisas):** *vidro liso*, a face de fora de cada vidro recebe uma superfície cúbica ajustada
  (robusta, 6 mm) e todos os vértices do vidro vão para ela, a face de dentro na espessura mediana (classificados pela normal das faces,
  não pelo desvio: pelo desvio a face de fora amassada caía no nível da de dentro e o vidro virava cacos); *passar a ferro*, chapa que
  invade o vidro vai para a faixa debaixo da borracha (0,3 da meia largura), vidro que passa da curva volta para dentro, o que fica acima
  da borracha desce para baixo dela, e chapa pintada bem dentro do vidro (o divisor serrilhado que o Meshy pintou no vidro da porta) é
  apagada; *borracha larga nos vidros fixos* (`--max-cm-fixo 2.5`: para-brisa e vidro traseiro, 5 cm, a borda do Meshy ali tem escada de
  5,5 cm). Nivelar a faixa inteira em volta do vidro pela mediana achatava o friso da cintura e o reflexo mostrava manchas: não fazer.
  A projeção das colunas A e B numa superfície regrada entre as borrachas (`--colunas`) ficou desligada: de perto saía como adesivo.
- **`alisar_pecas.py`:** normal ajustada que vira mais de 60 graus da normal real não vale (num canto do teto aparecia uma mancha
  refletindo o chão); acima da cintura aceita desvio de 25 mm (`--robusto-cima`, colunas e quadros não têm detalhe a preservar); e as
  quatro diagonais do plano do chão (colunas A e C, cantos). Tem que rodar **depois** da vedação: a malha reconstruída não tem normais
  próprias, e normais calculadas antes de a vedação mexer na chapa viravam manchas escuras em volta dos vidros.
- **`pele_de_dentro.py`:** a chapa pintada duplicada 1,5 cm para dentro e virada (MI_DNVao), 2,5 cm longe de toda borda, só abaixo da
  cintura (o kit põe o forro em cima; nas colunas finas ela saía por fora como lasca escura, e isso era a maior parte dos borrões),
  sem as faces que viram com o deslocamento. É o último passo porque a vedação mexe na chapa.
- **Resultado no Cuiabano v2** (`meshy/previas/cuiabano-v2/cirurgia-*.jpg`): frestas retas nas portas, no capô e na tampa, saia reta,
  lábios limpos nas quatro caixas de roda, capô, portas, para-lamas e lateral lisos, vidros lisos. O que ainda é do Meshy e aparece de
  perto: os quadros dos vidros e as colunas A e B (retalhos entre duas borrachas), a base do para-brisa e a borda do teto.
  Próximo passo, se o Felipe ainda vir borrão: refazer só a parte de cima (colunas, quadros dos vidros e borda do teto) com superfícies
  limpas no estilo quadrado do Gol, mantendo o Meshy abaixo da cintura.

## carroceria_limpa/ (28/10/2026)

Refaz a lataria de um carro do Meshy como **superfícies limpas**, usando o Meshy só como molde. Decisão do Felipe de 28/10/2026, depois
de três rodadas de remendo na malha do Meshy (alisar, soldar rachas, borracha nos vidros) que melhoravam o reflexo mas não a forma:
a malha do Meshy é uma escultura escaneada, com ondas de 30 a 50 cm, bordas em escada e frestas tortas, e remendo não chega a carro de
estúdio. Tudo o que sai daqui é geometria feita por script, CC0 do estúdio; do Meshy ficam só retrovisores, placas e rodas.

```
python -I ferramentas/carroceria_limpa/gerar.py -- --corte veiculos/meshy-conta/quebravel/<id> --id <id> --out <pasta>
```

Sai um `<id>.glb` no formato do corte do `carro_quebravel.py` (mesmos nomes de peça e de material), que entra direto no
`carro_completo.py` e na cadeia do Detonauto. ~3 min na CPU. Três passos, cada um um script da pasta:

1. **`medir.py`:** mede a casca do Meshy por raios numa grade de 1 cm nas 4 vistas (lateral, topo, frente e traseira), guardando
   a profundidade, o material e o objeto atingidos (`campos.npz`).
2. **`corpo.py`:** ajusta um polinômio de poucos termos (mínimos quadrados robustos, o que foge mais de 2 cm pesa pouco) a cada região:
   lateral baixa (x⁴ z³), caixa de vidros acima da cintura (x³ z²), capô, para-brisa, teto e vidro traseiro (x² y⁴, pares em y, com
   mistura suave de ±8 cm nas fronteiras), frente e traseira (z² y⁴). As fronteiras saem das caixas do mapa (para-brisa, vidro
   traseiro) e do próprio campo (bico do capô, vinco da traseira, linha de cintura pela base do vidro lateral). Cada seção transversal
   nasce dessas superfícies com os vincos no lugar: fundo (saia, topo do para-choque ou arco da caixa de roda), cintura com o degrau
   de 3 cm do vidro, borda do teto ou ombro do para-lama, cada um com o seu raio (1,2 cm, 2,5 cm, 4 cm). O loft ao longo de x tem
   seção a cada 2 cm e 56 pontos por meia seção, com os vincos em índices fixos; cada fileira termina onde encontra a superfície da
   frente ou de trás. Os vidros vêm das máscaras de material do Meshy (abertura de 10 cm na lateral, para a lasca do para-brisa vista de
   lado não entrar; casco convexo e alisamento de 4 cm), um contorno por janela.
3. **`malha.py`:** monta no Blender: loft espelhado; tampas da frente e de trás como grade (y, z) com linhas nas bordas dos bolsos dos
   faróis, lanternas, grade e placa (profundidade do mapa), costurada ao loft; vidros pela máscara, com a borda encaixada no contorno,
   rebaixo de 5 mm e borracha de 2,4 cm sobre a borda real; cortes dos painéis por planos limitados a uma região (`cortes.py`:
   portas com o quadro paralelo à coluna A, capô com a lateral no para-lama e a traseira no cowl, para-lamas até a cintura e o cowl,
   tampa traseira até o vinco do teto e as laterais a 60 cm do centro) com fresta de 4 mm e aba escura de 1,2 cm; pele de dentro de 1,5
   cm (`MI_DNVao`, que o `kit_to_detonauto.py` tira nos vãos do kit); UV simples; e os detalhes paramétricos (`detalhes.py`):
   para-choques de plástico varridos em planta, maçanetas, limpadores, faróis e lanternas com moldura cromada.

O que o Meshy ainda dá: as medidas e as caixas do mapa, os contornos dos vidros, retrovisores, placas e rodas. O resto do carro não
depende mais dele. Serve para os outros carros do lote: é só rodar sobre o corte de cada um (as caixas do mapa e as medidas vêm do
`carro_quebravel.py`); van, picape e sedã vão precisar de ajuste nas fronteiras das regiões do topo.

Prévias em `meshy/previas/cuiabano-v2/cuiabano-v2-carroceria-limpa-*.jpg`.


## Gol Quadrado do Sketchfab: a cadeia sem Meshy (29/10/2026)

O Felipe quer o carro de teste **perfeito** e parecido com o modelo brasileiro de referência; a cirurgia no Meshy chegou ao limite
(colunas e quadros dos vidros). O Cuiabano passou a ser um carro modelado por gente: **"Gol Quadrado" por coptrum (Sketchfab, CC BY
4.0)**, `veiculos/sketchfab/gol-quadrado-coptrum__93858a6f970043978ba798ad430871e9.glb` (1,2 MB, 3 objetos: carroceria, vidros,
rodas+assoalho; baixo polígono, chapa limpa, sem logo). O Meshy fica no acervo (`meshy-conta/quebravel/hatch-quadrado-v2/`).

    python -I ferramentas/sketchfab_preparar.py -- <scene.gltf> <pasta>/gol-quadrado.glb "Object_3,Object_5,Object_7" 3.81 1.36 0.06
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/gol-quadrado.glb --out <corte> --id gol-quadrado --portas 2 \
        --sem-rotulos --manter-normais --mapa veiculos/sketchfab/quebravel/gol-quadrado/gol-quadrado_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/gol-quadrado.glb <corte>/gol-quadrado.glb
    python -I ferramentas/carro_completo.py -- --corte <corte> --id gol-quadrado --out <kit> --epoca 80

- **`sketchfab_preparar.py` (novo):** desparenta os objetos (matriz do mundo copiada), acha a frente e o eixo do carro por PCA, centra
  entre os eixos e em y, põe o chão em z=0, **estica a carroceria acima do eixo** até a altura real (1,36 m) para as rodas ficarem
  redondas, adensa (aresta máxima 6 cm) e junta num objeto só com os materiais `pintura`, `vidro`, `pneu` e `chassi` por ilha: as
  janelas por regra (ilha estreita e alta, acima de 0,75 m antes do estiramento, em pares espelhados) e as rodas por raio. Grava
  `<saida>_medidas.json` (vidros, rodas, retrovisores, peças soltas, eixos, caixa). Desde a noite de 29/10 recalcula as **normais por
  ângulo** (7º argumento, padrão 30°): aresta mais dobrada fica viva, o resto liso. Sem isso, o vinco da tampa sob o vidro traseiro
  e a saia refletiam o céu em manchas serrilhadas (o `bmesh` do adensamento perde as normais do arquivo); o corte precisa de
  `--manter-normais` para levá-las adiante.
- **`carro_quebravel.py` ganhou:** `--sem-rotulos` (a classificação pela textura não serve numa pintura clara: só o mapa manda);
  `take: "material"` com `material: vidro|pneu|chassi|luz|cromado` (atributo `cq_mat` criado dos materiais do arquivo; os materiais
  de entrada com nome igual aos nossos viram `entrada_<nome>`); `"rodas"` no mapa (centro, raio, y_dentro/y_fora, raio do aro) quando
  o detector erra; e, na noite de 29/10, o **vidro por ilha**: cada ilha ligada do material vai inteira para a caixa que contém a
  maior parte dela (a caixa do vidro traseiro roubava o canto do vidro de quarta e a borda saía em zigue-zague), e uma ilha pequena,
  paralela e 8 mm ou mais atrás da maior (a aba do caixilho que o autor pintou como vidro) sai do modelo.
- **`borracha_vidro.py` (novo):** borracha preta em volta de cada vidro a partir do **laço real da borda** da face de fora (não da
  rasterização, que arredondava os cantos): 3 fileiras ao longo da bissetriz no plano, projetadas na chapa pelo raio na normal do
  vidro, 1,5 mm acima e perfil de 4 mm; 1,6 cm nos vidros de porta, 2,4 cm nos fixos; dona é a porta, a tampa ou a carroceria;
  espigões de rachas internas (ida e volta no laço) são tirados. A `vedacao_vidros.py --so-borracha` faz só a borracha, sem alisar
  nem passar a ferro (no Gol o vidro já é limpo e o alisamento o estragava).
- **`carro_completo.py` ganhou** (tudo medido na casca, vale para qualquer carro): `z_casca(x, y)`; o encosto do banco de trás baixa
  até caber sob o vidro traseiro deitado, e os encostos de cabeça saem se não cabem (apareciam pelo vidro do hatch); a soleira fica
  rente à chapa logo acima dela (abaixo da porta a casca do Gol não existe); o bocal do tanque fica 4 cm por dentro da lateral; o forro
  da caixa de roda para 1,5 cm dentro do para-lama (o pneu do Gol passa 8 cm da lataria); `aparar_expostos` apaga, acima da cintura,
  toda face do kit de onde dois raios escapam sem bater na casca (colunas do vão e acabamento da coluna A saíam por fora de uma coluna
  mais estreita que a janela); **`saias()`**: chapa pintada sob cada para-choque (na borda de baixo dele, inclinada 12°), lateral até
  a caixa de roda e a soleira continuada fora do vão da porta; e `aparar_sob_a_saia` apaga o que ficou além desses planos abaixo da
  saia (radiador, travessa e assoalho do porta-malas apareciam por baixo).
- **No Detonauto:** `kit_to_detonauto.hidden_paint_faces` só apaga faces de pintura que olham para o meio da caixa do kit (a coluna A
  por fora olhava para o retrovisor e sumia); o `glb_texturas.py` trata tinta de pouca saturação (a do Gol é quase branca) como tinta
  trocável; `wheels.json` leva `hub_y_cm` (62,5 cm no Gol) e o `montar-cuiabano-completo.ps1` aceita `-Id` e `-Fonte`.
- **Saída (29/10):** `veiculos/sketchfab/quebravel/gol-quadrado/` (32 peças, ~253 mil triângulos, mapa feito à mão com as medidas
  do preparo: entre-eixos 2,386 m, roda 27,15 cm, cintura 0,907 m) e `veiculos/sketchfab/completo/gol-quadrado/` (kit época 80, 79
  peças). Prévias em `veiculos/sketchfab/previas/gol-quadrado/`.

### detalhes_na_casca.py (29/10/2026, tarde)

O Felipe aprovou o rumo ("está melhorando") e pediu os faróis, a grade e as lanternas da `carroceria_limpa/` nesta casca, e o que mais
desse para melhorar. O modelo baixo polígono trazia tudo isso como placa lisa. O passo roda depois da `borracha_vidro.py` e antes do kit:

    python -I ferramentas/detalhes_na_casca.py -- <corte>/gol-quadrado.glb <corte>/gol-quadrado.glb [--sem-friso] [--sem-faixa]
        [--sem-limpador] [--sem-macaneta] [--sem-miudezas] [--z-friso 0.58] [--z-faixa 0.42]

- **Faróis e lanternas refeitos** na caixa medida das faces `luz` da peça: moldura preta de 8 mm na boca do bolso, lente 4 mm à
  frente (convexa de leve), paredes para trás tapando o bolso; a lanterna traseira em três segmentos (ré, seta, freio) separados por
  divisórias pretas. No jogo a lente inteira é o material da lanterna (`kit_names.py`), por isso só `luz` e `chassi`.
- **Grade:** moldura preta, fundo recuado 5 cm, 4 palhetas horizontais e 2 travessas verticais.
- **O que o modelo não tinha:** duas palhetas do limpador deitadas no para-brisa (paralelas, descansando para o lado do carona),
  maçanetas nas portas, friso lateral preto a 58 cm cortado por peça (o trecho da porta vai com a porta), faixa de borracha na face
  dos para-choques (desviando da placa da frente), retrovisores refeitos (caixa arredondada preta com o espelho atrás e a haste até a
  porta), tampa do tanque na quarta traseira direita e antena no para-lama esquerdo.
- **Normais:** as peças que só ganham geometria mantêm as normais de canto do corte; faróis, lanternas, grade e retrovisores são
  refeitos e recebem normais por ângulo (30°). Tudo entra nas peças que já existem, com os materiais do corte: a cadeia do Detonauto
  (amassado, `kit_to_detonauto.py`, kit) roda igual, conferida aqui.
- Prévias: `veiculos/sketchfab/previas/gol-quadrado/gol-quadrado-detalhes.jpg` e as 4 vistas refeitas.

#### Rodada "até o carro perfeito" (29/10/2026, tarde)

Pedido do Felipe: "faça o que ainda dá para melhorar". Entrou no `detalhes_na_casca.py`:

- **Frisos nas lentes:** barras de 1,5 mm (verticais no farol, horizontais na lanterna). A lente do jogo é opaca e brilhante, e um
  refletor por dentro não apareceria; o relevo é o que lê como farol.
- **Seta âmbar e ré branca de verdade:** os segmentos da lanterna saem nos materiais `luz_ambar` e `luz_branca` (cor de prévia no
  GLB). No Detonauto, `kit_names.py` mapeia para `MI_DNLanternaAmbar<Modelo>` e `MI_DNLanternaBranca<Modelo>`, que o
  `import_kit_car.py` cria da lente do cupê com outro tom; o freio continua `MI_DNLanternaTraseira<Modelo>`.
- **Para-choques de plástico preto** (o Gol quadrado de série), com os retalhos de chapa pintada da carroceria que ficam dentro do
  volume do para-choque também pretos (só faces inteiras dentro, 1,5 cm abaixo do topo: a borda de cima fica reta). A placa continua
  no material de placa. `--para-choque-pintado` mantém a cor do carro.
- **Suavização das facetas (testada e descartada):** `sketchfab_preparar.py` ganhou um 8º argumento, passos de Taubin nos vincos
  suaves (padrão 0). Com 3 e 12 passos, e com arestas vivas a 15° em vez de 30°, a quarta traseira e a coluna C ficaram iguais: a
  ondulação é um quadrilátero torcido do modelo (duas faces não coplanares com normais interpoladas), e só remodelar a região
  resolveria. Fica como está: no jogo, à distância da câmera, não aparece.

### assar_desgaste.py (29/10/2026, tarde): a textura que faltava

O Felipe mostrou um print com Gol, Fusca, Kombi e Palio "de verdade" e perguntou por que o nosso não chega lá. A resposta é a
textura: o que faz um carro de jogo parecer real à distância é a cor assada (oclusão nas frestas e nos cantos, sujeira que sobe
do chão, variação leve de chapa), não a geometria. O Gol do Sketchfab vinha com a UV colapsada (116 mil faces num texel) e uma
textura quase branca de 512 px. Este passo roda depois do `detalhes_na_casca.py`:

    python -I ferramentas/assar_desgaste.py -- <corte>/gol-quadrado.glb <corte>/gol-quadrado.glb [--tamanho 2048] [--amostras 32] [--sujeira 0.22]

1. **Faces viradas:** a face cuja normal entra na folga da chapa dupla (o raio pela normal bate em algo a menos de 2,5 cm) e cujo
   sentido contrário sai livre está virada e é invertida; a pele de dentro, que olha para a cabine, fica, e a chapa sob um friso ou
   uma maçaneta (bate perto nos dois sentidos) também: era ela que, virada por engano, assava escura em manchas (apontado pelo
   Felipe em 29/10). (O `recalc_face_normals` do bmesh virava metade da chapa
   e a oclusão saía em camuflagem.) Normais por ângulo de novo onde mexeu.
2. **UV nova, um atlas só:** projeção em caixa (cada face vai para o plano da sua normal dominante), uma carta por peça, eixo e
   lado (de fora / de dentro, para a pele de dentro não se sobrepor à chapa do outro lado), cartas empacotadas em prateleiras na
   mesma densidade (~180 texels por metro em 2K). Os operadores de UV do Blender não rodam fora do editor com várias peças.
3. **Oclusão assada no Cycles (CPU)**, peça por peça (com todas selecionadas o bake de uma apagava o da anterior), com um chão
   para a saia e os para-choques escurecerem perto do solo. A altura de cada texel sai da própria carta (v = z nas cartas de lado).
4. **Composição:** 0,96 x oclusão (0,70 + 0,30 x ao^1,2) x sujeira (até 16% entre 48 cm e 20 cm do chão, com manchas suaves) x
   grão fino; pele de dentro 30% mais escura. Sai `<id>_desgaste.png` (2048 px) e ela vira a cor de `pintura`, `luz`, `cromado`
   e das lentes; o `chassi` multiplica a mesma oclusão pelo preto.
5. No jogo, `glb_texturas.py` tira essa textura do GLB (`T_Cuiabano_C`) e a tinta trocável multiplica por cima: a cor continua
   livre, com o desgaste. O `Image_0.jpg` passou a ser reencodado (antes gravava os bytes PNG do GLB com nome .jpg).

O que ainda separa do print: lá os modelos têm textura pintada por gente (ou foto), com riscos, decalques e cada detalhe da
frente desenhado; aqui a textura é só oclusão + sujeira procedural. O próximo degrau seria uma textura pintada (Meshy retexture
custa créditos; a economia vai até 23/11) ou riscos e decalques procedurais.

#### Correções de 29/10 (noite): manchas e vidro vermelho

O Felipe apontou manchas que ainda sobravam e um vidro pintado com a cor do carro.

- **Vidro vermelho:** o Gol traz, no plano da janela da porta, uma chapa pintada do corpo a 2 ou 3 mm do vidro (na esquerda na
  frente dele, na direita atrás). O `detalhes_na_casca.py` agora apaga toda face pintada a menos de 1,5 cm de um vidro e em cima
  dele (a reta até o vidro segue a normal do vidro; a moldura em volta fica): 1 510 faces no corpo e 227 na tampa.
- **Manchas (retângulos escuros na porta e na quarta):** as cartas da UV juntavam todas as faces de uma peça com a mesma normal
  dominante; faces em profundidades diferentes (o friso sobre a porta, a chapa atrás de outra) caíam umas sobre as outras no atlas
  e o bake de uma escurecia a outra. Agora cada carta é uma ilha ligada por aresta (46 mil cartas, 107 texels por metro em 2K).
- **Faces dos detalhes:** o retrovisor direito e partes das maçanetas saíam com a normal invertida (o `recalc_face_normals` não
  orienta faces soltas). Toda face nova é orientada para longe de um ponto de dentro (o centro da caixa, o eixo do friso, o fundo
  do bolso do farol).

#### Carro novo, vidro de verdade, luzes e rodas (29/10/2026, noite)

Pedidos do Felipe: "falta a placa", "a saia vermelha embaixo era melhor sem", "teste com outra cor", "os vidros deveriam ser
mais transparentes (película depois, no jogo)", "não tem cara de carro novo, as cores estão opacas", "pneus, rodas, lanternas e
sinaleiras mais realistas" e "o vidro perto do retrovisor ainda está pintado".

- **Placa:** a face da frente de `plate_front` e `plate_rear` vira o material `placa` (no jogo, `MI_DNPlacaCoupe`), em branco e
  sem letras (placa real é proibida), com moldura preta de 1 cm e dois parafusos; o resto do suporte fica preto.
- **Saias:** no `carro_completo.py` elas passaram a ser `chassi_graxa` (escuras) e recuadas 6 cm da borda do para-choque: leem
  como a sombra do fundo e ainda tapam radiador e travessa.
- **Vidro de duas faces:** a espessura de 6 mm do vidro saía com a face de trás em `chassi`, preto opaco, e a janela parecia
  fumê fechado. A face `chassi` paralela a um vidro e até 1,2 cm atrás dele vira vidro (11 mil faces nos 6 vidros).
- **Quebra-vento:** o triângulo entre a janela da porta e a coluna A era chapa pintada. É cortado por planos (frente da janela,
  coluna A paralela à borda do para-brisa medida na chapa, cintura) e por outros 1,2 cm para dentro: o miolo vira vidro e o anel,
  borracha.
- **Faróis:** a lente passou a ser vidro com frisos, e atrás dela um refletor acetinado (`refletor`, pirâmide rasa) com a lâmpada.
  **Lanternas:** cada segmento (freio `luz_vermelha`, seta `luz_ambar`, ré `luz_branca`) tem refletor atrás e cor mais viva.
  **Sinaleiras:** piscas âmbar com moldura nas pontas da barra do para-choque da frente.
- **Carro novo:** `assar_desgaste.py --estado novo` (padrão; `--estado usado` volta ao desgaste anterior): a oclusão só escurece
  as frestas (0,80 a 1,0), sujeira 3%, sem grão; a pintura da prévia com verniz cheio (rugosidade 0,16, verniz 1,0) e as lentes
  lisas. A textura multiplica a cor de cada material em vez de substituí-la (as lentes eram brancas).
- **Rodas (`rodas_kit.py`):** aro de aço prata de fábrica (antes cinza chumbo), calota e liga mais espelhadas, pneu de borracha
  nova (preto fosco, não chapado). Testes do `test_rodas_kit.py` passando.
- **Cores:** as seis cores de `Data/Paints.csv` testadas com a `Paint.png` que o jogo usa (`gol-quadrado-cores.jpg`): a lataria
  inteira pega a cor, plásticos ficam pretos, placa branca, lentes nas suas cores.

#### Placa, para-lamas e pintura de carro novo (29/10/2026, noite)

Pedidos do Felipe: "a placa dianteira ainda está estranha, os para-lamas também, pesquise como é o modelo real" e "a pintura ainda
está opaca". Referência: fotos do Gol GL 1991-94 e do Gol 1985 (odg.com.br): placa de 40 x 13 cm no meio da face do para-choque, na
metade de baixo; caixas de roda redondas e rentes à lateral, sem alargador.

- **Caixas de roda redondas (`detalhes_na_casca.py`, `--r-arco 0.34`, `--sem-arco-redondo`):** o modelo trazia o arco como um
  polígono de 6 ou 7 lados, apertado na frente de baixo (2 cm do pneu) e com a borda saltada 2 a 4 cm para fora. Por ângulo em volta
  do cubo (do `_mapa.json`) mede-se a borda vista de lado e o plano da lateral 8 a 12 cm para fora dela; um campo de deslocamento
  leva a borda a um círculo de 34 cm e a pele que passa do plano da lateral volta para ele. O campo só depende da posição, então a
  costura entre peças fica fechada; nos vértices que andaram as normais passam a ser por ângulo (as do arquivo desenhavam o arco antigo).
- **Abas soltas:** tiras pretas da caixa de roda original desciam a 15 cm do chão e saíam 3 cm da lateral, na frente da roda da
  frente e atrás da de trás (de frente pareciam apara-barros pendurados): 72 faces fora.
- **Face do para-choque da frente (`--sem-face-para-choque`):** a barra tinha 8 cm e, embaixo, a chapa fugia 11 cm para trás em
  rampa. O campo empurra a parte de baixo até 1,2 cm atrás da barra, arredondando nos últimos 5,5 cm; o rebaixo da placa antiga usa
  a fileira de fora, e a mudança some no canto (0,58 a 0,72 m do meio). Normais por ângulo no plástico.
- **Placa da frente refeita (`--z-placa 0.355`, `--placa-original`):** era 40 x 10 cm (achatada) num suporte 10 cm fundo, e uma
  folha solta da carroceria logo abaixo fazia o "bloco escuro". Agora: placa de 40 x 13 cm em branco, centrada, de z 0,355 a 0,485,
  0,8 cm à frente da barra, sobre suporte preto que tapa o rebaixo antigo, com moldura e parafusos. A faixa do para-choque desvia dela.
- **Saias (`carro_completo.py`):** sem as laterais até a caixa de roda e a da frente 20 cm para dentro de cada lado (de lado
  penduravam como apara-barro).
- **Pintura "opaca":** duas causas. (1) A textura de carro novo escurecia 10 a 20% a chapa aberta: a lateral vê o chão e a oclusão
  dela fica perto de 0,5, abaixo do limite de 0,75; agora a chapa com oclusão de 0,40 para cima já sai com a cor cheia (portas,
  para-lamas e capô em 253 de 255). (2) As prévias refletiam só um céu liso e um chão vazio: o verniz não tinha o que mostrar. As
  prévias passaram a usar um HDRI de rua (Poly Haven, CC0) como numa foto.
- **Acabamentos:** o Detonauto ganhou `Data/PaintFinishes.csv` (sólida, metálica, perolizada, fosca, acetinada); as prévias
  `gol-quadrado-acabamentos.jpg` mostram cada um com os valores da tabela.

#### No jogo: placa gigante e farol preto (29/10/2026, noite)

O Felipe montou o Cuiabano no PC e viu a placa cobrindo a frente e a traseira e os faróis pretos, diferente das prévias.

- **Placa:** o `kit_to_detonauto.py` do Detonauto ainda fazia a "placa lisa" do Meshy: procurava o branco da placa na textura da lataria
  e crescia a placa até ele. Na textura de carro novo (tinta em branco, a cor vem do material) toda a lataria é branca: a placa saía
  com 91 x 32 cm na frente e 60 x 39 cm atrás. Placa modelada no acervo (material `placa`) agora passa como veio.
- **Farol:** a lente era vidro transparente na frente de um bolso escuro; no Unreal o bolso fica sem luz e o farol saía preto. A
  prévia escondia isso porque clareava a lente só nela. Agora a lente do farol é `lente_farol` (prata claro, um pouco metálica,
  envernizada, opaca, com os frisos; no jogo `MI_DNLenteFarol<Modelo>`) e o refletor é prata acetinado de pouco metal (no jogo
  também). **Regra:** a prévia usa os mesmos valores do jogo, sem truque só nela.
- **`previa_carro.py` (novo, era o rascunho das prévias):** o corte + o kit + as rodas de kit, a pintura como o jogo faz e, com
  `HDRI=`, uma rua em volta. Uso no cabeçalho do script.

## Receita: um carro do Sketchfab até o Detonauto (o caminho do Gol Quadrado, 29/10/2026)

Para cada carro nacional, uma sessão. Os passos, na ordem:

1. **Referência:** o carro real de cada nome do jogo está na ficha privada do Speed Tchê (`Felipebonamigo/SpeedTche`,
   `docs/CARROS-NACIONAIS.md`). O nome real nunca vai para tela, loja nem para o texto deste acervo, que é público (só o título que o
   autor deu ao modelo, no crédito que a licença pede). Fotos reais para comparar: frente, lado, traseira, detalhes (placa, arcos,
   faróis, lanternas, para-choques).
2. **Modelo:** buscar na API do Sketchfab (`api.sketchfab.com/v3/search?type=models&downloadable=true&q=...`, a sessão da nuvem já
   tem a credencial pelo proxy) modelos **feitos por gente**, com licença **CC BY ou CC0** (nunca NC, ND nem "Standard"/pago), chapa
   limpa, vidros separados, sem logo, emblema, nome nem placa real. Mostrar 3 a 5 candidatos ao Felipe com miniatura, licença,
   autor e triângulos; **o Felipe escolhe**. Baixar por `/v3/models/<uid>/download`, guardar o `.glb`/zip original e o `license.txt`.
   Comprar, logar ou aceitar termos: só o Felipe. Meshy só em último caso, perguntando antes com o custo (economia até 23/11).
3. **Preparar e cortar:** `sketchfab_preparar.py` (objetos, comprimento e altura reais, frente +X, chão em z=0, normais por ângulo),
   um `_mapa.json` feito à mão (rodas, portas, capô, tampa, para-choques, vidros, luzes, placas) e `carro_quebravel.py --sem-rotulos
   --manter-normais --mapa ...`, depois `borracha_vidro.py`.
4. **Detalhes:** `detalhes_na_casca.py`. Várias medidas ali são do Gol (quebra-vento, sinaleiras no para-choque, antena, altura do
   friso e da faixa): use as opções que existem e ponha opção nova para o que mudar, **sem mudar o resultado do Gol** (rodar o Gol de
   novo e comparar). Arcos redondos, placa 40 x 13 cm, lente de farol clara e para-choques pretos servem para todos.
5. **Textura e kit:** `assar_desgaste.py --tamanho 2048 --amostras 32` e `carro_completo.py --corte ... --epoca <80|90|2000>`.
6. **Prévia e conferência:** `previa_carro.py` com o HDRI da rua, nas 4 vistas, closes de frente, lado e traseira, e as cores e
   acabamentos; comparar com as fotos reais e **olhar cada imagem antes de dizer que ficou bom**. No Detonauto, a cadeia de
   conferência (`make_crush_channels.py`, `kit_to_detonauto.py`, `glb_texturas.py`, `kit_completo_to_detonauto.py`).
7. **Registro:** `catalogo.csv`, `CREDITOS.md`, aba "Modelos 3D" do doc do estúdio e `docs/licencas.csv` do Detonauto, no mesmo dia.
   Arquivo nenhum acima de 50 MB.
8. **No jogo:** o que só o PC faz (importar, compilar, jogar) vai num texto pronto para o Felipe passar à sessão local, com as
   capturas pedidas; o veredito visual é a captura do jogo, não a prévia.
- **Placa de trás e luzes iguais (29/10, noite):** a placa de trás também passou a ser a brasileira de 40 x 13 cm no meio da tampa
  (era 30 x 12), pela mesma função da da frente (`--placa-tras-original` mantém a antiga). Faróis e lanternas de cada par usam a
  união das duas caixas, espelhada: no modelo a lanterna esquerda tinha 24 cm e a direita 28 (`--luzes-como-vieram` desliga).

## casca_impressao.py (30/10/2026)

Para modelo do Sketchfab que é só uma **casca maciça de impressão 3D** (STL com a lataria de ~3 cm de parede, janelas e caixas de roda
furadas, sem vidro, sem roda, sem assoalho e sem material). Entrega os 3 objetos que a `sketchfab_preparar.py` espera (`carroceria`,
`vidros`, `rodas`), sem mexer na cadeia do Gol:

    python -I ferramentas/casca_impressao.py -- --entrada <scene.gltf> --out <pasta>/<id>_casca.glb --comp <m> [--razao 0.3]
        [--aro aro_liga14] [--pneu pneu_p185_60] [--frente -y] [--so-casca]

- Junta, solda, tira ilhas soltas, põe a frente em +X e reduz (colapso).
- Vidros por raios numa grade de 5 mm: janela lateral é o que o raio atravessa de lado a lado acima de 0,55 m; para-brisa e vidro
  traseiro, o que o raio de cima atravessa sem se ligar à borda da grade. A superfície de cada vidro é um polinômio ajustado ao anel
  de chapa em volta (robusto), 4 mm para dentro, 5 mm de espessura.
- Rodas do `rodas_kit` no centro do círculo ajustado a cada caixa de roda, 2,5 cm por dentro da lataria; a casca sobe até o pneu
  tocar o chão. Assoalho plano entre as soleiras (material de chassi na preparação).
- Primeiro uso: candidato do Barão (sedã), 30/10/2026. Entre-eixos e altura medidos batem com a referência, e os 8 vidros saem
  certos. A chapa desse modelo vem ondulada no próprio arquivo, e o `alisar_lataria.py` piorou nos dois testes (com a camada de
  3 cm ele mistura as duas peles; com 1,2 cm continua enrugando). Uma casca assim pede superfície refeita, como na `carroceria_limpa/`.
