#!/usr/bin/env python3
"""Lote do Meshy pela API, com teto de créditos e livro-caixa.

Fluxo em duas fases, como a regra do estúdio manda (prévia -> miniatura -> refinar):
  python3 ferramentas/meshy_lote.py preview meshy/lote-2026-10.json   # cria as prévias (20 créditos cada)
  python3 ferramentas/meshy_lote.py status  meshy/lote-2026-10.json   # acompanha e baixa as miniaturas
  python3 ferramentas/meshy_lote.py refine  meshy/lote-2026-10.json   # textura PBR das prévias aprovadas (10 cada)
  python3 ferramentas/meshy_lote.py baixar  meshy/lote-2026-10.json   # GLB + texturas para <categoria>/meshy-conta/

A chave da API vem do ambiente MESHY_API_KEY; na nuvem o proxy injeta a chave em api.meshy.ai e a
variável pode ficar vazia. Nenhuma chamada que gasta crédito passa do teto do manifesto ("teto_creditos").
Toda tarefa criada entra em meshy/livro-caixa.md com id, créditos consumidos e saldo depois.
"""
import base64, json, os, sys, time, urllib.request, urllib.error, datetime, pathlib

API = "https://api.meshy.ai"
RAIZ = pathlib.Path(__file__).resolve().parent.parent
LIVRO = RAIZ / "meshy" / "livro-caixa.md"

