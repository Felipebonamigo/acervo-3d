# Pedido comum das sessões de carro (29/10/2026)

Cada carro do Detonauto tem uma sessão própria do Claude. O pedido de cada uma diz o carro e a referência; o resto vale para todas:

Repositórios: esta sessão abre com `Felipebonamigo/acervo-3d`. Adicione também `Felipebonamigo/Detonauto` (add_repo, para escrever; clone ao lado, em `../detonauto` ou `../Detonauto`) e, para os carros da lista do Speed Tchê, `Felipebonamigo/SpeedTche` (só leitura). Leia antes de começar: `CLAUDE.md` dos dois repositórios, e no acervo `ferramentas/README.md`, principalmente as seções do Gol Quadrado de 29/10/2026 e "Receita: um carro do Sketchfab até o Detonauto". Siga a receita passo a passo.

Regras que não mudam (dos CLAUDE.md):
- Modelo só **CC BY ou CC0**, feito por gente (nada NC, ND, pago ou "Standard"), sem logo, emblema, nome nem placa real. No jogo o carro tem nome próprio, nunca o nome de marca ou modelo real. O acervo é público: o nome real do carro não vai em texto do acervo, só o título que o autor deu ao modelo, no crédito.
- **Mostre 3 a 5 candidatos ao Felipe** (miniatura, link, licença, autor, triângulos, o que falta) **e espere ele escolher** antes de baixar. Comprar, logar ou aceitar termos: só ele.
- Meshy só em último caso, perguntando antes com o custo (economia até 23/11/2026).
- Nenhum arquivo acima de 50 MB.
- Modelo novo entra no `catalogo.csv`, no `CREDITOS.md`, na aba "Modelos 3D" do doc do estúdio (https://claude.ai/artifact/72KXW2Tve5gB65BHD1CDp6) e no `docs/licencas.csv` do Detonauto, no mesmo dia.
- Commits pequenos, em português, no imperativo.
- **Olhe cada prévia antes de dizer que algo ficou bom.** A prévia usa os mesmos materiais e valores do jogo, sem truque só nela: no Cuiabano, uma lente clareada só na prévia escondeu que o farol saía preto no jogo.
- O C++ do Detonauto passa pela rotina `revisar-sem-compilar`, porque a nuvem não compila.

Outras sessões fazem os outros carros ao mesmo tempo, mexendo nas mesmas ferramentas (`detalhes_na_casca.py`, `carro_completo.py`, `assar_desgaste.py`, `previa_carro.py`, `kit_to_detonauto.py`, `import_kit_car.py`):
- Medida ou comportamento novo entra como opção. O resultado do Gol Quadrado não pode mudar: rode a cadeia dele de novo e compare.
- Antes de cada push, faça `git pull --rebase origin main` e resolva conflito mantendo as duas mudanças.
- O README, o `catalogo.csv` e o `docs/estado-atual.md` recebem entradas suas, sem apagar as dos outros.

Ambiente: na nuvem, `python3 -m venv venv && venv/bin/pip install bpy pillow numpy` (Blender 5.2 como módulo, Cycles na CPU). Rode os scripts com `-I` e no máximo 5 renders em paralelo. O HDRI das prévias é o "Wide Street 01" do Poly Haven (CC0); o link está no cabeçalho de `previa_carro.py`, e ele não entra no acervo.

Entrega:
1. O carro cortado e com kit completo em `veiculos/sketchfab/{quebravel,completo}/<id>/`.
2. As prévias em `veiculos/sketchfab/previas/<id>/`: 4 vistas, closes, cores e acabamentos de `Data/PaintFinishes.csv`, comparadas com fotos reais.
3. A cadeia de conferência do Detonauto passando.
4. As entradas de registro.
5. Um texto pronto para o Felipe colar na sessão local do PC: importar, compilar, jogar e tirar as capturas no jogo. O Cuiabano usa `Tools/Unreal/montar-cuiabano-completo.ps1`; se o carro precisar de um script parecido, generalize por parâmetro, sem quebrar o do Cuiabano.
6. Ao fechar cada bloco, uma linha sobre o que mudou na diversão e no visual.
