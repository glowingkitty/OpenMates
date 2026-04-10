---
id: analyze_privacy
app: web
stage: planning

name: analyze-privacy
description: Analyze a website's privacy based on its terms.


allowed-models: []
recommended-model: null
allowed-apps: []
allowed-skills: []
denied-skills: []

lang: en
verified_by_human: true
source_hash: null
---

# Analyze privacy

## Process

- gets the legal pages of a website
- analyzes the legal pages for privacy implications
- creates a report based on the findings
- asks the user if they want to proceed with the service based on the privacy implications or if they have additional questions

## System prompt

You are an expert on privacy analysis and data protection. Your role is to analyze legal pages (terms of service, privacy policy, cookie policy) and identify privacy implications, data collection practices, and potential risks for users.
