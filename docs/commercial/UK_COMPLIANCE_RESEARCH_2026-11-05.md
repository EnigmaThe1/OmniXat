# OmniXAT — UK accounting and filing research baseline

**Checked:** 5 November 2026. **Scope:** engineering research baseline; no customer records.

## Purpose and authority

OmniXAT is now being developed as a commercial UK accounting, tax and compliance platform from the outset. The target includes multiple customer workspaces, subscriptions and trials, a separately billable developer API, and a platform-owner administration service. This supersedes the previous personal-only release strategy. The existing fictional prototype remains a reference, not a public financial service.

This document maps researched obligations into product requirements. It is not an exhaustive opinion on every UK law, a certification of tax calculations, or authority to submit customer declarations. Sources were checked through official government, regulator and standards-body publications. Some were inspected as search extracts rather than full instruments. No claim is made that every supplementary return, relief, sector or transition has been qualified. Before a module goes live, its detailed rules, current legislation, technical schemas and test cases must be independently reviewed for that module.

The machine-readable catalogue `commercial/rules.json` contains 40 dated records with sources, legal/change status and implementation status. A researched obligation is not an implemented capability. All live filing flags are false.

## 1. Findings that change the architecture now

1. **Rules depend on the relevant period, not today's date alone.** Historic amendments need historic accounting standards, size thresholds, tax rates and accepted taxonomies. Never regenerate historic accounts using whichever rules are newest.
2. **Accounts, returns and payments are distinct obligations.** Companies House delivery, HMRC CT600, tax payment and shareholder accounts may have different content, deadlines and recipients.
3. **Ordinary accounts and replacement revisions need different templates.** Do not inherit ordinary filleting options into replacement revised accounts.
4. **Legal form is not a tax regime.** A person may run several businesses; a charity can also be a company; an association may owe Corporation Tax without being incorporated.
5. **UK is not one reporting jurisdiction.** Charity regulators and some tax rules differ between England and Wales, Scotland and Northern Ireland. UK-wide product architecture must retain these distinctions.
6. **Production access is a per-service qualification.** A working web interface, schema-valid XML or successful sandbox call does not establish recognised production capability.
7. **Commercial service classification matters.** Pure software, managed bookkeeping, paid tax representation and identity verification have different regulatory consequences.

## 2. Entity and obligation coverage map

| Entity / customer | Obligations to model | Coverage decision |
|---|---|---|
| Sole trader | Income/expense records, accounting basis, SA100 and applicable pages, NI, MTD eligibility, VAT and CIS where applicable | Launch candidate; detailed tax preparation still to qualify |
| Individual landlord | UK/foreign property businesses, Self Assessment, MTD, ownership shares, separate disposal reporting | Separate module; do not treat property as trade |
| Private limited company by shares | Statutory accounts, Companies House filings, CT600, records, confirmation statement, directors/PSC updates | Initial company module |
| Company limited by guarantee | Company obligations plus distinct member/capital presentation and any charitable status | Separate tested account templates |
| Dormant/non-trading company | Companies House duties remain; HMRC dormancy and notices separately assessed | Dedicated questionnaire, not a single dormant toggle |
| Ordinary partnership / Scottish partnership | Partnership return and allocations; each partner's return; legal jurisdiction and partners' status | Planned specialist module |
| LLP | Statutory accounts and confirmation statement; normally partnership tax and member allocations | Distinct legal form; never default all LLPs to CT600 |
| Limited partnership | Registration and partner status; qualifying-partnership accounts where applicable | Research/deeper qualification required |
| CIC | Company accounts plus community interest report CIC34 and dedicated filing route | Later module, including dormant CIC obligations |
| Charity/CIO/SCIO/charitable company | Regulator-specific returns, accounts basis, trustees' report, scrutiny, funds; company filings where applicable | Jurisdiction-specific modules |
| Co-operative / community benefit society | FCA mutuals annual return/accounts and applicable tax | Separate module; FCA registration is not financial-service authorisation |
| Club / unincorporated association | Constitution, accounts, potential Corporation Tax, charity or CASC status where applicable | Dedicated applicability review |
| Trust / estate | SA900 and pages; Trust Registration Service separately | Specialist module |
| PLC, groups, overseas establishments, UKSEF | Different accounts deadlines, consolidation, package formats and reporting | Explicitly unsupported until individually qualified |

