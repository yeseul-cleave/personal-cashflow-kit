#!/usr/bin/env python3
"""월 현금흐름·카테고리·자산을 눈으로 보는 로컬 단일 HTML 대시보드."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from common import LEDGER, OUT, find_exports, load_profile, load_status


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    cashflow = read_csv(OUT / "cashflow_monthly.csv")
    categories = read_csv(OUT / "category_monthly.csv")
    asset_monthly = read_csv(OUT / "asset_monthly.csv") if (OUT / "asset_monthly.csv").exists() else []
    profile = load_profile()
    household_labels = {m["label"] for m in profile["household"]["members"]
                        if m.get("role") == "self" or m.get("shared_household")}
    transaction_rows = read_csv(LEDGER / "ledger.csv")
    category_transactions: dict[str, dict[str, list[dict]]] = {}
    for r in transaction_rows:
        if r["귀속"] not in household_labels or r["상태"] in ("제외", "내부이체", "저축이체", "자산거래", "확인필요"):
            continue
        if r["카테고리"] in ("수입", "내부이체", "자산거래"):
            continue
        amount = int(r["금액"])
        if amount >= 0 and r["타입"] != "지출":
            continue
        category_transactions.setdefault(r["월"], {}).setdefault(r["카테고리"], []).append({
            "date": r["날짜"], "desc": r["내용"], "sub": r["세부"], "account": r["계좌"],
            "amount": -amount, "fixed": r["고정비"], "status": r["상태"], "evidence": r["근거"],
        })
    for month_data in category_transactions.values():
        for rows in month_data.values():
            rows.sort(key=lambda x: (x["date"], abs(x["amount"])), reverse=True)
    with (OUT / "balance_sheet.json").open(encoding="utf-8") as f:
        balance = json.load(f)
    next_step = json.loads((OUT / "next_step.json").read_text(encoding="utf-8")) if (OUT / "next_step.json").exists() else {}
    status = load_status(find_exports()[-1])
    data = json.dumps({"cashflow": cashflow, "categories": categories, "categoryTransactions": category_transactions,
                       "assetMonthly": asset_monthly, "balance": balance,
                       "investments": status.investments, "loans": status.loans, "nextStep": next_step},
                      ensure_ascii=False, default=str).replace("</", "<\\/")
    OUT.mkdir(parents=True, exist_ok=True)
    html = HTML.replace("__DATA__", data)
    # 표는 최신부터, 차트의 시간축은 과거→최신을 유지한다.
    html = html.replace("],cf.map(r=>[r['월']", "],[...cf].reverse().map(r=>[r['월']")
    html = html.replace(
        "const cm=Object.keys(D.categories[0]||{}).filter(k=>/^\\d{4}-\\d{2}$/.test(k))",
        "const cm=Object.keys(D.categories[0]||{}).filter(k=>/^\\d{4}-\\d{2}$/.test(k)).reverse()",
    )
    html = html.replace(
        '<div class="tablewrap" id="category-table"></div></article>',
        '<div class="tablewrap" id="category-table"></div><div id="cell-detail" class="detail" hidden></div></article>',
    )
    html = html.replace(
        "...cm.map(m=>w(r[m]))",
        """...cm.map(m=>`<button class="cellbtn" onclick='showTx(${JSON.stringify(r['카테고리'])},${JSON.stringify(m)})'>${w(r[m])}</button>`)""",
    )
    html = html.replace(
        "</script></body>",
        """function showTx(cat,mo){const rows=D.categoryTransactions?.[mo]?.[cat]||[],box=document.getElementById('cell-detail'),sum=rows.reduce((s,r)=>s+n(r.amount),0);box.hidden=false;box.innerHTML=`<h2>${e(mo)} · ${e(cat)} <span class=\\"sub\\">${rows.length}건 · ${w(sum)}</span></h2><div class=\\"tablewrap\\"><table><thead><tr><th>날짜</th><th>내용</th><th>세부</th><th>결제수단</th><th>금액</th><th>구분</th><th>분류 근거</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${e(r.date)}</td><td>${e(r.desc)}</td><td>${e(r.sub||'-')}</td><td>${e(r.account)}</td><td class=\\"${n(r.amount)<0?'good':''}\\">${w(r.amount)}</td><td>${r.fixed==='Y'?'고정 ':''}${e(r.status)}</td><td>${e(r.evidence)}</td></tr>`).join('')}</tbody></table></div>`;box.scrollIntoView({behavior:'smooth',block:'nearest'})}</script></body>""",
    )
    html = html.replace(".note{font-size:12px", ".cellbtn{border:0;background:transparent;color:var(--blue);font:inherit;font-weight:650;cursor:pointer;padding:2px 0}.cellbtn:hover{text-decoration:underline}.detail{margin-top:18px;padding-top:18px;border-top:1px solid var(--line)}.detail .sub{font-size:13px;color:var(--muted);font-weight:500}.note{font-size:12px")
    (OUT / "dashboard.html").write_text(html, encoding="utf-8")
    print(f"✔ 눈으로 보는 결과: {OUT / 'dashboard.html'}")


HTML = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>내 현금흐름 대시보드</title><style>
:root{--bg:#f4f6fa;--card:#fff;--ink:#172033;--muted:#687386;--line:#e3e8f0;--blue:#3977f6;--green:#14a273;--red:#e05757;--violet:#7657d5}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px -apple-system,BlinkMacSystemFont,"Noto Sans KR",sans-serif}.shell{max-width:1380px;margin:auto;padding:24px}.top{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:18px}.top h1{font-size:25px;margin:0 0 4px}.sub,.note{color:var(--muted)}.tabs{display:flex;gap:7px}.tab{border:1px solid var(--line);background:var(--card);padding:9px 15px;border-radius:10px;cursor:pointer;font-weight:700}.tab.on{color:#fff;background:var(--ink)}.page{display:none}.page.on{display:block}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:15px;box-shadow:0 3px 14px #17203309}.kpi{padding:17px}.kpi small{display:block;color:var(--muted);font-weight:700;margin-bottom:9px}.kpi strong{font-size:22px}.good{color:var(--green)}.bad{color:var(--red)}.grid2{display:grid;grid-template-columns:1.25fr 1fr;gap:14px}.card{padding:18px;margin-bottom:14px}.card h2{font-size:16px;margin:0 0 15px}.chart{width:100%;height:270px}.chart svg{width:100%;height:100%;overflow:visible}.legend{display:flex;gap:14px;color:var(--muted);font-size:12px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}.tablewrap{overflow:auto;max-height:520px;border:1px solid var(--line);border-radius:12px}table{border-collapse:separate;border-spacing:0;width:100%;white-space:nowrap}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:right}th{position:sticky;top:0;background:#f8fafc;z-index:2;color:#526071;font-size:12px}th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:inherit}td:first-child{font-weight:650}tbody tr:nth-child(even){background:#fafbfd}tbody tr:hover{background:#eef4ff}.controls{margin:-4px 0 12px}.controls select{border:1px solid var(--line);border-radius:9px;padding:7px 10px}.bars{display:grid;gap:11px}.barrow{display:grid;grid-template-columns:120px 1fr 105px;gap:10px;align-items:center}.track{height:11px;background:#edf0f5;border-radius:99px;overflow:hidden}.fill{height:100%;border-radius:99px}.choices{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.choices span{padding:9px 12px;border:1px solid var(--line);border-radius:9px;background:#f8fafc}.note{font-size:12px;margin-top:8px}@media(max-width:850px){.shell{padding:14px}.top{align-items:start;flex-direction:column}.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.chart{height:230px}}@media(max-width:480px){.kpis{grid-template-columns:1fr}.tabs{width:100%}.tab{flex:1}}
</style></head><body><main class="shell"><header class="top"><div><h1>내 현금흐름 대시보드</h1><div class="sub" id="period"></div></div><nav class="tabs"><button class="tab on" data-page="cash">가계부</button><button class="tab" data-page="asset">자산</button><button class="tab" data-page="next">다음 설계</button></nav></header>
<section class="page on" id="cash"><div class="kpis" id="cash-kpis"></div><div class="grid2"><article class="card"><h2>월별 수입·지출·순현금흐름</h2><div class="chart" id="monthly-chart"></div><div class="legend"><span><i class="dot" style="background:var(--blue)"></i>수입</span><span><i class="dot" style="background:var(--red)"></i>지출</span><span><i class="dot" style="background:var(--green)"></i>순현금흐름</span></div></article><article class="card"><h2>최근 완성월 카테고리 비중</h2><div class="bars" id="category-bars"></div></article></div><article class="card"><h2>월별 요약표</h2><div class="tablewrap" id="monthly-table"></div><div class="note">* 부분 월은 평균에서 제외됩니다. 확인필요는 수입·지출에 아직 포함되지 않습니다.</div></article><article class="card"><h2>카테고리별 지출 흐름표</h2><div class="tablewrap" id="category-table"></div></article><article class="card"><h2>카테고리 지출 추이</h2><div class="controls"><select id="cat-select"></select></div><div class="chart" id="category-chart"></div></article></section>
<section class="page" id="asset"><div class="kpis" id="asset-kpis"></div><article class="card"><h2>월별 자산 요약표</h2><div class="tablewrap" id="asset-monthly-table"></div><div class="note">매달 마감할 때 같은 달은 갱신되고 새 달은 누적됩니다.</div></article><div class="grid2"><article class="card"><h2>자산 구성</h2><div class="bars" id="asset-bars"></div></article><article class="card"><h2>증권사별 투자자산</h2><div class="bars" id="broker-bars"></div></article></div><article class="card"><h2>보유 종목 상세</h2><div class="tablewrap" id="investment-table"></div></article><article class="card"><h2>대출 상세</h2><div class="tablewrap" id="loan-table"></div></article></section>
<section class="page" id="next"><div class="kpis" id="next-kpis"></div><div class="grid2"><article class="card"><h2>줄일 수 있는 곳 — 판단 전 후보</h2><div id="cut-table" class="tablewrap"></div><div class="note">금액이 크다는 이유만으로 줄일 항목은 아닙니다. 인터뷰에서 ‘삶의 만족을 해치지 않고 줄일 수 있는 것’만 고릅니다.</div></article><article class="card"><h2>지금 필요한 질문</h2><div id="next-question"></div></article></div><article class="card"><h2>인터뷰가 끝나면 나오는 것</h2><div id="next-outputs"></div></article></section></main>
<script>const D=__DATA__,n=x=>Number(x)||0,w=x=>Math.round(n(x)).toLocaleString('ko-KR')+'원',e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab,.page').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.getElementById(b.dataset.page).classList.add('on')});const cf=D.cashflow,full=cf.filter(r=>r['완전한달']==='Y'),months=cf.map(r=>r['월']),avg=k=>full.length?full.reduce((s,r)=>s+n(r[k]),0)/full.length:0;document.getElementById('period').textContent=`${months[0]||'-'} ~ ${months.at(-1)||'-'} · 자산 ${D.balance.exported_at||'-'} 기준`;function cards(id,a){document.getElementById(id).innerHTML=a.map(([k,v,c=''])=>`<div class="kpi"><small>${k}</small><strong class="${c}">${v}</strong></div>`).join('')}cards('cash-kpis',[['월평균 수입',w(avg('수입'))],['월평균 지출',w(avg('지출'))],['월평균 순현금흐름',w(avg('순현금흐름')),avg('순현금흐름')>=0?'good':'bad'],['월평균 저축·투자',w(avg('저축·투자 이체(순)'))]]);function table(id,h,rows){document.getElementById(id).innerHTML=`<table><thead><tr>${h.map(x=>`<th>${e(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((x,i)=>`<td>${i?x:e(x)}</td>`).join('')}</tr>`).join('')}</tbody></table>`}table('monthly-table',['월','수입','지출','고정','변동','순현금흐름','저축·투자','자산거래','확인필요'],cf.map(r=>[r['월']+(r['완전한달']==='Y'?'':' *'),w(r['수입']),w(r['지출']),w(r['고정지출']),w(r['변동지출']),`<span class="${n(r['순현금흐름'])>=0?'good':'bad'}">${w(r['순현금흐름'])}</span>`,w(r['저축·투자 이체(순)']),w(r['자산거래(순유출)']),w(r['확인필요금액'])]));const cm=Object.keys(D.categories[0]||{}).filter(k=>/^\d{4}-\d{2}$/.test(k)),cats=D.categories.filter(r=>!r['카테고리'].startsWith('수입/')).sort((a,b)=>n(b['월평균(완전한달)'])-n(a['월평균(완전한달)']));table('category-table',['카테고리',...cm,'월평균'],cats.map(r=>[r['카테고리'],...cm.map(m=>w(r[m])),w(r['월평균(완전한달)'])]));function bars(id,a,color){const mx=Math.max(1,...a.map(x=>x[1]));document.getElementById(id).innerHTML=a.map(([k,v])=>`<div class="barrow"><span>${e(k)}</span><div class="track"><div class="fill" style="width:${Math.max(1,v/mx*100)}%;background:${color}"></div></div><b>${w(v)}</b></div>`).join('')}const lf=full.at(-1)?.['월']||cm.at(-1);bars('category-bars',cats.map(r=>[r['카테고리'],n(r[lf])]).filter(x=>x[1]>0).slice(0,12),'var(--blue)');function chart(id,series){const W=900,H=250,p={l:58,r:15,t:12,b:36},vals=series.flatMap(s=>s.v),lo=Math.min(0,...vals),hi=Math.max(1,...vals),x=i=>p.l+i*(W-p.l-p.r)/Math.max(1,months.length-1),y=v=>p.t+(hi-v)*(H-p.t-p.b)/(hi-lo||1);let z=`<svg viewBox="0 0 ${W} ${H}"><line x1="${p.l}" y1="${y(0)}" x2="${W-p.r}" y2="${y(0)}" stroke="#cfd6e2"/>`;months.forEach((m,i)=>{if(i%Math.ceil(months.length/6)===0)z+=`<text x="${x(i)}" y="${H-8}" text-anchor="middle" font-size="11" fill="#687386">${m.slice(2)}</text>`});series.forEach(s=>{z+=`<polyline points="${s.v.map((v,i)=>`${x(i)},${y(v)}`).join(' ')}" fill="none" stroke="${s.c}" stroke-width="3"/>`;s.v.forEach((v,i)=>z+=`<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${s.c}"><title>${months[i]} ${s.k}: ${w(v)}</title></circle>`)});document.getElementById(id).innerHTML=z+'</svg>'}chart('monthly-chart',[{k:'수입',c:'#3977f6',v:cf.map(r=>n(r['수입']))},{k:'지출',c:'#e05757',v:cf.map(r=>n(r['지출']))},{k:'순현금흐름',c:'#14a273',v:cf.map(r=>n(r['순현금흐름']))}]);const sel=document.getElementById('cat-select');cats.forEach(r=>sel.add(new Option(r['카테고리'])));function draw(){const r=cats.find(x=>x['카테고리']===sel.value)||cats[0];chart('category-chart',[{k:r?.['카테고리']||'',c:'#7657d5',v:months.map(m=>n(r?.[m]))}])}sel.onchange=draw;draw();const b=D.balance;cards('asset-kpis',[['총자산',w(b.total_assets)],['총부채',w(b.total_liabilities),'bad'],['순자산',w(b.net_worth),n(b.net_worth)>=0?'good':'bad'],['유동자산',w(b.liquid_assets)]]);table('asset-monthly-table',['월','총자산','총부채','순자산','유동자산','투자','연금','부동산'],D.assetMonthly.map(r=>[r['월'],w(r['총자산']),w(r['총부채']),w(r['순자산']),w(r['유동자산']),w(r['투자']),w(r['연금']),w(r['부동산'])]));const ko={checking:'입출금',savings:'저축',pay:'간편결제',cash:'현금',investment:'투자',pension:'연금',realestate:'부동산',insurance:'보험',other:'기타'};bars('asset-bars',Object.entries(b.assets||{}).map(([k,v])=>[ko[k]||k,n(v)]).sort((a,z)=>z[1]-a[1]),'var(--green)');bars('broker-bars',Object.entries(b.investments?.by_broker||{}).map(([k,v])=>[k,n(v)]).sort((a,z)=>z[1]-a[1]),'var(--violet)');table('investment-table',['금융사','종목','종류','원금','평가','손익','수익률'],D.investments.sort((a,z)=>n(z['평가금액'])-n(a['평가금액'])).map(i=>{const g=n(i['평가금액'])-n(i['투자원금']);return[i['금융사'],e(i['상품명']),e(i['투자상품종류']),w(i['투자원금']),w(i['평가금액']),`<span class="${g>=0?'good':'bad'}">${w(g)}</span>`,`${n(i['수익률']).toFixed(1)}%`]}));table('loan-table',['금융사','상품','잔액','원금/한도','금리','만기'],D.loans.map(l=>[l['금융사'],e(l['상품명']),w(l['대출잔액']),w(l['대출원금']),`${n(l['대출금리']).toFixed(2)}%`,e(String(l['대출만기일']||'').slice(0,10))]));const ns=D.nextStep||{},obs=ns.observed||[];cards('next-kpis',obs.slice(0,4).map(x=>[x.label,x.note?`${w(x.value)} · ${x.note}`:w(x.value)]));table('cut-table',['카테고리','월평균','10% 조정','20% 조정'],(ns.cut_candidates||[]).map(x=>[x.category,w(x.monthly),w(x.ten_pct),w(x.twenty_pct)]));const q=ns.next_question;document.getElementById('next-question').innerHTML=q?`<div class="note">${e(q.why)}</div><h3>${e(q.question)}</h3><div class="choices">${q.choices.map(x=>`<span>${e(x)}</span>`).join('')}</div><p class="note">채팅에서 답하면 저장되고 다음 질문으로 넘어갑니다. ${ns.status.answered}/${ns.status.total} 완료</p>`:'<strong class="good">인터뷰 완료 — 설계표를 만들 수 있습니다.</strong>';document.getElementById('next-outputs').innerHTML=`<div class="choices">${(ns.outputs||[]).map(x=>`<span>${e(x)}</span>`).join('')}</div>`;</script></body></html>'''

if __name__ == "__main__":
    main()
