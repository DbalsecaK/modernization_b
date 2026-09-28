---
name: webforms
description: "ViewState, postbacks, code-behind, server controls and web.config."
metadata:
  title: "ASP.NET WebForms"
  version: 0.6.0
  type: source
  applies_to:
    agents: ["legacy-analyst", "ui-analyst", "rules-extractor"]
    technologies: ["aspx-webforms"]
  conflicts: []
  requires: []
  status: evaluating
  eval_score: null
---
# ASP.NET WebForms

- **Page lifecycle:** Init → Load → control events → PreRender → Render. Logic in `Page_Load` usually branches on
  `IsPostBack`.
- **ViewState** keeps control state between postbacks; business state often hides there.
- **Code-behind** event handlers hold the business logic; server controls (GridView, SqlDataSource…) carry
  implicit data access.
- **web.config** holds connection strings, appSettings and authorization rules.
- **Session and Application** state are shared between requests: make every dependency explicit.
