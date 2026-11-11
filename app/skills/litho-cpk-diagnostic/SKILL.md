---
name: litho-cpk-diagnostic
description: Diagnose a confirmed LITHO capability (Cpk) excursion over a bounded time range using the controlled named workflow. Use when a user asks why lithography Cpk dropped or whether LITHO capability is abnormal in a given period.
metadata:
  domain: manufacturing
  process_step: LITHO
---

# Lithography Cpk diagnostic

Use this Skill only for a confirmed LITHO capability-excursion request with a
bounded time range. The controlled workflow supplies the existing capability
Playbook and named planner, plus a weekly Cpk trend as optional context. Treat
tool results as evidence, disclose gaps, and do not propose automatic
production changes.

Read the weekly trend to tell a sustained capability drop from a single bad
week; it does not replace the equipment-level Cpk evidence.

This package does not grant tool permissions or execute database queries.
Use the exact evidence-policy version supplied by the trusted host. A completed
check is not a passing diagnosis. If the required check is unavailable, report
that limitation; model knowledge cannot replace it. A knowledge-source label
alone does not certify an approved, effective SOP.
