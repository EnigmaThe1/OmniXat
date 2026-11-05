"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Company = {
  id:string; company_number:string; company_name:string; company_status:string | null;
  source:string; accounts_due:string | null; confirmation_due:string | null;
  accounts_period_end:string | null; checked_at:string | null;
};
type TaxYear = {start_year:number; self_assessment_required:boolean; second_payment_expected:boolean};
type CTPeriod = {id:string;company_id:string;period_end:string;hmrc_return_required:boolean};
type Obligation = {kind:string;label:string;due:string;entity:string;basis:string;status:string;notes:string};
type Overview = {
  companies:Company[]; tax_years:TaxYear[]; corporation_tax_periods:CTPeriod[];
  obligations:Obligation[]; capabilities:{companies_house_configured:boolean;filing_enabled:boolean};
};
type Session = {authenticated:boolean;companies_house_configured:boolean;filing_enabled:boolean};
type Tab = "overview" | "companies" | "tax" | "calendar";

async function api<T>(path:string, method="GET", body?:unknown): Promise<T> {
  const headers:Record<string,string> = {"X-OmniXat-Request":"1"};
  if (body !== undefined) headers["Content-Type"]="application/json";
  const res=await fetch("/api"+path,{
    method,headers,credentials:"same-origin",cache:"no-store",
    body:body===undefined ? undefined : JSON.stringify(body),
  });
  const data=await res.json().catch(()=>({detail:"Unexpected response from API"}));
  if(!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data as T;
}

function ukDate(raw:string) {
  return new Date(raw+"T12:00:00Z").toLocaleDateString("en-GB",{
    day:"2-digit", month:"short", year:"numeric",timeZone:"Europe/London",
  });
}

const description = {
  overview:"A clear view of your obligations, without invented deadlines.",
  companies:"Track registered businesses and dates supplied by Companies House.",
  tax:"Configure your personal tax years and HMRC Corporation Tax periods.",
  calendar:"See known obligations in date order, with their evidence sources.",
};

export default function Home() {
  const [session,setSession]=useState<Session|null>(null);
  const [overview,setOverview]=useState<Overview|null>(null);
  const [tab,setTab]=useState<Tab>("overview");
  const [password,setPassword]=useState("");
  const [loading,setLoading]=useState(false);
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const [companyNumber,setCompanyNumber]=useState("");
  const [companyName,setCompanyName]=useState("");
  const [taxYear,setTaxYear]=useState(2025);
  const [saRequired,setSaRequired]=useState(true);
  const [secondPayment,setSecondPayment]=useState(false);
  const [ctCompany,setCtCompany]=useState("");
  const [periodEnd,setPeriodEnd]=useState("");
  const [ctRequired,setCtRequired]=useState(true);

  const reload=useCallback(async()=>setOverview(await api<Overview>("/overview")),[]);
  useEffect(()=>{
    api<Session>("/session").then(async s=>{
      setSession(s);
      if(s.authenticated) await reload();
    }).catch(e=>setError(e.message));
  },[reload]);

  async function act(task:()=>Promise<void>,success:string) {
    setError("");setNotice("");setLoading(true);
    try { await task();setNotice(success); }
    catch(e) {setError(e instanceof Error?e.message:"Request failed");}
    finally {setLoading(false);}
  }

  function signIn(e:FormEvent) {
    e.preventDefault();
    void act(async()=>{
      const s=await api<Session>("/session","POST",{password});
      setSession(s);setPassword("");await reload();
    },"Signed in to your private workspace.");
  }
  function signOut() {
    void act(async()=>{
      await api("/session","DELETE");
      setSession({authenticated:false,companies_house_configured:false,filing_enabled:false});
      setOverview(null);
    },"Signed out.");
  }
  function saveManual(e:FormEvent) {
    e.preventDefault();
    void act(async()=>{
      await api("/companies/manual","POST",{company_number:companyNumber,company_name:companyName});
      await reload();setCompanyNumber("");setCompanyName("");
    },"Company added as unverified. Official deadlines are hidden until verified.");
  }
  function importCompany() {
    void act(async()=>{
      await api("/companies/import","POST",{company_number:companyNumber});
      await reload();setCompanyNumber("");setCompanyName("");
    },"Company imported from Companies House.");
  }
  function refreshCompany(id:string) {
    void act(async()=>{
      await api("/companies/"+id+"/refresh","POST");await reload();
    },"Company information refreshed from the official register.");
  }
  function saveYear(e:FormEvent) {
    e.preventDefault();
    void act(async()=>{
      await api("/personal-tax-years/"+taxYear,"PUT",{
        self_assessment_required:saRequired,second_payment_expected:saRequired && secondPayment,
      });await reload();
    },"Personal tax year saved.");
  }
  function savePeriod(e:FormEvent) {
    e.preventDefault();
    void act(async()=>{
      await api("/corporation-tax-periods","POST",{
        company_id:ctCompany,period_end:periodEnd,hmrc_return_required:ctRequired,
      });await reload();setPeriodEnd("");
    },"Corporation Tax period saved. Dates are standard-rule estimates, not HMRC confirmations.");
  }

  if(session===null) return <main className="boot"><div className="logo">OX</div><h1>OmniXat</h1><p>Connecting to your private workspace…</p></main>;

  if(!session.authenticated) return <main className="login-wrap">
    <section className="login">
      <div className="logo">OX</div><div className="eyebrow">PERSONAL EDITION · PRIVATE-LOCAL</div>
      <h1>Financial clarity,<br/><span>without the paperwork.</span></h1>
      <p className="muted">Your private UK tax and company compliance control centre.</p>
      <form onSubmit={signIn}>
        <label htmlFor="password">Owner password</label>
        <input id="password" type="password" value={password} onChange={e=>setPassword(e.target.value)}
               autoComplete="current-password" required minLength={1}/>
        <button className="primary" disabled={loading}>{loading?"Signing in…":"Unlock workspace"}</button>
      </form>
      {error && <div role="alert" className="alert error">{error}</div>}
      <p className="small muted">Personal alpha. No tax submissions or payments are enabled.</p>
    </section>
  </main>;

  const companies=overview?.companies??[];
  const obligations=overview?.obligations??[];
  const years=overview?.tax_years??[];
  const dueSoon=obligations.filter(o=>o.status==="upcoming").length;
  const datePassed=obligations.filter(o=>o.status==="date_passed_status_unknown").length;

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="logo">OX</div><div><strong>OmniXat</strong><small>Personal workspace</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      {(["overview","companies","tax","calendar"] as Tab[]).map(t=>
        <button key={t} onClick={()=>setTab(t)} className={"nav-item "+(t===tab?"active":"")}>
          <span className="nav-dot"/>{t==="tax"?"Tax settings":t[0].toUpperCase()+t.slice(1)}
        </button>
      )}
      <div className="sidebar-bottom"><div className="privacy">● Local-only by default</div><button onClick={signOut} className="signout">Sign out</button></div>
    </aside>
    <main className="main">
      <header className="topbar"><span>Personal control centre</span><span className="top-badge">ALPHA 0.1 · READ / PLAN ONLY</span></header>
      <div className="content">
        <div className="eyebrow">YOUR WORKSPACE</div>
        <h1>{tab==="tax"?"Tax settings":tab[0].toUpperCase()+tab.slice(1)}</h1>
        <p className="intro">{description[tab]}</p>
        {notice && <div role="status" className="alert success">{notice}</div>}
        {error && <div role="alert" className="alert error">{error}</div>}
        <section className="warning"><strong>Filing disabled:</strong> OmniXat currently tracks and calculates deadlines only. It does not prepare, submit or pay tax. Dates may depend on HMRC notices and individual circumstances.</section>

        {tab==="overview" && <>
          <div className="metrics">
            <div className="metric"><span>Registered companies</span><strong>{companies.length}</strong><small>{companies.filter(c=>c.source==="companies_house").length} publicly verified</small></div>
            <div className="metric"><span>Tracked dates</span><strong>{obligations.length}</strong><small>From confirmed inputs</small></div>
            <div className="metric"><span>Within 30 days</span><strong>{dueSoon}</strong><small>Upcoming deadlines</small></div>
            <div className="metric"><span>Past dates</span><strong>{datePassed}</strong><small>Filing status not yet checked</small></div>
          </div>
          <div className="grid-two">
            <section className="card">
              <div className="card-head"><h2>Next deadlines</h2><button className="text-btn" onClick={()=>setTab("calendar")}>View calendar →</button></div>
              {obligations.length===0?<div className="empty">No obligations configured. Add a company or declare a personal tax year to begin.</div>:
                obligations.slice(0,6).map((o,i)=><div className="deadline" key={i}><div className="date-tile">{ukDate(o.due)}</div><div><strong>{o.label}</strong><small>{o.entity}</small></div><span className="chip">{o.status==="date_passed_status_unknown"?"Review status":"Tracked"}</span></div>)}
            </section>
            <section className="card">
              <h2>Setup progress</h2>
              <div className="check-row"><span className="check done">✓</span><div><strong>Private workspace</strong><small>Owner access configured</small></div></div>
              <div className="check-row"><span className={"check "+(companies.length?"done":"")}>{companies.length?"✓":"2"}</span><div><strong>Add a company</strong><small>{companies.length?"Company profile available":"Import from Companies House or add manually"}</small></div></div>
              <div className="check-row"><span className={"check "+(years.length?"done":"")}>{years.length?"✓":"3"}</span><div><strong>Set personal tax year</strong><small>Only obligations you confirm will be shown</small></div></div>
              <div className="check-row"><span className="check">4</span><div><strong>Bookkeeping & filings</strong><small>Planned for later milestones</small></div></div>
              <button className="secondary" onClick={()=>setTab(companies.length?"tax":"companies")}>Continue setup →</button>
            </section>
          </div>
        </>}

        {tab==="companies" && <>
          <div className="grid-two">
            <section className="card">
              <h2>Add a company</h2><p className="muted">Eight-character UK company number. Official lookup requires a Companies House API key.</p>
              <form onSubmit={saveManual}>
                <label htmlFor="company-number">Company number</label>
                <input id="company-number" placeholder="12345678" value={companyNumber} maxLength={8}
                       onChange={e=>setCompanyNumber(e.target.value.toUpperCase())} required/>
                <button className="primary" type="button" disabled={loading||!session.companies_house_configured||companyNumber.trim().length!==8} onClick={importCompany}>Import verified company</button>
                {!session.companies_house_configured && <p className="small muted">API key not configured. Add a manual unverified record instead.</p>}
                <hr/>
                <label htmlFor="company-name">Manual company name</label>
                <input id="company-name" placeholder="Example Limited" value={companyName} onChange={e=>setCompanyName(e.target.value)} required/>
                <button className="secondary" disabled={loading||companyNumber.trim().length!==8}>Add unverified company</button>
              </form>
            </section>
            <section className="card">
              <h2>Connected company profiles</h2>
              {companies.length===0?<div className="empty">No companies yet.</div>:companies.map(c=><div className="company" key={c.id}>
                <strong>{c.company_name}</strong><small>{c.company_number} · {c.company_status||"Status unknown"}</small>
                <div className={"chip "+(c.source==="companies_house"?"verified":"pending")}>{c.source==="companies_house"?"Companies House verified":"Manual · unverified"}</div>
                <div className="detail"><span>Next accounts</span><strong>{c.accounts_due?ukDate(c.accounts_due):"Not verified"}</strong></div>
                <div className="detail"><span>Confirmation</span><strong>{c.confirmation_due?ukDate(c.confirmation_due):"Not verified"}</strong></div>
                <button className="text-btn" onClick={()=>refreshCompany(c.id)} disabled={loading||!session.companies_house_configured}>Refresh official record →</button>
              </div>)}
            </section>
          </div>
        </>}

        {tab==="tax" && <div className="grid-two">
          <section className="card">
            <h2>Personal Self Assessment</h2>
            <p className="muted">Confirm whether your circumstances require a Self Assessment return. The app cannot decide applicability yet.</p>
            <form onSubmit={saveYear}>
              <label htmlFor="year">Tax year begins (6 April)</label>
              <input id="year" type="number" min={2000} max={2100} value={taxYear} onChange={e=>setTaxYear(Number(e.target.value))} required/>
              <label className="check-label"><input type="checkbox" checked={saRequired} onChange={e=>setSaRequired(e.target.checked)}/> I have confirmed that Self Assessment is required for this year</label>
              <label className="check-label"><input type="checkbox" checked={secondPayment} disabled={!saRequired} onChange={e=>setSecondPayment(e.target.checked)}/> I expect a second payment on account (31 July)</label>
              <button className="primary" disabled={loading}>Save tax year</button>
            </form>
            {years.map(y=><div className="saved" key={y.start_year}>{y.start_year}–{String(y.start_year+1).slice(-2)} · {y.self_assessment_required?"Self Assessment required":"Not marked as required"}</div>)}
          </section>
          <section className="card">
            <h2>Corporation Tax periods</h2>
            <p className="muted">Enter the actual HMRC Corporation Tax accounting period end; it may differ from the Companies House accounts period.</p>
            <form onSubmit={savePeriod}>
              <label htmlFor="ct-company">Company</label>
              <select id="ct-company" required value={ctCompany} onChange={e=>setCtCompany(e.target.value)}>
                <option value="">Select a company</option>{companies.map(c=><option key={c.id} value={c.id}>{c.company_name}</option>)}
              </select>
              <label htmlFor="ct-end">HMRC period end</label>
              <input id="ct-end" type="date" value={periodEnd} onChange={e=>setPeriodEnd(e.target.value)} required/>
              <label className="check-label"><input type="checkbox" checked={ctRequired} onChange={e=>setCtRequired(e.target.checked)}/> HMRC requires a CT600 return for this period</label>
              <button className="primary" disabled={loading||companies.length===0}>Save period</button>
            </form>
            {overview?.corporation_tax_periods.map(p=><div className="saved" key={p.id}>{companies.find(c=>c.id===p.company_id)?.company_name||"Company"} · {ukDate(p.period_end)} · {p.hmrc_return_required?"Return required":"Not marked required"}</div>)}
          </section>
        </div>}

        {tab==="calendar" && <section className="card">
          <div className="card-head"><h2>Compliance calendar</h2><span className="chip">{obligations.length} tracked</span></div>
          {obligations.length===0?<div className="empty">Add a verified company or confirm a tax obligation to generate your calendar.</div>:
          obligations.map((o,i)=><article className="calendar-item" key={i}>
            <div className="calendar-date">{ukDate(o.due)}</div>
            <div><strong>{o.label}</strong><p>{o.entity}</p><small>{o.notes}</small>
              <div className="source">Source: {o.basis==="companies_house_public_record"?"Companies House public API":"User declaration + standard statutory rule"}</div>
            </div><span className={"chip "+(o.status==="date_passed_status_unknown"?"pending":"")}>{o.status==="date_passed_status_unknown"?"Past date · check filing":"Scheduled"}</span>
          </article>)}
        </section>}
        <footer>OmniXat personal alpha · Dates are not evidence of filing · No HMRC submission integration</footer>
      </div>
    </main>
  </div>;
}
