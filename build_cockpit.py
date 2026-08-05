#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cockpit de Vendas — Visão Executiva (Vendas Digital Hapvida)
Consolida KPIs dos dashboards existentes em uma página única:
  1. Vendas Digital (local: ~/vendas-deploy/index.html — RAW embutido, oficial até Jun/2026)
  2. Vendas Diária RMSP (https://vendas-diaria-deploy.vercel.app/v1.html — meta × realizado)
  3. Conversão Time (https://conversao-time.vercel.app/data/*.json.gz — leads × vidas, diário)
  4. SLA / Atendimento (https://atendimento-hapvida.vercel.app/ — DADOS embutido)

Uso:  python3 build_cockpit.py          → gera index.html nesta pasta
Preview local (não publicado): python3 -m http.server 8767 -d ~/cockpit-vendas
"""
import json, re, gzip, io, os, sys, urllib.request
from datetime import datetime
from collections import defaultdict, Counter

HOME = os.path.expanduser('~')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
VENDAS_LOCAL = os.path.join(HOME, 'vendas-deploy', 'index.html')

def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode('utf-8')

def fetch_gz_json(url):
    return json.loads(gzip.decompress(fetch(url, binary=True)).decode('utf-8'))

def balanced_json(text, start_marker, open_char='{'):
    i = text.index(start_marker)
    s = text.index(open_char, i)
    close = '}' if open_char == '{' else ']'
    depth = 0
    in_str = False; esc = False
    for j in range(s, len(text)):
        c = text[j]
        if in_str:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
            continue
        if c == '"': in_str = True
        elif c == open_char: depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return json.loads(text[s:j+1])
    raise ValueError('JSON não balanceado para ' + start_marker)

# ────────────────────────────────────────────────────────────────────
# 1. VENDAS DIGITAL (RAW local)
# ────────────────────────────────────────────────────────────────────
def agg_vendas_digital():
    h = open(VENDAS_LOCAL, encoding='utf-8').read()
    raw = balanced_json(h, 'const RAW=')
    rows, cats = raw['rows'], raw['cats']
    # colunas: 0=ano(0=2025,1=2026) 1=mes 2=canal 3=uf 4=dir 5=faixa 6=plano 7=cid 8=valor 9=cancelado
    mensal = defaultdict(lambda: dict(vol=0, fat=0.0, canc=0))
    canal26 = Counter(); uf26 = Counter(); fat_uf26 = defaultdict(float)
    diret = defaultdict(lambda: dict(vol=0, fat=0.0))
    for r in rows:
        ano, mes, cn, uf, dr, fx, pl, cid, vl, cc = r
        m = mensal[(ano, mes)]
        m['vol'] += 1; m['fat'] += vl; m['canc'] += cc
        d = diret[(ano, cats['dir'][dr])]
        d['vol'] += 1; d['fat'] += vl
        if ano == 1:
            canal26[cats['canal'][cn]] += 1
            uf26[cats['uf'][uf]] += 1; fat_uf26[cats['uf'][uf]] += vl
    ult_mes_26 = max(m for (a, m) in mensal if a == 1)
    jj25 = [v for (a, m), v in mensal.items() if a == 0 and m <= ult_mes_26]
    return dict(
        mensal={f"{2025+a}-{m:02d}": dict(vol=v['vol'], fat=round(v['fat']), canc=v['canc'])
                for (a, m), v in sorted(mensal.items())},
        canal26=[dict(nome=k, vol=n) for k, n in canal26.most_common()],
        uf26=[dict(uf=u, vol=n, fat=round(fat_uf26[u])) for u, n in uf26.most_common(8)],
        diretoria={f"{2025+a}-{d}": dict(vol=v['vol'], tk=round(v['fat']/v['vol'], 2))
                   for (a, d), v in sorted(diret.items())},
        ult_mes_26=ult_mes_26,
        comp=dict(v25=sum(x['vol'] for x in jj25), f25=round(sum(x['fat'] for x in jj25)),
                  v26=sum(v['vol'] for (a, m), v in mensal.items() if a == 1),
                  f26=round(sum(v['fat'] for (a, m), v in mensal.items() if a == 1)),
                  canc26=sum(v['canc'] for (a, m), v in mensal.items() if a == 1)),
    )

# ────────────────────────────────────────────────────────────────────
# 2. VENDAS DIÁRIA RMSP (meta × realizado por mês)
# ────────────────────────────────────────────────────────────────────
def agg_diaria():
    h = fetch('https://vendas-diaria-deploy.vercel.app/v1.html')
    i = h.find('const DADOS_MESES')
    out = {}
    for m in re.finditer(r'\n\s{2}([A-Z_0-9]+):\s*\{\s*\n\s*mesLabel:\s*"([^"]+)"', h[i:]):
        key, label = m.group(1), m.group(2)
        if 'Trimestre' in label or 'trimestre' in key.lower():
            continue
        seg = h[i + m.start(): i + m.start() + 150000]
        t = seg.find('TOTAL:')
        tt = seg[t:t + 2500] if t >= 0 else ''
        meta = re.search(r'meta:\s*([\d.]+)', tt)
        ac = re.search(r'acumulado:\s*\[([^\]]+)\]', tt)
        pf = re.search(r'pf:\s*(\d+)', tt); pme = re.search(r'pme:\s*(\d+)', tt)
        ad = re.search(r'adesao:\s*(\d+)', tt)
        acum = [int(x) for x in ac.group(1).replace('\n', '').split(',') if x.strip()] if ac else []
        # último dia com venda: primeiro índice a partir do qual o acumulado fica estável
        dia_real = len(acum)
        for j in range(len(acum) - 1, 0, -1):
            if acum[j] != acum[j - 1]:
                dia_real = j + 1
                break
        MESN = dict(Janeiro=1, Fevereiro=2, Março=3, Abril=4, Maio=5, Junho=6, Julho=7,
                    Agosto=8, Setembro=9, Outubro=10, Novembro=11, Dezembro=12)
        partes = label.split(' ')
        hoje = datetime.now()
        parcial = (MESN.get(partes[0]) == hoje.month and partes[-1] == str(hoje.year))
        out[key] = dict(label=label, meta=float(meta.group(1)) if meta else None,
                        realizado=acum[-1] if acum else None, dia_real=dia_real,
                        dias_no_mes=len(acum), parcial=parcial,
                        pf=int(pf.group(1)) if pf else 0, pme=int(pme.group(1)) if pme else 0,
                        adesao=int(ad.group(1)) if ad else 0)
    return out

# ────────────────────────────────────────────────────────────────────
# 3. CONVERSÃO (leads × vidas por mês — Σvidas ÷ Σleads, sempre agregado)
# ────────────────────────────────────────────────────────────────────
def agg_conversao():
    man = fetch_gz_json('https://conversao-time.vercel.app/data/_manifest.json.gz')
    rows = fetch_gz_json('https://conversao-time.vercel.app/data/conversao_vendedor_raw.json.gz')
    agg = defaultdict(lambda: dict(leads=0, vidas=0, vinc=0, sint=0, vinc_sint=0))
    for r in rows:
        m = agg[int(r['mes'])]
        m['leads'] += r['leads_tot']; m['vidas'] += r['vidas']; m['vinc'] += r['vidas_vinc']
        m['sint'] += r.get('vidas_sint', 0); m['vinc_sint'] += r.get('vidas_vinc_sint', 0)
    out = {}
    for mes in sorted(agg):
        a = agg[mes]
        out[f"2026-{mes:02d}"] = dict(
            leads=a['leads'], vidas=a['vidas'], sint=a['sint'],
            vinc=a['vinc'], vinc_sint=a['vinc_sint'])
    return out, man.get('dt_carga', '')

# ────────────────────────────────────────────────────────────────────
# 4. SLA / ATENDIMENTO (% dentro do SLA e ≤2min por mês)
# ────────────────────────────────────────────────────────────────────
def agg_sla():
    h = fetch('https://atendimento-hapvida.vercel.app/')
    datas = balanced_json(h, 'const DATAS', '[')
    dados = balanced_json(h, 'const DADOS')
    agg = defaultdict(lambda: dict(leads=0, a2=0, dentro=0, fora=0))
    for dt, obj in dados.items():
        a = agg[dt[:7]]
        for r in obj.get('R', []):
            a['leads'] += r.get('LEADS', 0); a['a2'] += r.get('ATE_2MIN', 0)
            a['dentro'] += r.get('DENTRO', 0); a['fora'] += r.get('FORA', 0)
    out = {}
    for mes in sorted(agg):
        a = agg[mes]; tot = a['dentro'] + a['fora']
        out[mes] = dict(leads=a['leads'],
                        pct_sla=round(100 * a['dentro'] / tot, 1) if tot else None,
                        pct_2min=round(100 * a['a2'] / a['leads'], 1) if a['leads'] else None)
    return out, datas[-1]

# ────────────────────────────────────────────────────────────────────
def main():
    print('1/4 Vendas Digital (local)…'); dig = agg_vendas_digital()
    print('2/4 Vendas Diária RMSP…'); dia = agg_diaria()
    print('3/4 Conversão…'); conv, dt_conv = agg_conversao()
    print('4/4 SLA/Atendimento…'); sla, dt_sla = agg_sla()

    data = dict(
        gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'),
        mes_atual=datetime.now().strftime('%Y-%m'),
        digital=dig, diaria=dia, conv=conv, sla=sla,
        cortes=dict(digital=f"Jun/2026", conv=dt_conv, sla=dt_sla),
    )
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template.html'),
               encoding='utf-8').read()
    html = tpl.replace('__DATA__', json.dumps(data, ensure_ascii=False))
    open(OUT, 'w', encoding='utf-8').write(html)
    print(f'OK → {OUT}  ({os.path.getsize(OUT)//1024} KB)')

if __name__ == '__main__':
    main()
