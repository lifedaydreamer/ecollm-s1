"use strict";
(() => {
  const cases = globalThis.TRADEPILOT_CASES;
  const labels = {seller:"卖方",buyer:"买方",currency:"币种",total:"总额",quantity:"数量",deposit_percent:"预付款比例",payment_days:"账期",payment_trigger:"付款触发条件",shipment_date:"装运日期",incoterm:"贸易术语",inspection:"验收",liability:"责任",dispute:"争议解决"};
  const kinds = {difference:"文件差异",business_risk:"策略风险",missing_info:"待补充"};
  let scenario = Object.hasOwn(cases,location.hash.slice(1))?location.hash.slice(1):"conflict", docId = "contract", filter = "all";
  const decisions = Object.fromEntries(Object.keys(cases).map(name=>[name,new Set()]));
  const $ = id => document.getElementById(id);
  function node(tag, className, text) {const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;}
  function button(className, text, action) {const el=node("button",className,text);el.type="button";el.addEventListener("click",action);return el;}
  function renderSource(highlight) {
    const doc=cases[scenario].documents.find(d=>d.id===docId);
    $("doc-tabs").replaceChildren(...cases[scenario].documents.map(d=>button(d.id===docId?"on":"",{inquiry:"询盘",quote:"报价",contract:"合同"}[d.kind],()=>{docId=d.id;renderSource();})));
    $("source").replaceChildren(...doc.blocks.map(block=>{const el=node("div","source-line"+(block.id===highlight?" highlight":""));el.dataset.block=block.id;el.append(node("small","",block.location),node("p","",block.text));return el;}));
    if(highlight){const el=Array.from($("source").children).find(e=>e.dataset.block===highlight);if(el)el.scrollIntoView({behavior:"smooth",block:"nearest"});}
  }
  function render() {
    const current=cases[scenario];
    $("case-title").textContent={conflict:"报价与合同条件变化",normal:"正常交易 · 规则检查",missing:"材料不足 · 待核实",payment:"英文付款条款 · 无 GPU 解析"}[scenario];
    document.querySelectorAll("[data-scenario]").forEach(el=>{el.classList.toggle("selected",el.dataset.scenario===scenario);el.setAttribute("aria-pressed",String(el.dataset.scenario===scenario));});
    $("revision").disabled=scenario!=="conflict";
    renderSource();
    const fields=current.documents.find(d=>d.kind==="contract").facts;
    $("facts").replaceChildren(...fields.map(f=>{const el=node("div","fact-row");el.append(node("label","",labels[f.field]||f.field),node("b","",f.value+(f.field==="deposit_percent"?"%":f.field==="payment_days"?" 天":"")));return el;}));
    $("finding-count").textContent=current.findings.length+" 项发现";
    document.querySelectorAll("[data-filter]").forEach(el=>el.classList.toggle("on",el.dataset.filter===filter));
    const findings=current.findings.filter(f=>filter==="all"||f.kind===filter);
    const elements=findings.map(f=>{
      const el=node("article","finding");el.append(node("span","tag "+f.kind,kinds[f.kind]),node("span","origin","规则检查"),node("h4","",f.title),node("p","",f.explanation),node("div","suggestion",f.suggestion));
      for(const evidence of f.evidence){const doc=current.documents.find(d=>d.id===evidence.document_id);el.append(button("citation","↗ "+doc.name+" · "+evidence.location,()=>{docId=doc.id;renderSource(evidence.block_id);}));}
      el.append(button("decision"+(decisions[scenario].has(f.id)?" done":""),decisions[scenario].has(f.id)?"✓ 已模拟核对 · 点击撤销":"标记已核对（演示）",()=>{const set=decisions[scenario];set.has(f.id)?set.delete(f.id):set.add(f.id);render();}));return el;
    });
    if(!elements.length){const empty=node("div","no-findings");empty.append(node("strong","","✓"),node("div","",current.findings.length?"当前分类没有发现":"规则未发现字段差异或阈值违例"),node("p","","本页不执行语义审查。自然语言条款仍需人工核验。"));elements.push(empty);}
    $("findings").replaceChildren(...elements);
    $("progress").textContent=current.findings.length?`已模拟核对 ${decisions[scenario].size} / ${current.findings.length} 项`:"规则检查完成 · 仍需人工语义复核";
  }
  document.querySelectorAll("[data-scenario]").forEach(el=>el.addEventListener("click",()=>{scenario=el.dataset.scenario;docId="contract";filter="all";history.replaceState(null,"","#"+scenario);render();}));
  window.addEventListener("hashchange",()=>{const name=location.hash.slice(1);if(Object.hasOwn(cases,name)){scenario=name;docId="contract";filter="all";render();}});
  document.querySelectorAll("[data-filter]").forEach(el=>el.addEventListener("click",()=>{filter=el.dataset.filter;render();}));
  $("revision").addEventListener("click",()=>{scenario="normal";filter="all";render();$("case-title").textContent="修订示例 · 金额、预付款与账期已与报价一致";});
  $("export").addEventListener("click",()=>{const value={...cases[scenario],preview_only:true,simulated_checked_ids:[...decisions[scenario]],note:"Synthetic static demo; not a real approval or model evaluation"};const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json"}));const a=node("a");a.href=url;a.download="tradepilot-"+scenario+"-demo.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  $("copy").addEventListener("click",async()=>{try{await navigator.clipboard.writeText("git clone https://github.com/lifedaydreamer/ecollm-s1.git\ncd ecollm-s1\npython3 scripts/demo.py start");$("copy").textContent="已复制";}catch{$("copy").textContent="请选中下方命令复制";}});
  render();
})();
