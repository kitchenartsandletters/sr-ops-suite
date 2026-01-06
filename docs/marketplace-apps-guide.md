# Google Workspace Marketplace Apps Guide  
_Internal vs Public Distribution & Release Checklist_

This document serves as a reusable reference for developing, deploying, and maintaining **Google Workspace Marketplace apps**, with a focus on **Sheets Add-ons built with Apps Script**.

It is intended to prevent common deadlocks around authorization, versioning, visibility, and publishing.

---

## App Types at a Glance

| App Type | Audience | Review Required | Typical Use Case |
|---|---|---|---|
| **Internal App** | Single Workspace domain | No external review | Internal ops tools, finance, inventory, reporting |
| **Public App** | Any Workspace user | Yes (Google review) | SaaS products, partner tools, external integrations |

---

## Internal Marketplace Apps

### Characteristics
- Restricted to a single Google Workspace domain
- Discoverable under **Marketplace → My domain apps**
- Can be admin-installed domain-wide
- Still require a complete Store Listing (icons, screenshots, URLs)

### When to choose Internal
- Tool is operational or administrative
- Users are non-technical staff
- You want fast iteration without review delays
- Data access should remain domain-contained

### Required Components
- User-managed GCP project
- OAuth consent screen set to **Internal**
- Apps Script Add-on deployment (versioned)
- Marketplace SDK configuration:
  - Visibility: **Private**
  - Integration: **Sheets add-on**
  - Script ID + Version
- Store Listing assets:
  - Icons (128×128, 32×32)
  - Application card banner (220×140)
  - Screenshot (1280×800)
  - Privacy / Terms / Support URLs

### Common Pitfalls
- App invisible due to incomplete Store Listing
- “Help-only” menu due to missing `onInstall(e)`
- Old behavior because Marketplace SDK still points to a prior version
- Broken auth due to deleted OAuth client in GCP

---

## Public Marketplace Apps

### Characteristics
- Discoverable by all Google Workspace users
- Subject to Google’s Marketplace review process
- Longer approval cycles
- Higher documentation and policy standards

### When to choose Public
- External users or customers
- Revenue-generating tools
- Partner or platform integrations
- Long-lived, version-stable products

### Additional Requirements
- Strong privacy policy (often external website)
- Clear terms of service
- Detailed screenshots and descriptions
- Scope justification during review
- Stable release cadence (frequent changes can trigger re-review)

### Operational Considerations
- Expect review delays (days to weeks)
- Breaking changes may require re-approval
- Maintain backward compatibility where possible
- Plan a staging or internal testing project

---

## Auth & Lifecycle Rules (Critical)

### Add-on Initialization
- Marketplace Add-ons may load in `AuthMode.NONE`
- UI and authenticated services may be unavailable initially

**Best Practice**
```js
function onInstall(e) {
  onOpen(e);
}

function onOpen(e) {
  SpreadsheetApp.getUi()
    .createAddonMenu()
    .addItem('Run Tool', 'main')
    .addToUi();
}
```

- Always use `createAddonMenu()` for Sheets Add-ons
- Keep menu construction minimal

---

## Versioning Model

- Marketplace never runs “HEAD”
- Only **numbered deployments** are installable
- Marketplace SDK must explicitly point to the active version

**Golden Rule**
> Code is not live until the Marketplace SDK version is updated.

---

## Release Checklist (Use Before Every Deployment)

### Apps Script
- [ ] Code changes complete and reviewed
- [ ] `onInstall(e)` present and calls `onOpen(e)`
- [ ] `createAddonMenu()` used (not `createMenu()`)
- [ ] New external URLs added to manifest allowlist (if applicable)
- [ ] OAuth scopes reviewed and minimized

### Deployment
- [ ] New **Add-on** deployment created
- [ ] Deployment version number recorded

### Marketplace SDK
- [ ] Sheets add-on script version updated to new deployment
- [ ] App Configuration saved successfully
- [ ] (If required) Store Listing assets unchanged or updated

### Verification
- [ ] Waited 5–10 minutes for cache propagation
- [ ] Tested in a **new** Google Sheet
- [ ] Menu appears under Extensions → Add-ons
- [ ] Tool runs without errors
- [ ] Expected data written correctly

### Rollback (if needed)
- [ ] Previous stable version number identified
- [ ] Marketplace SDK reverted to prior version
- [ ] Verification re-run

---

## Safety Rules

- Never delete OAuth clients tied to an active Apps Script project
- Never change Script ID without planning a new Marketplace listing
- Avoid unnecessary scope expansion
- Treat Marketplace SDK version updates as production releases

---

## Recommended Docs to Keep Alongside This Guide
- Project-specific README.md
- CHANGELOG.md (Marketplace version → changes)
- Admin install SOP (for IT / Workspace Admins)

---

End of guide.
