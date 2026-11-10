# Lataria por molde

Carroceria **própria**, de superfície limpa, feita por script a partir de uma ficha de texto. Substitui o caminho antigo (modelo de
terceiros esticado, cortado por planos e vestido com caixas), que deixava facetas, lanterna saltada, borracha fora do vão e arco de
roda serrilhado. Método aprovado pelo Felipe em 10/11/2026 (Detonauto, `docs/roteiro-do-jogo.md`, seção 6).

O modelo de terceiros serve **só de régua**: `medir_regua.py` imprime cotas (comprimento, alturas, larguras por estação), que vão
arredondadas para a ficha. Nenhum vértice, face ou textura dele entra no resultado. Tudo o que sai daqui é CC0 do estúdio.

## Um comando

```bash
python -I ferramentas/lataria_molde/reconstruir.py cuiabano            # ficha -> carro, kit completo e portão (código 1 se reprova)
python -I ferramentas/lataria_molde/reconstruir.py cuiabano --previa   # mais as 4 vistas da folha, em Cycles, de um lado só
```

Na nuvem do Detonauto, o Python com o Blender é `Tools/Blender/blender-nuvem.sh <script> -- <argumentos>`.

Saída em `veiculos/proprios/quebravel/<id>/` (o mesmo formato do corte do `carro_quebravel.py`, para a cadeia do jogo não mudar):
`<id>.glb` (LOD de perto), `<id>_lod1.glb`, `<id>_lod2.glb`, `<id>_mapa.json`, `<id>_wheels.json`, `<id>_pecas.json`,
`<id>_molde.json` (triângulos por peça, materiais, densidade do UV) e `<id>_portao.json` (as medidas do portão). O kit completo vai
para `veiculos/proprios/completo/<id>/`.

## Como funciona

1. **Gabarito** (`gabarito_hatch.py`): uma gaiola de quadriláteros com os laços dos vãos já no desenho. Três remendos costurados:
   a lateral baixa (22 colunas × 8 fiadas, com os dois arcos de roda como buracos redondos e um anel em volta), a lateral da cabine
   e a faixa de cima (frente, capô, para-brisa, teto, vidro traseiro, traseira). Cada face sabe de que peça é.
2. **Superfície-mestra** (`construir.py`): a gaiola inteira subdividida (Catmull-Clark). Toda peça é assentada nela e herda a
   normal dela, então o reflexo atravessa as frestas sem degrau.
3. **Peças**: cada peça é o pedaço da gaiola da sua região, subdividido sozinho. A borda vira uma curva lisa, igual nos dois
   vizinhos do corte; os cantos arredondam com o raio da ficha; a borda recua meia fresta (2 mm de cada lado = 4 mm).
4. **O que nasce da borda**: a aba da chapa, a pele de dentro (a peça fica fechada), a borracha do vidro (perfil varrido na borda do
   vão), o bolso do farol e da lanterna (refletor com frisos, lâmpada e a lente, que é a própria superfície), o lábio do arco e a
   caixa de roda.
5. **O resto**: para-choques (perfil varrido na planta do carro), grade, placas, retrovisores, maçanetas, limpadores, friso lateral,
   o emblema "Estilhaço" do Detonauto e as rodas de kit (`veiculos/proprios/rodas`).
6. **UV por painel** num atlas só, com a mesma densidade no carro todo; abas e peles de dentro vão para um canto reservado.

Nomes de peça e de material são os do corte de hoje (`body`, `hood`, `door_fl`, `glass_door_rl`, `headlight_left`...; `pintura`,
`chassi`, `vidro`, `cromo`, `refletor`, `lente_vidro`, `lente_vermelha`, `lente_ambar`, `lente_branca`, `placa`), para o
Detonauto receber o carro sem mexer no C++ (`Tools/Blender/kit_names.py`).

## O portão (`portao.py`)

Mede o **arquivo final**, de um lado só, sem confiar em como ele foi feito, e sai com código 1 se reprova:

| Regra | O que mede | Teto |
|---|---|---|
| P1 | face opaca vista só pelas costas de 26 câmeras em volta (no Unreal ela some); o kit completo entra de anteparo | 4 cm² por peça |
| P2 | degrau entre vizinhos de uma fresta e entre a lente e a chapa | 2 mm |
| P3 | largura da fresta entre chapas | 3 a 5 mm (mediana e 90% das medidas) |
| P4 | faceta: normal partida na pele, aresta dobrada, ângulo entre faces vizinhas | 20° (0,4% podem passar), nenhuma dobra |
| P5 | arco de roda num círculo, os quatro com o mesmo raio | 1,5 mm de resíduo |
| P6 | orçamento, sem as rodas | 200 mil triângulos, 10 materiais |
| P7 | UV da pele dentro de 0..1, sem sobrepor outra peça | |
| P8 | peças e materiais do contrato do jogo | |
| P9 | borracha do vidro encostada na chapa e no vidro | 8 mm |

O CI (`.github/workflows/portao-lataria.yml`) reconstrói cada ficha e roda o portão a cada mudança.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `fichas/<carro>.json` | a ficha de texto do carro: cotas, vincos, acabamento, rodas |
| `gabarito_hatch.py` | o gabarito do hatch de 2 portas (sem bpy) |
| `construir.py` | ficha → carro (LOD0, LOD1, LOD2) e os JSON do corte |
| `malha_util.py` | subdivisão, superfície-mestra, bordas, aba, perfil varrido |
| `portao.py` | o portão automático |
| `previa.py` | a prévia em Cycles do arquivo final, de um lado só, com as câmeras fixas da folha |
| `medir_regua.py` | imprime as cotas de um modelo-régua |
| `reconstruir.py` | o comando único |

## Carro novo

1. Rode `medir_regua.py` no modelo-régua e copie as cotas (arredondadas a centímetro) para uma ficha nova.
2. Ajuste a forma na ficha (`colunas_x`, fiadas, `vincos`) olhando a prévia; nada de editar malha à mão.
3. `reconstruir.py <carro> --previa` até o portão aprovar e a folha convencer de perto.
4. Detalhes de assinatura (grade, farol, vincos) são desenho do estúdio: silhueta parecida de propósito pode, logo, nome, grade ou
   farol de marca real não.

Outros tipos de carroceria (sedã, picape, furgão, redondo) pedem um gabarito novo ao lado de `gabarito_hatch.py`; o resto serve igual.
