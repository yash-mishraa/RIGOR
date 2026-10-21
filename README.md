# RIGOR Interview Workbench

A client-side practice workbench for technical interview preparation and resume review. It has no authentication, backend, or upload service: resume parsing and analysis happen in the browser, and practice data is saved to local storage on the current device.

## Run locally

```sh
npm install
npm run dev
```

To create a production build:

```sh
npm run build
npm run preview
```

## Features

- Eight job-position practice tracks with role-specific topics and question banks: backend, frontend, AI/ML systems, cloud/platform, data infrastructure, security, systems, and distributed systems.
- Resume-driven practice questions for every extracted experience bullet and recognized technology, in addition to the selected role's topic drills.
- Resume import for PDF, DOCX, TXT, and Markdown, plus an editable text buffer.
- A role-specific ATS-friendly format review with a visible heuristic score, strengths, limitations, and suggested fixes. It is guidance, not an official ETS or ATS evaluation.
- LaTeX rendering across static and dynamically generated views via MathJax.
- Interview drills, response evaluation, answer references, architecture scenarios, capacity estimation, progress tracking, and Markdown export.

PDF/DOCX parsing and LaTeX rendering load their browser libraries from public CDNs. The app has no authentication flow and sends no resume content to an application server.