The final rows are coverage requirements, not claims of a fully researched implementation. Insolvency, regulated finance, insurance, pensions, tax shelters, customs/excise, international groups and sector-specific regimes need specialist modules. An unsupported entity may be tracked or exported without claiming that OmniXAT can prepare or submit its returns.

Sources: [LLP accounts](https://www.gov.uk/government/publications/limited-liability-partnership-accounts-guidance/llp-accounts), [partnership setup](https://www.gov.uk/set-up-business-partnership), [associations](https://www.gov.uk/unincorporated-associations), [SA900](https://www.gov.uk/government/publications/self-assessment-trust-and-estate-tax-return-sa900), [Companies House package types](https://find-and-update.company-information.service.gov.uk/accounts-filing).

## 3. Company accounts and filing

### Calendar and legal responsibilities

For an ordinary subsequent private-company year, Companies House accounts are normally due nine months after year end. CT600 is normally due twelve months after the separate Corporation Tax accounting-period end; the non-instalment Corporation Tax payment deadline is nine months and one day. First, shortened, public-company, special and extended periods require separate logic. A first accounts period can exceed twelve months while a CT accounting period cannot: splitting CT returns must not split statutory accounts automatically.

Annual confirmation statements are separate from accounts. The review period, confirmation date and filing deadline must be separate fields; a statement is normally required at least annually and delivered within fourteen days after the review period ends. Keep event filings and any fees separate from subscription charges.

Sources: [CT accounting periods](https://www.gov.uk/corporation-tax-accounting-period), [accounts/return deadlines](https://www.gov.uk/prepare-file-annual-accounts-for-limited-company), [confirmation statement](https://www.gov.uk/guidance/filing-your-companys-confirmation-statement).

### Size and accounting framework

Nominal annual micro limits changed for financial years beginning on or after 6 April 2025: turnover £1m, assets £500,000, employees 10. The previous micro limits were £632,000/£316,000/10. Small-company limits for the newer periods are £15m/£7.5m/50. Two-of-three tests alone are insufficient: exclusions, groups, two-year rules, transitional treatment and turnover adjustment for non-year periods matter. Audit exemption also requires its own checks.

FRS 105 is the micro framework; FRS 102 includes the small-company regime. The 2024 periodic review has a principal effective date of periods beginning 1 January 2026. FRS 102 revenue and lease changes require transition work; they must not be indiscriminately copied into FRS 105. February 2026 adapted-format amendments have a later effective date. Read the relevant standard and subsequent amendments together.

Sources: [size transition legislation](https://www.legislation.gov.uk/uksi/2024/1303/contents), [historic micro provision](https://www.legislation.gov.uk/ukpga/2006/46/section/384A/2023-02-07), [Companies House guidance](https://www.gov.uk/government/publications/filing-your-companies-house-accounts/life-of-a-company-part-1-accounts), [FRS 102](https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-102/), [FRS 105](https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-accounting-standards/frs-105/).

### Ordinary versus revised accounts

Ordinary eligible small/micro public copies can omit P&L under applicable rules. Revised replacement accounts are different: ICAEW explains there is no filleting facility under the defective-accounts regulations. Preserve period dates, original approval date and actual revision approval date; generate required statements and the complete replacement, including P&L. Regulation 14 provides a twenty-eight-day delivery period after revision. Supplementary-note revisions are a separate route, not interchangeable with replacing an entire set.

The earlier A4O research identified a missing P&L reported in a revised preview; it did not prove every A4O revision is defective. Use fictional regression cases, not private company records in repository fixtures.

Sources: [revision regulations](https://www.legislation.gov.uk/uksi/2008/373/contents), [regulation 14](https://www.legislation.gov.uk/uksi/2008/373/regulation/14), [ICAEW interpretation](https://www.icaew.com/technical/tas-helpsheets/law-and-regulation/defective-accounts-and-reports), [Companies House amendments](https://www.gov.uk/annual-accounts/corrections-and-amendments).

### Identity and announced reforms

Director and PSC identity verification is role- and date-specific. A person's Companies House personal code is different from the company's authentication code. Reuse of one identity across companies does not remove the need to associate it with each role. Never put these codes in ordinary logs or AI prompts.

The official 23 October 2026 update retains planned mandatory software/iXBRL accounts filing from April 2028, while pausing the planned general small/micro P&L publication requirement. This pause does not establish a filleting right for revised replacements. Record these as announced future changes; recheck implementation legislation and technical rules before enabling them.

Sources: [identity timing](https://www.gov.uk/guidance/when-you-need-to-verify-your-identity-for-companies-house), [October reform update](https://www.gov.uk/government/news/companies-house-update-to-accounts-filing-from-april-2028).

## 4. Corporation Tax

The standard non-ring-fence framework has 19% small-profits and 25% main rates, with marginal relief between nominal £50,000 and £250,000 limits. Associated companies, short accounting periods, augmented profits and exclusions mean a simple profit-band lookup is not a complete calculation. Separate accounting profit, taxable total profits, losses, disallowable costs, capital allowances, director loans and supplementary pages. Owner-paid company invoices need payer/funding treatment separate from deductibility.

Company Tax Return amendments are normally due within twelve months of the filing deadline. They and Companies House revised accounts require separate applicability decisions and approvals. Companies House acceptance does not update HMRC automatically. A zero tax estimate or absence of trading does not by itself cancel a notice to file.

Sources: [CT amendments](https://www.gov.uk/company-tax-returns/making-changes), [annual investment allowance](https://www.gov.uk/capital-allowances/annual-investment-allowance), [CT rates](https://www.gov.uk/government/publications/rates-and-allowances-corporation-tax/rates-and-allowances-corporation-tax), [CT XML API](https://developer.service.hmrc.gov.uk/api-documentation/docs/api/xml/Corporation%20Tax%20Online), [dormancy distinction](https://www.gov.uk/dormant-company/dormant-for-companies-house).

## 5. Individuals, self-employment and MTD

### Annual Self Assessment

Keep registration, paper filing, software filing and payment deadlines separate. For 2025–26, ordinary paper and online filing dates are 31 October 2026 and 31 January 2027. The usual notification date for a newly required return is 5 October after the year ends. Notices and late registration can create different filing dates without moving the ordinary payment date. Payments on account have their own applicability and January/July dates. Amendments are generally allowed within twelve months of the filing deadline, with different routes after that.

Cash basis is the default from 2024–25 for eligible self-employed businesses; eligibility and an election to use traditional accounting still matter. Do not apply this rule to company statutory accounts. The tax-year basis, overlap relief transition, losses, CIS deductions, mixed income and residence require dedicated tests before calculations are released.

Sources: [SA deadlines](https://www.gov.uk/self-assessment-tax-returns/deadlines), [payment dates](https://www.gov.uk/pay-self-assessment-tax-bill), [SA amendments](https://www.gov.uk/self-assessment-tax-returns/corrections), [records/accounting basis](https://www.gov.uk/self-employed-records/overview).

### MTD Income Tax

| First mandated year | Reference tax year | Qualifying income threshold |
|---|---|---|
| 2026–27 | 2024–25 | Over £50,000 |
| 2027–28 | 2025–26 | Over £30,000 |
| 2028–29 | 2026–27 | Over £20,000 |

This is qualifying gross self-employment/property income, not profit or all personal income. Apply registration conditions, permanent/temporary exemptions and ongoing mandation rules. Partnership commencement is not yet specified in the guidance reviewed; do not assign sole-trader dates to partnerships.

Standard updates are cumulative from 6 April to 5 July, 5 October, 5 January and 5 April, due 7 August, 7 November, 7 February and 7 May respectively. Calendar elections need separate period logic. Quarterly updates are not final declarations and are not quarterly payment instructions. Finalisation must account for other income and adjustments through the supported year-specific journey.

Sources: [MTD rollout](https://www.gov.uk/guidance/find-out-if-and-when-you-need-to-use-making-tax-digital-for-income-tax), [exemptions](https://www.gov.uk/guidance/find-out-if-you-can-get-an-exemption-from-making-tax-digital-for-income-tax), [quarterly updates](https://www.gov.uk/guidance/use-making-tax-digital-for-income-tax/send-quarterly-updates), [first-year journey](https://www.gov.uk/guidance/use-making-tax-digital-for-income-tax/using-making-tax-digital-for-income-tax-for-the-first-time).

### Rates and geography

Use year-versioned personal tax, dividends, savings and NI tables; support Scottish non-savings/non-dividend income separately. For example, published 2026–27 dividend rates differ from 2025–26, while the standard Personal Allowance remains £12,570 with adjusted-net-income tapering. A single universal income-tax band table is unsuitable. Annual NIC rates, contribution treatment and voluntary Class 2 decisions also need year-specific support.

Sources: [income tax/dividends by year](https://www.gov.uk/government/publications/rates-and-allowances-income-tax/income-tax-rates-and-allowances-current-and-past), [NI](https://www.gov.uk/national-insurance/how-much-you-pay).

## 6. VAT, payroll, CIS and property events

VAT registration screening must cover the rolling twelve-month taxable-turnover test and the separate forward-looking test; the UK-established threshold reviewed is £90,000. Non-established businesses and special cases differ. All VAT-registered businesses are within MTD VAT unless exempt, not merely those above the registration threshold. Model digital links, schemes, corrections, partial exemption and Northern Ireland goods rules separately. Normal VAT return/payment timing is one calendar month plus seven days, but use actual HMRC obligations and applicable exceptions rather than only a calculated date.

Payroll needs FPS normally on/before payday, applicable EPS normally by the nineteenth of the following tax month, separate remittances, benefits, year-end documents and pension duties. CIS contractors need verification, employment-status consideration, deductions and monthly returns due the nineteenth following the tax month. A CIS subcontractor's deduction is not automatically a business expense or the same thing as a contractor return.

UK property disposals can trigger a separate sixty-day reporting/payment journey; non-resident reporting can apply even without tax due. ATED can require annual and relief declarations even when relief reduces the charge to nil. These event returns must not wait unnoticed for annual accounts. SDLT, Welsh LTT, Scottish LBTT, IHT, trusts and overseas cases remain specialist expansion work rather than assumed launch coverage.

Sources: [VAT registration](https://www.gov.uk/register-for-vat), [MTD VAT](https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat), [VAT deadline](https://www.gov.uk/submit-vat-return), [FPS](https://www.gov.uk/running-payroll/reporting-to-hmrc), [EPS](https://www.gov.uk/running-payroll/reporting-to-hmrc-eps), [CIS](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/file-your-monthly-returns), [property gains](https://www.gov.uk/capital-gains-tax/reporting-and-paying-capital-gains-tax), [ATED](https://www.gov.uk/guidance/annual-tax-on-enveloped-dwellings-returns).

## 7. Charities and other organisations

England/Wales charity annual reporting is normally due within ten months; CIO reporting obligations apply regardless of income, while thresholds and legal form affect other charities' requirements. Scottish OSCR reporting is normally within nine months, Northern Ireland within ten. Do not reuse one jurisdiction's accounts basis, audit/independent-examination thresholds or reporting questions for another. Charitable companies can have both company and charity-regulator duties; charitable status does not establish blanket exemption for every tax or trade. SORP 2026 applies to relevant reporting periods starting on or after 1 January 2026, subject to jurisdictional enabling provisions. Separately, England/Wales threshold changes apply to years ending on or after 30 September 2026: independent-examination income threshold rises to £40,000, the non-company accruals threshold to £500,000, and the principal audit income threshold to £1.5m, with an additional income/assets test. Do not infer that charitable companies can use receipts-and-payments accounts or apply these thresholds to Scotland/NI. Older guides still showing £25,000/£250,000/£1m need period-specific handling. Exact boundary and audit tests require qualification before implementation.

CICs need CIC34 with their annual accounts, including when dormant. Registered co-operative/community benefit societies normally deliver AR30 and accounts to the FCA within seven months. Trust registration is separate from SA900 and can apply to some non-taxable trusts. Clubs and associations may require CT registration/returns despite lacking a company number. These facts require composable obligations rather than a universal “company filing” record.

Sources: [September threshold changes](https://www.gov.uk/guidance/changes-to-charity-accounting-and-reporting), [SORP versions](https://www.charitysorp.org/download-a-full-sorp), [charity return](https://www.gov.uk/guidance/prepare-a-charity-annual-return), [CIO accounts](https://www.gov.uk/government/publications/charity-accounts/charity-accounts-rules-for-charitable-incorporated-organisations-cios), [OSCR](https://www.oscr.org.uk/managing-a-charity/charity-accounting/), [CCNI](https://www.charitycommissionni.org.uk/running-a-charity/annual-reporting/), [CIC](https://www.gov.uk/government/publications/community-interest-companies-how-to-form-a-cic/community-interest-companies-guidance-chapters), [societies](https://www.fca.org.uk/firms/annual-returns-accounts-mutual-societies), [trust registration](https://www.gov.uk/trusts-taxes/registering-a-trust), [association registration](https://www.gov.uk/guidance/register-an-unincorporated-association-for-corporation-tax).

## 8. Filing software and developer API requirements

Corporation Tax uses its XML filing specifications; MTD uses its own APIs/authentication. Do not assume a universal OAuth or universal Government Gateway credential flow. Companies House public information APIs are not a substitute for filing access. Its developer guidance requires relevant test qualification and a presenter account, and anticipates a future XML-to-REST transition without a fixed timetable.

Validate accounts and computational taxonomies independently against current acceptance windows. HMRC's published CT computational 2024 end-date limit is 31 March 2026; it must not be used indiscriminately for later periods. Current CT RIM artefacts were updated in October 2026. New computation-format proposals must be recorded as proposals until required.

MTD production access requires endpoint testing, terms compliance and accurate fraud-prevention data. For OmniXAT's downstream API, collect the required end-user context for the actual connection method; do not invent device data or simply substitute the API server's details. Keep external developer credentials separate from authority tokens and company codes. No credential should enter language-model prompts.

Sources: [CT developer collection](https://www.gov.uk/government/collections/corporation-tax-online-support-for-software-developers), [taxonomies](https://www.gov.uk/government/publications/taxonomies-accepted-by-hm-revenue-and-customs/taxonomies-accepted-by-hmrc), [CT changes](https://www.gov.uk/guidance/changes-and-issues-affecting-the-corporation-tax-online-service), [Companies House developer guidance](https://www.gov.uk/government/publications/technical-interface-specifications-for-companies-house-software/important-information-for-software-developers-read-first), [MTD integration](https://developer.service.hmrc.gov.uk/guides/income-tax-mtd-end-to-end-service-guide/documentation/how-to-integrate.html), [fraud headers](https://developer.service.hmrc.gov.uk/guides/fraud-prevention/).

## 9. Duties of OmniXAT as a commercial operator

### Software versus representation

HMRC's 2026 tax-adviser guidance excludes interaction solely to develop/provide accounting or tax software from agent registration, but paid client representation is different. AML guidance explicitly includes virtual/automated accountancy services. Determine the actual service model before launching managed preparation, advice or filing assistance. Software disclaimers do not decide classification. Record any AML supervision, client-authority and HMRC agent requirements that follow from the chosen model.

Companies House ACSP requirements are another distinct regime. The guidance reviewed currently requires registration for identity-verification agents and describes later extension to all filing agents. Do not present the future phase as already universally commenced. OmniXAT must not offer its own identity-verification service without qualifying that role.

Sources: [tax-adviser registration](https://www.gov.uk/guidance/check-if-and-when-you-need-to-register-as-a-tax-adviser-with-hmrc), [AML scope](https://www.gov.uk/guidance/money-laundering-regulations-accountancy-service-provider-registration), [ACSP](https://www.gov.uk/guidance/being-an-authorised-corporate-service-provider).

### Privacy and security

Apply UK GDPR, DPA 2018 and commenced DUAA changes. Map controller/processor roles by processing purpose, execute suitable processor terms, document subprocessors/transfers, and implement rights, retention and incident workflows. Separate customer records, support access and owner analytics. Assess DPIA need against real processing; do not assume every installation has identical requirements.

Retention is record-specific: self-employed business records normally at least five years after the relevant January deadline; company accounting records generally six years after the relevant financial year; VAT records normally six years with longer OSS/MOSS rules. Enquiries and other legal requirements can extend retention. Cancellation must not trigger immediate deletion of legally retained records; retention must not justify indefinite storage of everything.

HMRC Developer Hub terms include customer separation, security testing, staff access controls, accessibility and accurate product claims. Do not advertise “HMRC recognised” before completing the relevant process, or “HMRC approved”. Provide WCAG AA journeys and security-incident reporting appropriate to the actual integrations. ICO breach reporting and contractual HMRC notification are distinct assessments.

Sources: [ICO privacy by design](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/accountability-and-governance/guide-to-accountability-and-governance/data-protection-by-design-and-by-default), [self-employed retention](https://www.gov.uk/self-employed-records/how-long-to-keep-your-records), [company records](https://www.gov.uk/running-a-limited-company/company-and-accounting-records), [VAT retention](https://www.gov.uk/charge-reclaim-record-vat/keeping-vat-records), [developer terms](https://developer.service.hmrc.gov.uk/api-documentation/docs/terms-of-use).

### Subscriptions and API sales

Distinguish business customers from consumers using the actual contract/purpose, not just a checkbox or whether the customer is an individual. Build clear trial-to-paid consent, pricing, renewal notices, cancellation, refunds and durable terms records. October 2026 subscription material links to a PDF explicitly labelled **draft** and draft regulations subject to parliamentary approval, despite the landing page's more definite description. Treat its proposed commencement date as unconfirmed; do not deploy it as current law. Existing consumer rights and fair commercial practices still require assessment.

Use hosted/tokenised payment collection; keep card details outside OmniXAT. Model platform subscription VAT and invoicing separately from customers' VAT returns. Export and reasonable record access must be considered when a subscription expires, without promising indefinite free service. Prices must be immutable versions; changes for new sales must not silently reprice existing contracts. Notice/consent requirements must be determined before migrating subscribers.

Sources: [subscription guidance landing page](https://www.gov.uk/government/publications/subscription-contracts), [linked draft guidance](https://assets.publishing.service.gov.uk/media/6acf97da2de3184ccf8b814e/subscription-contracts-rules-guidance.pdf). Payment architecture and price versioning are engineering proposals, not findings that a particular provider has been selected or approved.

## 10. Release gates and maintenance

Each module needs a versioned source set, applicability rules, deterministic calculation fixtures, independent review, document rendering/tag checks, authority test evidence and explicit production capability status. Changes to law, standards, taxonomies, API versions and future commencement dates enter a review queue. Automated discovery can flag changes; it must not autonomously promote legal rules to production.

Store checked date, effective-from/to basis, source URL, legal status, supported years, review owner and test evidence. Marketing and billing entitlements must use the same capability registry as the API: selling a plan never enables an unqualified filing channel. Preserve unknown/pending outcomes and reconcile before retrying. Customer approval must cover the actual outgoing document, destination and environment.

Before release: decide operator service classification; qualify each advertised filing; test tenant isolation and account recovery; complete payment/webhook reconciliation; verify backup restore; test support access; verify accessible critical journeys; approve customer terms/privacy; and run an operational rehearsal. These are concrete unresolved launch requirements, not reasons to stop internal development.

## Development started

The first commercial slice adds tested internal permission checks, immutable in-memory price versions, artifact-bound approvals, researched MTD/ordinary-deadline/revision helpers and the rule catalogue. These components have no network filing/payment authority. Persistence, identity integration, owner dashboard, hosted billing and production API transport remain subsequent implementation work. See `COMMERCIAL_SPEC.md` and `commercial/README.md` for the exact scope.