def req(metodo, caminho, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(API + caminho, data=dados, method=metodo)
    r.add_header("Content-Type", "application/json")
    chave = os.environ.get("MESHY_API_KEY")
    if chave:
        r.add_header("Authorization", "Bearer " + chave)
    for tentativa in range(5):
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            texto = e.read().decode(errors="replace")
            if e.code == 429 and tentativa < 4:
                time.sleep(30 * (tentativa + 1)); continue
            raise RuntimeError(f"{metodo} {caminho}: HTTP {e.code}: {texto[:400]}")
    raise RuntimeError("sem resposta")

def saldo():
    return req("GET", "/openapi/v1/balance")

def anota(linha):
    LIVRO.parent.mkdir(parents=True, exist_ok=True)
    if not LIVRO.exists():
        LIVRO.write_text("# Livro-caixa do Meshy (conta do Felipe, plano Pro)\n\nToda operação que gasta crédito entra aqui na hora, com o saldo lido pela API depois (`GET /openapi/v1/balance`).\n\n| Data (UTC) | Lote | Item | Operação | Tarefa | Créditos | Saldo depois (mensal + permanente) | Aprovou |\n|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
    with LIVRO.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")

def carrega(caminho):
    return json.loads(pathlib.Path(caminho).read_text(encoding="utf-8"))

def salva(caminho, m):
    pathlib.Path(caminho).write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def gasto(m):
    return sum(i.get("creditos_preview", 0) + i.get("creditos_refine", 0) for i in m["itens"])

def agora():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")

def fase_preview(caminho):
    m = carrega(caminho)
    for it in m["itens"]:
        if it.get("preview_id") or it.get("pular"):
            continue
        if gasto(m) + 20 > m["teto_creditos"]:
            print(f"teto de {m['teto_creditos']} créditos atingido; {it['id']} fica para depois"); break
        corpo = {"mode": "preview", "prompt": it["prompt"], "ai_model": it.get("ai_model", "latest"),
                 "should_remesh": True, "topology": "triangle",
                 "target_polycount": it.get("polycount", 20000)}
        r = req("POST", "/openapi/v2/text-to-3d", corpo)
        it["preview_id"] = r["result"]; it["preview_criado"] = agora()
        salva(caminho, m)
        print(f"preview criada: {it['id']} -> {it['preview_id']}")
        time.sleep(2)
    print("saldo agora:", saldo())

def fase_status(caminho, espera=True):
    m = carrega(caminho)
    pend = True
    while pend:
        pend = False
        for it in m["itens"]:
            for fase in ("preview", "refine"):
                tid = it.get(f"{fase}_id")
                if not tid or it.get(f"{fase}_status") in ("SUCCEEDED", "FAILED", "CANCELED"):
                    continue
                t = req("GET", f"/openapi/v2/text-to-3d/{tid}")
                it[f"{fase}_status"] = t["status"]; it[f"{fase}_progresso"] = t.get("progress")
                if t["status"] == "SUCCEEDED":
                    it[f"creditos_{fase}"] = t.get("consumed_credits", 0)
                    it[f"{fase}_thumb"] = t.get("thumbnail_url"); it[f"{fase}_urls"] = t.get("model_urls")
                    if fase == "refine": it["texture_urls"] = t.get("texture_urls")
                    s = saldo()
                    anota(f"| {agora()} | {m['lote']} | {it['id']} | text-to-3d {fase} | {tid} | {it[f'creditos_{fase}']} | {s['balance']} ({s['monthly_credits']} + {s['permanent_credits']}) | {m['aprovado_por']} |")
                    pasta = RAIZ / "meshy" / "previas" / m["lote"]; pasta.mkdir(parents=True, exist_ok=True)
                    if t.get("thumbnail_url"):
                        urllib.request.urlretrieve(t["thumbnail_url"], pasta / f"{it['id']}-{fase}.png")
                elif t["status"] == "FAILED":
                    it[f"{fase}_erro"] = (t.get("task_error") or {}).get("message")
                    anota(f"| {agora()} | {m['lote']} | {it['id']} | text-to-3d {fase} FALHOU (reembolsado) | {tid} | 0 | | {m['aprovado_por']} |")
                else:
                    pend = True
                salva(caminho, m)
        resumo = ", ".join(f"{i['id']}:{i.get('refine_status') or i.get('preview_status') or '-'}" for i in m["itens"] if i.get("preview_id"))
        print(agora(), resumo)
        if pend and espera: time.sleep(20)
        elif pend: break

def fase_refine(caminho):
    m = carrega(caminho)
    for it in m["itens"]:
        if not it.get("aprovado") or it.get("refine_id") or it.get("preview_status") != "SUCCEEDED":
            continue
        if gasto(m) + 10 > m["teto_creditos"]:
            print("teto atingido"); break
        corpo = {"mode": "refine", "preview_task_id": it["preview_id"], "enable_pbr": True,
                 "texture_resolution": it.get("textura", "2k"), "remove_lighting": True}
        if it.get("texture_prompt"): corpo["texture_prompt"] = it["texture_prompt"]
        r = req("POST", "/openapi/v2/text-to-3d", corpo)
        it["refine_id"] = r["result"]; it["refine_criado"] = agora(); salva(caminho, m)
        print(f"refine criado: {it['id']} -> {it['refine_id']}")
        time.sleep(2)

def fase_baixar(caminho):
    m = carrega(caminho)
    for it in m["itens"]:
        urls = it.get("refine_urls")
        if not urls or it.get("arquivo"):
            continue
        dest = RAIZ / it["categoria"] / "meshy-conta"; dest.mkdir(parents=True, exist_ok=True)
        nome = f"{it['id']}__{it['refine_id'][:8]}.glb"
        urllib.request.urlretrieve(urls["glb"], dest / nome)
        it["arquivo"] = f"{it['categoria']}/meshy-conta/{nome}"; it["baixado"] = agora()
        salva(caminho, m)
        print("baixado:", it["arquivo"], round((dest / nome).stat().st_size / 1e6, 1), "MB")


def fase_registrar(caminho):
    """Linhas do catalogo.csv para os modelos baixados (fonte meshy-conta, plano Pro: modelo do Felipe, gerado por IA)."""
    import csv
    m = carrega(caminho)
    cat = RAIZ / "catalogo.csv"
    existentes = {r["arquivo"] for r in csv.DictReader(cat.open(encoding="utf-8"))}
    with cat.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for it in m["itens"]:
            if not it.get("arquivo") or it["arquivo"] in existentes:
                continue
            notas = (f"gerado_por_ia: Meshy text-to-3D {it.get('ai_model', 'latest')} em {it.get('refine_criado', '')[:10]}, "
                     f"plano Pro (modelo do Felipe), tarefas {it['preview_id']} e {it['refine_id']}, "
                     f"{it.get('creditos_preview', 0) + it.get('creditos_refine', 0)} créditos, PBR 2K, "
                     f"~{it.get('polycount')} triângulos pedidos; passar por limpar_ia.py antes de entrar no jogo; "
                     f"entra na declaração de IA da Steam")
            w.writerow([it["arquivo"], it["categoria"], it["id"].replace("-", " "), "Meshy, conta do Felipe (API)",
                        "Felipe Bonamigo (conta no Meshy, plano Pro)", "Meshy Pro: propriedade privada, uso comercial",
                        "", it["jogo"] + " (reserva)", "", "3D models generated with Meshy (meshy.ai).", notas])
            print("catalogo:", it["arquivo"])

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    fase, arq = sys.argv[1], sys.argv[2]
    {"preview": fase_preview, "status": fase_status, "refine": fase_refine, "baixar": fase_baixar, "registrar": fase_registrar,
     "olhar": lambda c: fase_status(c, espera=False)}[fase](arq)
